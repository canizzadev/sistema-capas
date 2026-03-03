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
    document.getElementById('tab-individual').classList.remove('active');
    document.getElementById('tab-batch').classList.remove('active');
    document.getElementById('tab-cover').classList.remove('active');

    document.getElementById('panel-individual').classList.add('hidden');
    document.getElementById('panel-batch').classList.add('hidden');
    document.getElementById('panel-cover').classList.add('hidden');

    document.getElementById(`tab-${tab}`).classList.add('active');
    document.getElementById(`panel-${tab}`).classList.remove('hidden');
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

    if (!urlInput || !selectedPhotoFile) {
        alert('Por favor, informe o link do Instagram e insira uma foto da médica.');
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
