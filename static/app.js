let resultsData = [];
let currentIndex = 0;
let selectedPhotoFile = null;

// --- sessionStorage persistence for results ---
function saveResultsToSession() {
    try {
        sessionStorage.setItem('ag_resultsData', JSON.stringify(resultsData));
        sessionStorage.setItem('ag_currentIndex', String(currentIndex));
    } catch (e) { /* quota exceeded or unavailable — silent fail */ }
}

function restoreResultsFromSession() {
    try {
        const saved = sessionStorage.getItem('ag_resultsData');
        const savedIndex = sessionStorage.getItem('ag_currentIndex');
        if (saved) {
            resultsData = JSON.parse(saved);
            currentIndex = savedIndex ? parseInt(savedIndex, 10) : 0;
            if (currentIndex >= resultsData.length) currentIndex = 0;
            if (resultsData.length > 0) {
                renderCurrent();
            }
        }
    } catch (e) { /* corrupt data — silent fail */ }
}

function updatePhotoPreview(file) {
    if (!file) return;
    selectedPhotoFile = file;
    const preview = document.getElementById('cover-photo-preview');
    const text = document.getElementById('cover-photo-text');
    const removeBtn = document.getElementById('cover-photo-remove');
    if (preview && text && removeBtn) {
        preview.src = window.URL.createObjectURL(file);
        preview.classList.remove('hidden');
        text.classList.add('hidden');
        removeBtn.classList.remove('hidden');
    }
}

function removePhoto(event) {
    if (event) {
        event.stopPropagation();
    }
    selectedPhotoFile = null;
    const preview = document.getElementById('cover-photo-preview');
    const text = document.getElementById('cover-photo-text');
    const removeBtn = document.getElementById('cover-photo-remove');
    const hiddenInput = document.getElementById('cover-photo-hidden');
    if (preview && text && removeBtn) {
        preview.src = '';
        preview.classList.add('hidden');
        text.classList.remove('hidden');
        removeBtn.classList.add('hidden');
    }
    if (hiddenInput) {
        hiddenInput.value = '';
    }
}

function handlePhotoSelect(event) {
    const file = event.target.files[0];
    if (file && file.type.startsWith('image/')) {
        updatePhotoPreview(file);
    }
}

document.addEventListener('DOMContentLoaded', () => {
    // Restore any previous session results
    restoreResultsFromSession();

    // Load awaiting number list on startup (pipeline tab is default)
    loadAwaitingNumber();

    // Paste listener anywhere on the document
    document.addEventListener('paste', (event) => {
        const coverPanel = document.getElementById('panel-cover');
        if (coverPanel && !coverPanel.classList.contains('hidden')) {
            const items = event.clipboardData.items;
            for (let i = 0; i < items.length; i++) {
                if (items[i].type.startsWith('image/')) {
                    const file = items[i].getAsFile();
                    updatePhotoPreview(file);
                    break;
                }
            }
        }
    });

    // Drag-and-drop listener
    const dropzone = document.getElementById('cover-photo-dropzone');
    if (dropzone) {
        dropzone.addEventListener('dragover', (e) => {
            e.preventDefault();
            dropzone.classList.add('dragover');
        });
        dropzone.addEventListener('dragleave', (e) => {
            e.preventDefault();
            dropzone.classList.remove('dragover');
        });
        dropzone.addEventListener('drop', (e) => {
            e.preventDefault();
            dropzone.classList.remove('dragover');
            if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
                const file = e.dataTransfer.files[0];
                if (file.type.startsWith('image/')) {
                    updatePhotoPreview(file);
                }
            }
        });
    }
});

function clearFields() {
    const boxes = ['box-name', 'box-specialty', 'box-headline'];
    boxes.forEach(id => {
        const el = document.getElementById(id);
        el.innerText = '';
        el.className = 'output-box empty';
    });
    document.getElementById('link-container').style.display = 'none';
    document.getElementById('external-anchor').href = '#';
}

function setField(id, text, isError = false) {
    const el = document.getElementById(id);
    if (isError) {
        el.innerHTML = `<span class="error-text">${text}</span>`;
        el.className = 'output-box empty'; // not copyable
        el.style.color = 'inherit'; // override transparent
    } else if (text) {
        el.innerText = text;
        el.className = 'output-box filled';
    } else {
        el.innerText = '';
        el.className = 'output-box empty';
    }
}

