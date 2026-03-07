"""
conversational_agent.py — AI Brain for Prospecting
Handles inbound WhatsApp messages via GPT-4o-mini.

Two specific modes:
1. handle_warm_up_response (Branch A): Classifies the contact (A/B/C/D), generates
   a personalized transition message, and dispatches the main sequence.
2. handle_conversation_reply (Branch B): Main conversation loop handling objections,
   scheduling meetings, and detecting terminal states.
"""

import os
import json
import logging
import asyncio
from typing import Dict, Any

from dotenv import load_dotenv
from openai import OpenAI

from execution.manage_leads import (
    get_lead,
    update_lead,
    update_status,
    append_conversation
)
from execution.send_whatsapp import send_followup, send_sequence, send_notification

# Attempt to load calendar module (P8) - graceful fallback if not yet implemented
try:
    from execution.check_calendar import get_available_slots, book_slot
except ImportError:
    def get_available_slots(): 
        return ["Nenhum horário disponível no momento (sistema em manutenção)."]
    def book_slot(date: str, time: str, name: str, number: str): 
        return None

load_dotenv()

logger = logging.getLogger(__name__)

# Configure OpenAI client
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
AGENT_MODEL = os.getenv("AGENT_MODEL", "gpt-4o-mini")

# Admin Team Notification
TEAM_NOTIFICATION_NUMBER = os.getenv("TEAM_NOTIFICATION_NUMBER", "")

# --- SYSTEM PROMPT FRAGMENTS ---

IDENTITY_BLOCK = """
Você é um membro da equipe comercial da agência Behind, especializada em criar sites profissionais e de alta conversão para médicos(as).
Seu objetivo é agendar uma breve reunião de 20 minutos (via Google Meet) para apresentar como o site trabalha pela imagem e atração de pacientes particulares do médico.
- Seja cordial, empático e extremamente profissional.
- NUNCA diga que é uma inteligência artificial (AI). Aja como uma pessoa real da equipe.
- NUNCA invente informações sobre os serviços da Behind, preços, ou cases de sucesso que não existam.
- Se não souber responder algo complexo, diga que a dúvida será esclarecida em detalhes na reunião.
- Suas mensagens devem ser CURTAS. Uma ideia por mensagem. Nunca mande blocos gigantes de texto.
- Use um tom de voz adequado ao nível de formalidade médica, mas com a agilidade do WhatsApp.
- NÃO use emojis em excesso.
"""

OBJECTION_PLAYBOOK = """
Playbook de Objeções:
- "Já tenho site": "Que ótimo! Como ele tem performado para atrair pacientes particulares? Nosso foco é justamente transformar o site em um motor de resultados, não apenas um cartão de visitas. Posso te mostrar como fazemos isso na reunião de 20 min?"
- "Sem tempo" / "Correria": "Entendo perfeitamente a rotina de consultório! São só 20 minutinhos, super direto ao ponto, e posso me adaptar ao seu horário. O que acha?"
- "Quanto custa?": "Temos diferentes escopos dependendo do seu momento, mas na reunião eu te apresento tudo com os detalhes de valores! Vale muito a pena conhecer."
- "Não me interessa" / "Não quero": Responda de forma educada, desejando sucesso e dizendo estar à disposição no futuro (Isso fará com que o sistema marque o lead como perdido/opt-out).
- "Quem é você?": "Sou da equipe comercial da Behind! Somos uma agência especializada em sites para médicos."
"""

# =====================================================================
# BRANCH A: WARM-UP RESPONSE (CLASSIFICATION)
# =====================================================================

