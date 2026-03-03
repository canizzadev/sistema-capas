import os
import io
import re
import math
import zipfile
import colorsys
import base64
import logging
import textwrap
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from google import genai
from google.genai import types
from reportlab.lib.pagesizes import landscape, A4
from reportlab.pdfgen import canvas as pdf_canvas
from reportlab.lib.utils import ImageReader
from dotenv import load_dotenv

from execution.scrape_instagram import scrape_profile
from execution.generate_titles import generate_titles

load_dotenv()

logger = logging.getLogger(__name__)

# --- STEP 0: Utilities ---

def validate_hex_color(hex_code: str) -> str:
    """Validates and normalizes a hex color string. Returns a valid 7-char hex or fallback."""
    if not hex_code or not isinstance(hex_code, str):
        logger.warning("Invalid hex color input: %r, using fallback #27AE60", hex_code)
        return "#27AE60"
    hex_code = hex_code.strip().lstrip('#')
    # Support 3-char shorthand (e.g. "F0A" -> "FF00AA")
    if len(hex_code) == 3 and all(c in '0123456789abcdefABCDEF' for c in hex_code):
        hex_code = ''.join(c * 2 for c in hex_code)
    if len(hex_code) != 6 or not all(c in '0123456789abcdefABCDEF' for c in hex_code):
        logger.warning("Invalid hex color '#%s', using fallback #27AE60", hex_code)
        return "#27AE60"
    return f"#{hex_code.upper()}"

def hex_to_rgb(hex_code: str):
    hex_code = hex_code.lstrip('#')
    return tuple(int(hex_code[i:i+2], 16) for i in (0, 2, 4))

def rgb_to_hex(r: int, g: int, b: int) -> str:
    return '#{:02x}{:02x}{:02x}'.format(r, g, b).upper()

def hex_to_hsl(hex_code: str):
    r, g, b = hex_to_rgb(hex_code)
    return colorsys.rgb_to_hls(r/255.0, g/255.0, b/255.0)

def hsl_to_hex(h: float, l: float, s: float) -> str:
    r, g, b = colorsys.hls_to_rgb(h, l, s)
    return rgb_to_hex(int(r*255), int(g*255), int(b*255))

def lighten_color_hex(brand_hex: str, delta: float = 0.35) -> str:
    h, l, s = hex_to_hsl(brand_hex)
    l = max(0.0, min(1.0, l + delta))
    return hsl_to_hex(h, l, s)

def darken_color_hex(brand_hex: str, delta: float = 0.10) -> str:
    h, l, s = hex_to_hsl(brand_hex)
    l = max(0.0, min(1.0, l - delta))
    return hsl_to_hex(h, l, s)

def safe_load_font(path: str, size: int):
    try:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    except Exception:
        pass
    return None

def draw_text_with_tracking(draw: ImageDraw.Draw, xy: tuple, text: str, font, fill, tracking_px: int):
    x, y = xy
    for char in text:
        draw.text((x, y), char, font=font, fill=fill)
        if font:
            try:
                bbox = draw.textbbox((0, 0), char, font=font)
                char_width = bbox[2] - bbox[0]
            except AttributeError:
                char_width, _ = draw.textsize(char, font=font)
        else:
            char_width = 8 
        x += char_width + tracking_px

def parse_city_from_text(text: str) -> str:
    if not text:
        return ""
    uf_pattern = r'\b(AC|AL|AP|AM|BA|CE|DF|ES|GO|MA|MT|MS|MG|PA|PB|PR|PE|PI|RJ|RN|RS|RO|RR|SC|SP|SE|TO)\b'
    match = re.search(r'([A-ZÁÉÍÓÚÂÊÔÃÕÇ][a-záéíóúâêôãõç]+(?: [A-ZÁÉÍÓÚÂÊÔÃÕÇ][a-záéíóúâêôãõç]+)*)\s*[,/\-]\s*' + uf_pattern, text)
    if match:
        return f"{match.group(1)} - {match.group(2)}"
    match = re.search(r'([A-Za-zÀ-ÖØ-öø-ÿ\s]+)\s*[,/\-]\s*' + uf_pattern, text)
    if match:
        city = match.group(1).strip()
        if len(city) > 2 and len(city) < 30:
            return f"{city} - {match.group(2)}"
    return ""