function renderCurrent() {
    if (resultsData.length === 0) {
        clearFields();
        document.getElementById('pagination').style.display = 'none';
        return;
    }

    const data = resultsData[currentIndex];

    if (data.error) {
        clearFields();
        setField('box-name', `Erro em ${data.url}: ${data.error}`, true);
    } else {
        setField('box-name', data.formatted_name);
        setField('box-specialty', data.specialty_line);
        setField('box-headline', data.headline);

        if (data.external_link) {
            document.getElementById('link-container').style.display = 'block';
            document.getElementById('external-anchor').href = data.external_link;
        } else {
            document.getElementById('link-container').style.display = 'none';
        }
    }

    // Pagination UI
    if (resultsData.length > 1) {
        document.getElementById('pagination').style.display = 'flex';
        document.getElementById('page-counter').innerText = `${currentIndex + 1} / ${resultsData.length}`;
        document.getElementById('prev-btn').disabled = (currentIndex === 0);
        document.getElementById('next-btn').disabled = (currentIndex === resultsData.length - 1);
    } else {
        document.getElementById('pagination').style.display = 'none';
    }
}

function nav(dir) {
    currentIndex += dir;
    if (currentIndex < 0) currentIndex = 0;
    if (currentIndex >= resultsData.length) currentIndex = resultsData.length - 1;
    saveResultsToSession();
    renderCurrent();
}

async function extractProfiles() {
    const input = document.getElementById('urls-input').value;
    const btn = document.getElementById('extract-btn');
    const spinner = document.getElementById('spinner');

    const urls = input.split('\n').map(u => u.trim()).filter(u => u);
    if (urls.length === 0) return;

    btn.disabled = true;
    spinner.style.display = 'block';

    resultsData = [];
    currentIndex = 0;
    clearFields();
    document.getElementById('pagination').style.display = 'none';

    try {
        const response = await fetch('/extract', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ urls })
        });

        if (!response.ok) throw new Error('Erro na API');

        resultsData = await response.json();
        saveResultsToSession();
        renderCurrent();
    } catch (error) {
        setField('box-name', 'Ocorreu um erro ao conectar-se à API.', true);
    } finally {
        btn.disabled = false;
        spinner.style.display = 'none';
    }
}

async function copyText(elementId) {
    const box = document.getElementById(elementId);
    if (box.classList.contains('empty')) return;

    const text = box.innerText;
    try {
        await navigator.clipboard.writeText(text);

        // Animation flash
        box.classList.add('copied');
        setTimeout(() => {
            box.classList.remove('copied');
        }, 500);
    } catch (err) {
        alert('Falha ao copiar para a área de transferência.');
    }
}

function switchTab(tab) {
    const tabs = ['pipeline', 'individual', 'batch', 'cover', 'discovery', 'dashboard'];
    tabs.forEach(t => {
        const tabEl = document.getElementById(`tab-${t}`);
        const panelEl = document.getElementById(`panel-${t}`);
        if (tabEl) tabEl.classList.remove('active');
        if (panelEl) panelEl.classList.add('hidden');
    });

    document.getElementById(`tab-${tab}`).classList.add('active');
    document.getElementById(`panel-${tab}`).classList.remove('hidden');

    if (tab === 'pipeline') loadAwaitingNumber();
    if (tab === 'dashboard') loadLeads();
    if (tab === 'discovery') loadDiscovered();
}