def handle_warm_up_response(lead_id: int, message: str) -> None:
    """
    Called by webhook when a lead responds to the initial warm-up message.
    1. Classify lead A/B/C/D.
    2. Generate personalized reply bridging to the sequence.
    3. Send personalized reply.
    4. Trigger 5-part sequence.
    """
    logger.info("Agent processing warm-up response for lead %d", lead_id)
    lead = get_lead(lead_id)
    if not lead:
        return

    hist_json = lead.get("conversation_history", "[]")
    history = json.loads(hist_json)
    
    # We only care about the last message (the lead's reply to our warm-up)
    
    prompt = f"""
Baseado na resposta do lead à nossa mensagem inicial de contato (warm-up), classifique quem está respondendo e gere uma mensagem curta e educada de transição.

Dados do lead:
- Nome extraído Instagram: {lead.get('formatted_name')}
- Username: {lead.get('username')}
- Mensagem recebida: "{message}"

REGRAS DE CLASSIFICAÇÃO:
"A" - Médico(a) respondendo diretamente, de forma positiva ou neutra.
"B" - Secretária ou Auxiliar respondendo.
"C" - Médico(a) aparentemente ocupado ou resistente.
"D" - Outro (clínica genérica, não deu para identificar). Se em dúvida, use D.

A MENSAGEM DE TRANSIÇÃO (personalized_reply):
- Deve ter no máximo 1 ou 2 frases.
- Deve agradecer ou comentar rapidamente a resposta, e avisar que vai mandar a capa que a equipe preparou.
- Exemplo se foi a secretária: "Ah, perfeito! Obrigada pelo retorno. A nossa equipe de design preparou um material..."
- Exemplo se foi o médico: "Que ótimo, Dr(a). {lead.get('formatted_name')}! O motivo do meu contato é que a nossa equipe..."

RETORNE APENAS UM JSON VÁLIDO. Nenhuma outra palavra.
{{
    "classification": "A" (ou B, C, D),
    "personalized_reply": "sua mensagem aqui"
}}
"""

    try:
        response = client.chat.completions.create(
            model=AGENT_MODEL,
            messages=[
                {"role": "system", "content": "Você é um classificador automático de mensagens de prospecção. Responda apenas com JSON."} ,
                {"role": "user", "content": prompt}
            ],
            temperature=0.3
        )
        
        content = response.choices[0].message.content.strip()
        if content.startswith("```json"): content = content[7:-3]
        elif content.startswith("```"): content = content[3:-3]
        
        result = json.loads(content)
        classification = result.get("classification", "B")
        if classification not in ("A", "B", "C", "D"):
            classification = "B"
            
        reply_msg = result.get("personalized_reply", f"Perfeito! O motivo do meu contato é que nossa equipe preparou um material para o perfil da Dra.")
        
        # 1. Update classification in DB
        update_lead(lead_id, contact_classification=classification)
        logger.info("Lead %d classified as %s", lead_id, classification)
        
        # 2. Send personalized reply
        send_followup(lead_id, reply_msg)
        
        # 3. Trigger Sequence
        logger.info("Dispatching sequence for lead %d", lead_id)
        send_sequence(lead_id)
        
    except Exception as e:
        logger.error("Failed to process warm-up classification for lead %d: %s", lead_id, e)
        # Fallback: Just trigger sequence B
        update_lead(lead_id, contact_classification="B")
        send_sequence(lead_id)


# =====================================================================
# BRANCH B: ONGOING CONVERSATION
# =====================================================================