def balance_text(text):
    """Quebra o texto garantindo que a primeira linha seja sempre maior ou igual à segunda."""
    if not text or not text.strip():
        return [""]
    text = text.strip()
    words = text.split()
    # Very short text (fewer than 5 words or under 50 chars): keep on one line
    if len(words) < 5 or len(text) < 50:
        return [text]
    # Very long text (more than 20 words): cap at two lines, truncate with ellipsis
    if len(words) > 20:
        logger.warning("Headline too long (%d words), truncating to 20", len(words))
        words = words[:20]
        words[-1] = words[-1].rstrip('.!') + '...'
        text = " ".join(words)
    best_split = 0
    min_diff = len(text)

    for i in range(1, len(words)):
        line1 = " ".join(words[:i])
        line2 = " ".join(words[i:])

        if len(line1) >= len(line2):
            diff = len(line1) - len(line2)
            if diff < min_diff:
                min_diff = diff
                best_split = i

    if best_split > 0:
        return [" ".join(words[:best_split]), " ".join(words[best_split:])]
    else:
        return [text]

# --- Main Pipeline ---

def generate_cover_zip(photo_bytes: bytes, brand_color: str, instagram_url: str) -> bytes:
    brand_color = validate_hex_color(brand_color)
    logger.info("Generating cover for '%s' with brand color %s", instagram_url, brand_color)
    profile_data = scrape_profile(instagram_url)
    
    if "error" in profile_data:
        formatted_name = "Dr. Nome Completo"
        specialty_line = "Especialista"
        headline = "Descubra a melhor versão da sua pele com leveza e naturalidade!"
        raw_bio = ""
    else:
        gpt_data = generate_titles(profile_data["name"], profile_data["bio"])
        formatted_name = gpt_data.get("formatted_name", profile_data["name"] or "Dr. Nome Completo")
        specialty_line = gpt_data.get("specialty_line", "Especialista")
        headline = gpt_data.get("headline", "")
        raw_bio = profile_data.get("bio", "")
    
    prefix = "Dr."
    if formatted_name.lower().startswith("dra"):
        prefix = "DRA."
        name_no_prefix = formatted_name[4:].strip() if formatted_name.lower().startswith("dra.") else formatted_name[3:].strip()
    elif formatted_name.lower().startswith("dr"):
        prefix = "DR."
        name_no_prefix = formatted_name[3:].strip() if formatted_name.lower().startswith("dr.") else formatted_name[2:].strip()
    else:
        name_no_prefix = formatted_name
    
    if name_no_prefix.startswith("."):
        name_no_prefix = name_no_prefix[1:].strip()
        
    name_words = name_no_prefix.split()
    if len(name_words) > 1:
        name_no_prefix = f"{name_words[0]} {name_words[-1]}"
        
    specialty_line = re.sub(r'[\s\-\–\—]+$', '', specialty_line)
    
    city_text = parse_city_from_text(raw_bio)
    
    # --- STEP 2: Expansão de Imagem ---
    original_image = Image.open(io.BytesIO(photo_bytes)).convert("RGB")
    img_byte_arr = io.BytesIO()
    original_image.save(img_byte_arr, format='JPEG', quality=95)
    safe_photo_bytes = img_byte_arr.getvalue()
    
    gemini_image = None
    try:
        client = genai.Client()
        response = client.models.generate_content(
            model='gemini-2.5-flash-image',
            contents=[
                types.Part.from_bytes(data=safe_photo_bytes, mime_type='image/jpeg'),
                'I want to outpainting this image to a 16:9 landscape format. Keep the person on the right third of the frame. Maintain the exact same background and style.'
            ],
            config=types.GenerateContentConfig(
                response_modalities=["IMAGE"],
                image_config=types.ImageConfig(aspect_ratio="16:9")
            )
        )
        if response.candidates and response.candidates[0].content.parts:
            img_bytes = response.candidates[0].content.parts[0].inline_data.data
            gemini_image = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    except Exception as e:
        logger.warning("Gemini expansion failed, falling back to mirror-blur: %s", e)
        gemini_image = None
        
    bg_img = Image.new("RGB", (1920, 1000), (0, 0, 0))
    if gemini_image:
        gw, gh = gemini_image.size
        target_ratio = 1920 / 1000.0
        current_ratio = gw / gh
        if current_ratio > target_ratio:
            new_h = 1000
            new_w = int(new_h * current_ratio)
            gemini_image = gemini_image.resize((new_w, new_h), Image.Resampling.LANCZOS)
            left = new_w - 1920
            gemini_image = gemini_image.crop((left, 0, new_w, 1000))
        else:
            new_w = 1920
            new_h = int(new_w / current_ratio)
            gemini_image = gemini_image.resize((new_w, new_h), Image.Resampling.LANCZOS)
            top = (new_h - 1000) // 2
            gemini_image = gemini_image.crop((0, top, 1920, top + 1000))
        bg_img.paste(gemini_image, (0, 0))
    else:
        orig_w, orig_h = original_image.size
        new_h = 1000
        new_w = int((orig_w / orig_h) * new_h)
        sharp = original_image.resize((new_w, new_h), Image.Resampling.LANCZOS)
        bg_stretched = sharp.resize((1920, 1000), Image.Resampling.LANCZOS)
        blurred = bg_stretched.filter(ImageFilter.GaussianBlur(radius=80))
        bg_img.paste(blurred, (0, 0))
        x_pos = min(int(1920 * 0.60), max(0, 1920 - new_w))
        bg_img.paste(sharp, (x_pos, 0))
        
    # --- STEP 3: Composite cover ---
    overlay = Image.new("RGBA", (1920, 1000), (0, 0, 0, 0))
    gradient_width = int(1920 * 0.48) 
    for px in range(gradient_width):
        alpha = int(190 * (1.0 - (px / gradient_width)))
        for py in range(1000):
            overlay.putpixel((px, py), (0, 0, 0, alpha))
            
    final_img = Image.alpha_composite(bg_img.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(final_img)
    
    fonts_dir = "static/fonts"
    font_name = safe_load_font(os.path.join(fonts_dir, "TheSeasons-Regular.ttf"), 102) or safe_load_font(os.path.join(fonts_dir, "CormorantGaramond-Regular.ttf"), 102)
    font_specialty = safe_load_font(os.path.join(fonts_dir, "Poppins-SemiBold.ttf"), 20)
    font_headline = safe_load_font(os.path.join(fonts_dir, "Poppins-Regular.ttf"), 20)
    font_btn = safe_load_font(os.path.join(fonts_dir, "Poppins-Regular.ttf"), 18) 
    font_city = safe_load_font(os.path.join(fonts_dir, "AtypDisplay-Regular.ttf"), 16) or safe_load_font(os.path.join(fonts_dir, "Poppins-Regular.ttf"), 16)
    
    def_font = ImageFont.load_default()
    font_name = font_name or def_font
    font_specialty = font_specialty or def_font
    font_headline = font_headline or def_font
    font_btn = font_btn or def_font
    font_city = font_city or def_font
    
    # Coordenadas Mapeadas do Figma
    base_x = int(320)
    curr_y = int(240)
    
    # Prefix (Alinhado em 320)
    draw.text((base_x, curr_y), prefix, font=font_headline, fill=(255, 255, 255))
    try:
        bbox = draw.textbbox((0,0), prefix, font=font_headline)
        curr_y += bbox[3] - bbox[1] + 8
    except Exception:
        curr_y += 24 + 8
        
    # Name (Alinhado em 320)
    name_overlay = Image.new("RGBA", final_img.size, (0, 0, 0, 0))
    ndraw = ImageDraw.Draw(name_overlay)
    draw_text_with_tracking(ndraw, (base_x, curr_y), name_no_prefix, font_name, (255, 255, 255, 255), -3)
    final_img = Image.alpha_composite(final_img.convert("RGBA"), name_overlay).convert("RGB")
    draw = ImageDraw.Draw(final_img)
    try:
        bbox = draw.textbbox((0,0), name_no_prefix, font=font_name)
        curr_y += bbox[3] - bbox[1] + 53
    except Exception:
        curr_y += 110 + 53
        
    # --- Bloco de Textos (Especialidade + Headline) recuados em 27px ---
    y_text_start = curr_y
    text_offset_x = 27
    content_x = base_x + text_offset_x 
    
    # Specialty
    draw.text((content_x, curr_y), specialty_line, font=font_specialty, fill=(255, 255, 255))
    try:
        bbox = draw.textbbox((0,0), specialty_line, font=font_specialty)
        curr_y += bbox[3] - bbox[1] + 10 # Line-height aumentado
    except Exception:
        curr_y += 24 + 10
    
    # Headline
    balanced_lines = balance_text(headline)
    for line in balanced_lines:
        draw.text((content_x, curr_y), line, font=font_headline, fill=(234, 234, 234))
        try:
            bbox = draw.textbbox((0,0), line, font=font_headline)
            curr_y += bbox[3] - bbox[1] + 10 # Line-height aumentado
        except Exception:
            curr_y += 24 + 10
            
    y_text_end = curr_y - 10
    
    # Borda lateral Branca (#FFFFFF), 1px, cravada no X = 320
    draw.line([(base_x, y_text_start + 4), (base_x, y_text_end)], fill=(255, 255, 255), width=1)
    
    curr_y = y_text_end + 53
        
    # --- STEP 4: O Super Botão ---
    cor2 = lighten_color_hex(brand_color, 0.35)
    border_color = darken_color_hex(brand_color, 0.10)
    btn_w = int(305)
    btn_h = int(81)
    btn_radius = int(5)
    border_bottom_h = int(3)
    
    # Efeito de Glow
    glow_layer = Image.new("RGBA", final_img.size, (0, 0, 0, 0))
    gdraw = ImageDraw.Draw(glow_layer)
    glow_color = hex_to_rgb(cor2) + (76,) 
    gdraw.rounded_rectangle([base_x, curr_y, base_x + btn_w, curr_y + btn_h], radius=btn_radius, fill=glow_color)
    glow_layer = glow_layer.filter(ImageFilter.GaussianBlur(radius=36.5))
    final_img = Image.alpha_composite(final_img.convert("RGBA"), glow_layer).convert("RGB")
    draw = ImageDraw.Draw(final_img)
    
    # 1. Base Escura (Essa é a camada que vai sobrar embaixo fazendo o papel de borda)
    draw.rounded_rectangle([base_x, curr_y, base_x + btn_w, curr_y + btn_h], radius=btn_radius, fill=hex_to_rgb(border_color))
    
    # 2. Fundo do Botão (Gradiente)
    # A altura dele é a altura total menos os 3px da borda
    gradient_h = btn_h - border_bottom_h
    btn_img = Image.new("RGBA", (btn_w, gradient_h), (0, 0, 0, 0))
    btn_draw = ImageDraw.Draw(btn_img)
    
    r1, g1, b1 = hex_to_rgb(brand_color)
    r2, g2, b2 = hex_to_rgb(cor2)
    for bx in range(btn_w):
        if bx <= (btn_w/2):
            t = bx / (btn_w/2)
            r = int(r1 + (r2 - r1) * t)
            g = int(g1 + (g2 - g1) * t)
            b = int(b1 + (b2 - b1) * t)
        else:
            t = (bx - (btn_w/2)) / (btn_w/2)
            r = int(r2 + (r1 - r2) * t)
            g = int(g2 + (g1 - g2) * t)
            b = int(b2 + (b1 - b2) * t)
        btn_draw.line([(bx, 0), (bx, gradient_h)], fill=(r, g, b, 255))
        
    mask = Image.new("L", (btn_w, gradient_h), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.rounded_rectangle([0, 0, btn_w, gradient_h], radius=btn_radius, fill=255)
    btn_img.putalpha(mask)
    
    # Cola o gradiente alinhado ao topo da base escura
    final_img.paste(btn_img, (base_x, curr_y), btn_img)
    draw = ImageDraw.Draw(final_img)
    
    # Centralização do Texto + Ícone PNG
    btn_text = "AGENDAR CONSULTA"
    try:
        bbox = draw.textbbox((0,0), btn_text, font=font_btn)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        y_offset = bbox[1] 
    except Exception:
        tw = len(btn_text) * 10
        th = 18
        y_offset = 0
        
    icon_path = "static/seta.png"
    icon_w = 22 
    icon_h = 22 
    gap = 8 
    
    total_content_w = tw + gap + icon_w
    usable_h = gradient_h # A área para centralizar o texto é o gradiente
    
    start_x = base_x + (btn_w - total_content_w) // 2
    
    # Desenha o texto
    tx = start_x
    ty = curr_y + (usable_h - th) // 2 - y_offset
    draw.text((tx, ty), btn_text, font=font_btn, fill=(255, 255, 255))
    
    # Cola a imagem PNG da Seta
    try:
        if os.path.exists(icon_path):
            icon_img = Image.open(icon_path).convert("RGBA")
            ix = start_x + tw + gap
            iy = curr_y + (usable_h - icon_h) // 2
            final_img.paste(icon_img, (int(ix), int(iy)), icon_img)
    except Exception as e:
        logger.warning("Failed to load button icon PNG: %s", e)
    
    draw = ImageDraw.Draw(final_img)
    
    curr_y += btn_h + 130
    
    # City
    fill_city = (255, 255, 255, 102)
    text_overlay = Image.new("RGBA", final_img.size, (0, 0, 0, 0))
    tdraw = ImageDraw.Draw(text_overlay)
    draw_text_with_tracking(tdraw, (base_x, curr_y), city_text, font_city, fill_city, 1)
    final_img = Image.alpha_composite(final_img.convert("RGBA"), text_overlay).convert("RGB")
    
    # --- STEP 5: Export ---
    png_io = io.BytesIO()
    final_img.save(png_io, format="PNG")
    png_bytes = png_io.getvalue()
    
    pdf_io = io.BytesIO()
    pw, ph = 841.89, 438.49
    c = pdf_canvas.Canvas(pdf_io, pagesize=(pw, ph))
    img_reader = ImageReader(io.BytesIO(png_bytes))
    c.drawImage(img_reader, 0, 0, width=pw, height=ph)
    c.save()
    pdf_bytes = pdf_io.getvalue()
    
    zip_io = io.BytesIO()
    with zipfile.ZipFile(zip_io, "w") as zf:
        zf.writestr("capa.png", png_bytes)
        zf.writestr("capa.pdf", pdf_bytes)
        
    return zip_io.getvalue()