async function extractBatch() {
    const input = document.getElementById('batch-urls-input').value;
    const btn = document.getElementById('batch-extract-btn');
    const spinner = document.getElementById('batch-spinner');
    const progressText = document.getElementById('batch-progress');

    const urls = input.split('\n').map(u => u.trim()).filter(u => u);
    if (urls.length === 0) return;

    btn.disabled = true;
    spinner.style.display = 'block';
    progressText.innerText = `0 / ${urls.length}`;

    const taskId = Math.random().toString(36).substring(7);

    // Polling interval
    const pollInterval = setInterval(async () => {
        try {
            const res = await fetch(`/progress?task_id=${taskId}`);
            const data = await res.json();
            if (data.total > 0) {
                progressText.innerText = `${data.current} / ${data.total}`;
            }
        } catch (e) { }
    }, 1000);

    try {
        const response = await fetch(`/extract-batch?task_id=${taskId}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ urls })
        });

        clearInterval(pollInterval);
        progressText.innerText = `${urls.length} / ${urls.length} Concluído!`;

        if (!response.ok) throw new Error('Erro na API');

        const blob = await response.blob();
        const downloadUrl = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.style.display = 'none';
        a.href = downloadUrl;
        a.download = 'resultados.xlsx';
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(downloadUrl);
        a.remove();

    } catch (error) {
        clearInterval(pollInterval);
        progressText.innerText = 'Erro no processamento.';
    } finally {
        btn.disabled = false;
        spinner.style.display = 'none';
        setTimeout(() => { progressText.innerText = ''; }, 5000);
    }
}

function syncColor(source) {
    const swatch = document.getElementById('cover-color-swatch');
    const text = document.getElementById('cover-color-input');

    if (source === 'swatch') {
        text.value = swatch.value.toUpperCase();
    } else if (source === 'text') {
        let hex = text.value.trim();
        if (!hex.startsWith('#')) hex = '#' + hex;
        // Basic hex validation before applying to swatch
        if (/^#[0-9A-Fa-f]{6}$/i.test(hex)) {
            swatch.value = hex;
        }
    }
}


async function generateCover() {
    const urlInput = document.getElementById('cover-url-input').value.trim();
    const colorInput = document.getElementById('cover-color-input').value;
    const whatsappInput = document.getElementById('cover-whatsapp-input').value.trim();
    const nameOverride = document.getElementById('cover-name-override').value.trim();
    const prospectStatus = document.getElementById('prospect-status');

    if (!urlInput || !selectedPhotoFile) {
        alert('Por favor, informe o link do Instagram e insira uma foto da médica.');
        return;
    }

    if (!whatsappInput) {
        alert('Por favor, informe o número de WhatsApp do médico(a).');
        return;
    }

    const btn = document.getElementById('cover-generate-btn');
    const spinner = document.getElementById('cover-spinner');
    const statusMsg = document.getElementById('cover-status');

    btn.disabled = true;
    btn.innerText = 'Gerando...';
    spinner.style.display = 'block';
    statusMsg.className = 'status-message';
    statusMsg.innerText = 'Buscando dados do Instagram e expandindo foto com IA... isso pode levar até 30 segundos.';
    if (prospectStatus) prospectStatus.innerText = '';

    const formData = new FormData();
    formData.append('instagram_url', urlInput);
    formData.append('photo', selectedPhotoFile);
    formData.append('brand_color', colorInput);

    try {
        const response = await fetch('/generate-cover', {
            method: 'POST',
            body: formData
        });

        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.detail || 'Erro ao gerar capa na API');
        }

        statusMsg.className = 'status-message success';
        statusMsg.innerText = 'Capa gerada com sucesso! Baixando...';

        const blob = await response.blob();
        const downloadUrl = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.style.display = 'none';
        a.href = downloadUrl;
        a.download = 'capa.zip';
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(downloadUrl);
        a.remove();

        // --- Chain into POST /prospect to register lead ---
        if (prospectStatus) {
            prospectStatus.className = 'status-message';
            prospectStatus.innerText = 'Registrando lead para prospecção...';
        }

        try {
            const prospectResp = await fetch('/prospect', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    instagram_url: urlInput,
                    whatsapp_number: whatsappInput,
                    formatted_name: nameOverride,
                    username: urlInput.split('/').filter(Boolean).pop() || '',
                })
            });

            if (prospectResp.ok) {
                const data = await prospectResp.json();
                if (prospectStatus) {
                    prospectStatus.className = 'status-message success';
                    prospectStatus.innerText = `Lead registrado com sucesso! (ID: ${data.lead_id})`;
                }
            } else {
                const errData = await prospectResp.json();
                if (prospectStatus) {
                    prospectStatus.className = 'status-message error';
                    prospectStatus.innerText = errData.detail || 'Erro ao registrar lead.';
                }
            }
        } catch (prospectErr) {
            if (prospectStatus) {
                prospectStatus.className = 'status-message error';
                prospectStatus.innerText = 'Erro ao conectar com /prospect: ' + prospectErr.message;
            }
        }

        setTimeout(() => {
            statusMsg.innerText = '';
        }, 3000);

    } catch (error) {
        statusMsg.className = 'status-message error';
        statusMsg.innerText = error.message;
    } finally {
        btn.disabled = false;
        btn.innerText = 'Gerar Capa';
        spinner.style.display = 'none';
    }
}

// ---------------------------------------------------------------------------
// Discovery functions
// ---------------------------------------------------------------------------

async function startDiscovery() {
    const countInput = document.getElementById('discovery-count');
    const btn = document.getElementById('discovery-start-btn');
    const spinner = document.getElementById('discovery-spinner');
    const logEl = document.getElementById('discovery-log');
    const statsBar = document.getElementById('discovery-stats-bar');

    const count = parseInt(countInput.value, 10);
    if (!count || count < 1) {
        alert('Informe uma quantidade válida de perfis.');
        return;
    }

    btn.disabled = true;
    btn.innerText = 'Descobrindo...';
    spinner.style.display = 'block';
    logEl.style.display = 'block';
    logEl.innerHTML = '<div class="log-entry">Iniciando descoberta de ' + count + ' perfis...</div>';
    statsBar.style.display = 'flex';
    updateStatsBar({ approved: 0, rejected: 0, skipped: 0, errors: 0 });

    try {
        const response = await fetch('/discover', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ target_count: count })
        });

        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || 'Erro na API');
        }

        const result = await response.json();

        updateStatsBar(result);

        logEl.innerHTML = '';
        if (result.details && result.details.length > 0) {
            result.details.forEach(d => {
                const cls = d.status === 'approved' ? 'log-approved' :
                            d.status === 'rejected' ? 'log-rejected' :
                            d.status === 'error' ? 'log-error' : 'log-skipped';
                logEl.innerHTML += '<div class="log-entry ' + cls + '">@' + escapeHtml(d.username) + ' — ' + escapeHtml(d.reason) + '</div>';
            });
        } else {
            logEl.innerHTML = '<div class="log-entry">Nenhum perfil processado.</div>';
        }

        loadDiscovered();

    } catch (error) {
        logEl.innerHTML += '<div class="log-entry log-error">Erro: ' + escapeHtml(error.message) + '</div>';
    } finally {
        btn.disabled = false;
        btn.innerText = 'Iniciar Descoberta';
        spinner.style.display = 'none';
    }
}

function updateStatsBar(stats) {
    document.getElementById('stat-approved').textContent = (stats.approved || 0) + ' aprovados';
    document.getElementById('stat-rejected').textContent = (stats.rejected || 0) + ' rejeitados';
    document.getElementById('stat-skipped').textContent = (stats.skipped || 0) + ' já processados';
    document.getElementById('stat-errors').textContent = (stats.errors || 0) + ' erros';
}

async function loadDiscovered() {
    const tbody = document.getElementById('discovered-tbody');
    const emptyMsg = document.getElementById('discovered-empty');
    if (!tbody) return;

    try {
        const response = await fetch('/discovered');
        const data = await response.json();
        const doctors = data.doctors || [];

        tbody.innerHTML = '';

        if (doctors.length === 0) {
            emptyMsg.style.display = 'block';
            return;
        }

        emptyMsg.style.display = 'none';

        doctors.forEach(doc => {
            const bio = doc.bio || '';
            const bioShort = bio.length > 80 ? bio.substring(0, 80) + '...' : bio;
            const followers = doc.followers != null ? Number(doc.followers).toLocaleString('pt-BR') : '—';
            const specialty = doc.especialidade_detectada || '—';

            const tr = document.createElement('tr');
            tr.innerHTML =
                '<td><a href="https://instagram.com/' + escapeHtml(doc.username) + '" target="_blank">@' + escapeHtml(doc.username) + '</a></td>' +
                '<td>' + escapeHtml(doc.name || '') + '</td>' +
                '<td>' + escapeHtml(specialty) + '</td>' +
                '<td>' + followers + '</td>' +
                '<td title="' + escapeAttr(bio) + '">' + escapeHtml(bioShort) + '</td>' +
                '<td><button class="btn-promote" onclick="promoteDoctor(' + doc.id + ', this)">Promover</button></td>';
            tbody.appendChild(tr);
        });
    } catch (e) {
        tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:#e53e3e;">Erro ao carregar médicos descobertos.</td></tr>';
    }
}

async function promoteDoctor(doctorId, btn) {
    if (!confirm('Promover este médico para o fluxo de prospecção?')) return;

    btn.disabled = true;
    btn.textContent = '...';

    try {
        const response = await fetch('/discovered/' + doctorId + '/promote', { method: 'POST' });

        if (!response.ok) {
            const err = await response.json();
            alert(err.detail || 'Erro ao promover');
            btn.disabled = false;
            btn.textContent = 'Promover';
            return;
        }

        const result = await response.json();
        btn.textContent = 'Promovido!';
        btn.classList.add('promoted');

        // Remove row after a brief delay
        setTimeout(() => {
            const row = btn.closest('tr');
            if (row) row.remove();
            // Check if table is now empty
            const tbody = document.getElementById('discovered-tbody');
            if (tbody && tbody.children.length === 0) {
                document.getElementById('discovered-empty').style.display = 'block';
            }
        }, 800);

    } catch (e) {
        alert('Erro de conexão: ' + e.message);
        btn.disabled = false;
        btn.textContent = 'Promover';
    }
}

function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

function escapeAttr(str) {
    return str.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/'/g, '&#39;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

// ---------------------------------------------------------------------------
// Pipeline functions
// ---------------------------------------------------------------------------

let pipelineTaskId = null;
let pipelinePollingInterval = null;

const PHASE_LABELS = {
    starting: 'Iniciando...',
    discovery: 'Descoberta',
    titles: 'Títulos GPT',
    color: 'Cor da marca',
    cover: 'Gerando capa',
    phone: 'Extraindo telefone',
    registration: 'Registrando lead',
    complete: 'Concluído',
};

async function startPipeline() {
    const countInput = document.getElementById('pipeline-count');
    const btn = document.getElementById('pipeline-start-btn');
    const spinner = document.getElementById('pipeline-spinner');
    const progressArea = document.getElementById('pipeline-progress-area');
    const resultsArea = document.getElementById('pipeline-results-area');

    const count = parseInt(countInput.value, 10);
    if (!count || count < 1) {
        alert('Informe uma quantidade válida.');
        return;
    }

    btn.disabled = true;
    btn.innerText = 'Executando...';
    spinner.style.display = 'block';
    progressArea.style.display = 'block';
    resultsArea.style.display = 'none';

    try {
        const response = await fetch('/pipeline/start', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ target_count: count })
        });

        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || 'Erro ao iniciar pipeline');
        }

        const data = await response.json();
        pipelineTaskId = data.task_id;

        // Start polling progress
        pipelinePollingInterval = setInterval(pollPipelineProgress, 2000);

    } catch (error) {
        alert('Erro: ' + error.message);
        btn.disabled = false;
        btn.innerText = 'Iniciar Pipeline';
        spinner.style.display = 'none';
    }
}

async function pollPipelineProgress() {
    if (!pipelineTaskId) return;

    try {
        const response = await fetch('/pipeline/progress/' + pipelineTaskId);
        if (!response.ok) return;

        const data = await response.json();

        // Update phase label
        const phaseEl = document.getElementById('pipeline-phase');
        const phaseLabel = PHASE_LABELS[data.phase] || data.phase;
        phaseEl.textContent = phaseLabel + (data.username ? ' — @' + data.username : '');

        // Update counter
        const counterEl = document.getElementById('pipeline-counter');
        counterEl.textContent = data.current + ' / ' + data.total;

        // Update progress bar
        const pct = data.total > 0 ? Math.round((data.current / data.total) * 100) : 0;
        document.getElementById('pipeline-bar').style.width = pct + '%';

        // Update message
        document.getElementById('pipeline-message').textContent = data.message || '';

        // Update stats
        const stats = data.stats || {};
        document.getElementById('pl-stat-leads').textContent = (stats.leads_created || 0) + ' leads';
        document.getElementById('pl-stat-awaiting').textContent = (stats.awaiting_number || 0) + ' aguardando nº';
        document.getElementById('pl-stat-covers').textContent = (stats.covers_generated || 0) + ' capas';
        document.getElementById('pl-stat-rejected').textContent = (stats.rejected || 0) + ' rejeitados';
        document.getElementById('pl-stat-errors').textContent = (stats.errors || 0) + ' erros';

        // Check if done
        if (data.status === 'completed' || data.status === 'error') {
            clearInterval(pipelinePollingInterval);
            pipelinePollingInterval = null;

            document.getElementById('pipeline-start-btn').disabled = false;
            document.getElementById('pipeline-start-btn').innerText = 'Iniciar Pipeline';
            document.getElementById('pipeline-spinner').style.display = 'none';
            document.getElementById('pipeline-bar').style.width = '100%';

            if (data.status === 'completed') {
                loadPipelineResults();
                loadAwaitingNumber();
            }
        }
    } catch (e) {
        // Silently retry on next poll
    }
}

async function loadPipelineResults() {
    if (!pipelineTaskId) return;

    try {
        const response = await fetch('/pipeline/results/' + pipelineTaskId);
        if (!response.ok) return;

        const data = await response.json();
        if (data.status !== 'completed' || !data.results) return;

        const details = data.results.details || [];
        const tbody = document.getElementById('pipeline-results-tbody');
        const resultsArea = document.getElementById('pipeline-results-area');

        tbody.innerHTML = '';

        if (details.length === 0) {
            resultsArea.style.display = 'none';
            return;
        }

        resultsArea.style.display = 'block';

        details.forEach(d => {
            const statusCls = d.status === 'lead_created' ? 'log-approved' :
                              d.status === 'awaiting_number' ? 'log-skipped' :
                              d.status === 'error' ? 'log-error' :
                              d.status === 'rejected' ? 'log-rejected' : '';
            const tr = document.createElement('tr');
            tr.innerHTML =
                '<td><a href="https://instagram.com/' + escapeHtml(d.username) + '" target="_blank">@' + escapeHtml(d.username) + '</a></td>' +
                '<td class="' + statusCls + '">' + escapeHtml(d.status) + '</td>' +
                '<td>' + escapeHtml(d.message || '') + '</td>';
            tbody.appendChild(tr);
        });
    } catch (e) {
        // silent
    }
}

// ---------------------------------------------------------------------------
// Awaiting Number functions
// ---------------------------------------------------------------------------

async function loadAwaitingNumber() {
    const tbody = document.getElementById('awaiting-tbody');
    const emptyMsg = document.getElementById('awaiting-empty');
    if (!tbody) return;

    try {
        const response = await fetch('/leads/awaiting-number');
        const data = await response.json();
        const leads = data.leads || [];

        tbody.innerHTML = '';

        if (leads.length === 0) {
            emptyMsg.style.display = 'block';
            return;
        }

        emptyMsg.style.display = 'none';

        leads.forEach(lead => {
            const tr = document.createElement('tr');
            tr.id = 'awaiting-row-' + lead.id;
            tr.innerHTML =
                '<td>' + lead.id + '</td>' +
                '<td><a href="https://instagram.com/' + escapeHtml(lead.username || '') + '" target="_blank">@' + escapeHtml(lead.username || '') + '</a></td>' +
                '<td>' + escapeHtml(lead.formatted_name || lead.username || '') + '</td>' +
                '<td><input type="text" class="form-input" id="num-input-' + lead.id + '" placeholder="5511999999999" style="width: 160px; padding: 6px 10px; font-size: 0.85rem;"></td>' +
                '<td><button class="btn-promote" onclick="submitNumber(' + lead.id + ', this)">Salvar</button></td>';
            tbody.appendChild(tr);
        });
    } catch (e) {
        tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;color:#e53e3e;">Erro ao carregar.</td></tr>';
    }
}

async function submitNumber(leadId, btn) {
    const input = document.getElementById('num-input-' + leadId);
    const number = input.value.trim();

    if (!number || number.length < 10) {
        alert('Informe um número válido (mínimo 10 dígitos).');
        return;
    }

    btn.disabled = true;
    btn.textContent = '...';

    try {
        const response = await fetch('/leads/' + leadId + '/set-number', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ whatsapp_number: number })
        });

        if (!response.ok) {
            const err = await response.json();
            alert(err.detail || 'Erro ao salvar número');
            btn.disabled = false;
            btn.textContent = 'Salvar';
            return;
        }

        btn.textContent = 'Salvo!';
        btn.classList.add('promoted');

        setTimeout(() => {
            const row = document.getElementById('awaiting-row-' + leadId);
            if (row) row.remove();
            const tbody = document.getElementById('awaiting-tbody');
            if (tbody && tbody.children.length === 0) {
                document.getElementById('awaiting-empty').style.display = 'block';
            }
        }, 800);

    } catch (e) {
        alert('Erro de conexão: ' + e.message);
        btn.disabled = false;
        btn.textContent = 'Salvar';
    }
}