def handle_conversation_reply(lead_id: int, message: str) -> None:
    """
    Main conversational loop. Handles objections, scheduling, and opt_outs.
    """
    logger.info("Agent processing conversation reply for lead %d", lead_id)
    lead = get_lead(lead_id)
    if not lead:
        return
        
    # Standardize calendar slots context
    slots = get_available_slots()
    slots_str = "\\n".join(slots) if slots else "Nenhum horário disponível no momento. Ofereça disponibilidade flexível e peça para o lead sugerir um horário."

    # Format history for prompt
    hist_json = lead.get("conversation_history", "[]")
    history = json.loads(hist_json)
    
    formatted_history = ""
    for msg in history:
        role_pt = "Lead" if msg["role"] == "lead" else "Você (Behind)"
        formatted_history += f"[{msg['timestamp']}] {role_pt}: {msg['message']}\n"

    system_prompt = f"""
{IDENTITY_BLOCK}

{OBJECTION_PLAYBOOK}

STATUS DO LEAD: Em conversação.

OPÇÕES DE AGENDA DISPONÍVEIS AGORA:
{slots_str}
Regra de Agendamento: Se o lead demonstrar interesse, ofereça exatas 2 ou 3 opções textuais dessa lista.
Se o lead escolheu ou confirmou um horário, confirme alegremente e diga que o convite do Meet chegará em breve. VOCÊ DEVE MARCAR A AÇÃO COMO "book_calendar".

INSTRUÇÕES DE RESPOSTA (JSON):
Você deve analisar o hitórico da conversa e a última mensagem do Lead, e decidir sua resposta e qual ação o sistema deve tomar.

Ações possíveis (action):
- "none": Apenas enviar a mensagem de resposta. Maioria dos casos.
- "book_calendar": O lead acabou de CONFIRMAR um horário específico. Use isso para avisar o sistema para registrar a reunião.
- "ask_calendar": Você ofereceu opções e está esperando a pessoa escolher (apenas marcacional, age como none).

Atualização de Status (status_update):
- "unchanged": A conversa continua normalmente.
- "meeting_scheduled": O lead topou a reunião e confirmou o horário. (Terminal)
- "lost": O lead disse expressamente que NÃO quer, não tem interesse algum, ou foi rude, e já tentamos reverter ou não vale a pena reverter. Encerramento educado. (Terminal)
- "opt_out": O lead pediu para parar de mandar mensagem, tirar da lista, bloqueou, etc. (Terminal)

Responda APENAS em JSON estrito. Nenhuma marcação Markdown fora do JSON.
{{
    "response": "Sua resposta curta, educada e direta para o lead",
    "status_update": "unchanged" | "meeting_scheduled" | "lost" | "opt_out",
    "action": "none" | "book_calendar" | "ask_calendar",
    "internal_thought": "sua justificativa rápida do porquê tomou essa decisão"
}}
"""

    try:
        response = client.chat.completions.create(
            model=AGENT_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Histórico de Conversa:\n{formatted_history}"}
            ],
            temperature=0.4
        )
        
        content = response.choices[0].message.content.strip()
        if content.startswith("```json"): content = content[7:-3]
        elif content.startswith("```"): content = content[3:-3]
        
        result = json.loads(content)
        reply_msg = result.get("response", "Entendido! Qualquer dúvida estou à disposição.")
        status_update = result.get("status_update", "unchanged")
        action = result.get("action", "none")
        
        logger.info("Agent decision for lead %d: status=%s, action=%s, thought=%s", 
                    lead_id, status_update, action, result.get("internal_thought", ""))
        
        # 1. Send the response via WhatsApp
        success = send_followup(lead_id, reply_msg)
        
        # 2. Handle specific actions
        if action == "book_calendar":
            # Assuming the AI successfully confirmed a slot in the text.
            # In a full v1, we'd parse the chosen date/time out or have a separate tool call.
            # For now, we mock the booking function behavior from check_calendar.
            book_slot("TBD", "TBD", lead.get("formatted_name", ""), lead.get("whatsapp_number", ""))
            
        # 3. Update Status and notify team if terminal
        if status_update in ("meeting_scheduled", "lost", "opt_out"):
            update_status(lead_id, status_update)
            lead_name = lead.get("formatted_name", "Desconhecido")
            lead_phone = lead.get("whatsapp_number", "")
            
            notification_detail = ""
            if status_update == "meeting_scheduled":
                notification_detail = "Reunião Agendada! O lead confirmou horário."
            elif status_update == "lost":
                notification_detail = f"Lead perdido. Motivo aparente no histórico."
            elif status_update == "opt_out":
                notification_detail = "Solicitou remoção/Opt-out."
                
            notification_msg = f"[STATUS: {status_update.upper()}] Lead: {lead_name} | Number: {lead_phone} | Detail: {notification_detail}"
            send_notification(TEAM_NOTIFICATION_NUMBER, notification_msg)
            
    except Exception as e:
        logger.error("Failed to process conversation reply for lead %d: %s", lead_id, e)
        # Fallback response in case of hard failure, only if we haven't sent anything yet
        send_followup(lead_id, "Desculpe, tivemos uma pequena falha de conexão. Poderia repetir?")


# =====================================================================
# BRANCH C: SYSTEM-INITIATED FOLLOW-UP (QUEUE DISPATCHER)
# =====================================================================

def generate_system_followup(lead_id: int, is_friday_cleanup: bool = False) -> None:
    """
    Called by queue_dispatcher.py. 
    Agent evaluates the history. If is_friday_cleanup=True, agent decides if
    the interaction is dead and marks lost. Otherwise, generates a gentle follow-up.
    """
    logger.info("Agent processing system follow-up for lead %d (cleanup=%s)", lead_id, is_friday_cleanup)
    lead = get_lead(lead_id)
    if not lead:
        return
        
    hist_json = lead.get("conversation_history", "[]")
    history = json.loads(hist_json)
    
    formatted_history = ""
    for msg in history:
        role_pt = "Lead" if msg["role"] == "lead" else "Você (Behind)"
        formatted_history += f"[{msg['timestamp']}] {role_pt}: {msg['message']}\n"

    cleanup_prompt = """
Hoje é sexta-feira, dia de faxina de funil. Avalie o histórico.
Se o lead demonstrou ZERO interesse a semana toda (só respostas curtas, vácuos, sem perguntas), marque 'status_update' como 'lost' e crie uma mensagem de encerramento educada em 'response'.
Se houve QUALQUER sinal de interesse que justifique insistir na semana que vem, apenas retorne 'unchanged' e não envie mensagem (response="").
""" if is_friday_cleanup else """
O lead parou de responder. Crie uma mensagem curta, amigável e MUITO natural para puxar assunto novamente e tentar agendar a reunião.
Se a conversa estiver esfriando demais, você DEVE analisar se vale a pena continuar ou se já é hora de marcar como 'lost'.
"""

    system_prompt = f"""
{IDENTITY_BLOCK}

STATUS DO LEAD: Aguardando Resposta (Follow-up de Sistema)

{cleanup_prompt}

INSTRUÇÕES DE RESPOSTA (JSON):
Você deve analisar o histórico da conversa e decidir qual mensagem de retorno enviar.

Atualização de Status (status_update):
- "unchanged": A conversa continua (follow-up enviado).
- "lost": O lead não demonstrou interesse, não vale a pena fazer follow-up. Encerramento educado. (Terminal)

Ação (action):
- "none": envie a mensagem normalmente.
- "skip": se você achar que não deve mandar NADA agora (por ex, no friday cleanup).

Responda APENAS em JSON estrito.
{{
    "response": "Sua mensagem (ou deixe vazio se action=skip)",
    "status_update": "unchanged" | "lost",
    "action": "none" | "skip",
    "internal_thought": "sua justificativa rápida"
}}
"""

    try:
        response = client.chat.completions.create(
            model=AGENT_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Histórico de Conversa:\n{formatted_history}"}
            ],
            temperature=0.4
        )
        
        content = response.choices[0].message.content.strip()
        if content.startswith("```json"): content = content[7:-3]
        elif content.startswith("```"): content = content[3:-3]
        
        result = json.loads(content)
        reply_msg = result.get("response", "")
        status_update = result.get("status_update", "unchanged")
        action = result.get("action", "none")
        
        logger.info("Agent follow-up decision for lead %d: status=%s, action=%s, thought=%s", 
                    lead_id, status_update, action, result.get("internal_thought", ""))
        
        if action != "skip" and reply_msg:
            send_followup(lead_id, reply_msg)
            
        if status_update == "lost":
            update_status(lead_id, "lost")
            lead_name = lead.get("formatted_name", "Desconhecido")
            lead_phone = lead.get("whatsapp_number", "")
            notification_msg = f"[STATUS: LOST] Lead: {lead_name} | Number: {lead_phone} | Detail: Marcado como perdido pelo agente de Follow-up (cleanup={is_friday_cleanup})"
            send_notification(TEAM_NOTIFICATION_NUMBER, notification_msg)
            
    except Exception as e:
        logger.error("Failed to process system follow-up for lead %d: %s", lead_id, e)
