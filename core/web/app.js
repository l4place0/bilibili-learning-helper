const $ = (sel) => document.querySelector(sel);
const API = '/api';

let currentTaskId = null;
let pollTimer = null;
let lightboxFrames = [];
let lightboxIndex = 0;
let allTasks = [];

// Batch state
let batchTasks = {};   // {taskId: {url, status, title}}
let batchTotal = 0;
let batchDone = 0;
let batchFailed = 0;
let batchTimer = null;

// Known platform URL patterns
const PLATFORM_PATTERNS = [
    /bilibili\.com\/video\//,
    /b23\.tv\//,
    /youtube\.com\/watch/,
    /youtu\.be\//,
    /youtube\.com\/shorts\//,
];

function isValidVideoUrl(url) {
    return PLATFORM_PATTERNS.some(p => p.test(url));
}

function extractUrl(text) {
    const match = text.match(/https?:\/\/[^\s]+/);
    return match ? match[0] : null;
}

// --- Init ---
document.addEventListener('DOMContentLoaded', () => {
    loadHistory();
    loadStorage();
    initNavbar();
    $('#submit-form').addEventListener('submit', handleSubmit);
    $('#cleanup-btn').addEventListener('click', handleCleanup);
    $('#toggle-transcript').addEventListener('click', toggleTranscript);
    $('#show-frames').addEventListener('click', toggleFrames);
    $('#delete-task-btn').addEventListener('click', handleDeleteTask);
    $('#favorite-btn').addEventListener('click', handleToggleFavorite);
    $('#export-markdown').addEventListener('click', handleExportMarkdown);
    $('#export-review-doc').addEventListener('click', handleExportReviewDoc);
    $('#publish-btn').addEventListener('click', handlePublishClick);
    $('#publish-cancel').addEventListener('click', closePublishDialog);
    $('#publish-confirm').addEventListener('click', handlePublishConfirm);
    $('#batch-publish-btn').addEventListener('click', () => handleBatchPublish(true));
    $('#batch-unpublish-btn').addEventListener('click', () => handleBatchPublish(false));
    $('#batch-close').addEventListener('click', closeBatchDialog);
    $('#select-all-tasks').addEventListener('change', handleSelectAll);
    $('#retry-task-btn').addEventListener('click', handleRetryTask);
    $('#result-description')?.addEventListener('click', function() {
        this.classList.toggle('expanded');
    });
    document.addEventListener('keydown', handleLightboxKey);
    $('#history-search').addEventListener('input', applyHistoryFilters);
    $('#filter-platform').addEventListener('change', applyHistoryFilters);
    $('#filter-status').addEventListener('change', applyHistoryFilters);
    // Cookies management
    $('#cookies-check').addEventListener('click', loadCookiesStatus);
    $('#cookies-save').addEventListener('click', handleSaveCookies);
});

// --- Navbar ---
function initNavbar() {
    document.querySelectorAll('.nav-link').forEach(link => {
        link.addEventListener('click', (e) => {
            e.preventDefault();
            const page = link.dataset.page;
            // Update nav links
            document.querySelectorAll('.nav-link').forEach(l => l.classList.remove('active'));
            link.classList.add('active');
            // Update pages
            document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
            $(`#page-${page}`).classList.add('active');
            // Refresh data when switching to history
            if (page === 'history') {
                loadHistory();
                loadStorage();
            }
            if (page === 'settings') {
                onSettingsPageLoad();
            }
        });
    });
}

function navigateTo(page) {
    document.querySelectorAll('.nav-link').forEach(l => {
        l.classList.toggle('active', l.dataset.page === page);
    });
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    $(`#page-${page}`).classList.add('active');
}

// --- Submit ---
async function handleSubmit(e) {
    e.preventDefault();
    const raw = $('#url-input').value.trim();
    if (!raw) {
        $('#url-input').classList.add('invalid');
        return;
    }
    $('#url-input').classList.remove('invalid');

    // Split by lines, filter empty
    const lines = raw.split('\n').map(l => l.trim()).filter(Boolean);
    const valid = [];
    const invalid = [];

    for (const line of lines) {
        const url = extractUrl(line);
        if (url && isValidVideoUrl(url)) {
            valid.push(url);
        } else {
            invalid.push(line);
        }
    }

    if (valid.length === 0) {
        showToast('No valid video URLs found. Supported: Bilibili, YouTube.', 'error');
        return;
    }

    if (invalid.length > 0) {
        showToast(`Skipped ${invalid.length} invalid URL(s)`, 'error');
    }

    const btn = $('#submit-btn');
    btn.disabled = true;
    btn.textContent = 'Submitting...';

    try {
        if (valid.length === 1) {
            // Single URL: use existing endpoint
            await submitSingle(valid[0]);
        } else {
            // Multiple URLs: use batch endpoint
            await submitBatch(valid);
        }
    } catch (err) {
        showError(err.message);
    } finally {
        btn.disabled = false;
        btn.textContent = 'Submit';
    }
}

async function submitSingle(url) {
    const resp = await fetch(`${API}/summarize`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            url,
            language: $('#language-select').value,
            llm_provider: $('#provider-select').value,
            mode: $('#mode-select').value,
        }),
    });

    if (!resp.ok) {
        const err = await resp.json();
        throw new Error(err.detail || 'Request failed');
    }

    const data = await resp.json();
    currentTaskId = data.task_id;
    showResultSection();
    startPolling(currentTaskId);
}

async function submitBatch(urls) {
    const resp = await fetch(`${API}/summarize/batch`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            urls,
            language: $('#language-select').value,
            llm_provider: $('#provider-select').value,
            mode: $('#mode-select').value,
        }),
    });

    if (!resp.ok) {
        const err = await resp.json();
        throw new Error(err.detail || 'Batch request failed');
    }

    const data = await resp.json();

    if (data.skipped && data.skipped.length > 0) {
        showToast(`Server skipped ${data.skipped.length} invalid URL(s)`, 'error');
    }

    if (!data.tasks || data.tasks.length === 0) {
        throw new Error('No tasks were created');
    }

    // Initialize batch state
    batchTasks = {};
    batchTotal = data.tasks.length;
    batchDone = 0;
    batchFailed = 0;
    currentTaskId = null;

    for (const t of data.tasks) {
        batchTasks[t.task_id] = { url: t.url, status: t.status };
    }

    showBatchSection();
    startBatchPolling();
}

// --- Polling ---
function startPolling(taskId) {
    stopPolling();
    pollTimer = setInterval(() => pollTask(taskId), 2000);
    pollTask(taskId);
}

function stopPolling() {
    if (pollTimer) {
        clearInterval(pollTimer);
        pollTimer = null;
    }
}

let sseSource = null;

async function pollTask(taskId) {
    try {
        // Use lightweight status endpoint for polling
        const resp = await fetch(`${API}/tasks/${taskId}/status`);
        if (!resp.ok) throw new Error('Query failed');
        const status = await resp.json();

        // Update progress bar with lightweight data
        updateProgressOnly(status);

        // Start SSE streaming when summarizing begins
        if (status.status === 'summarizing' && !sseSource) {
            startSSEStream(taskId);
        }

        if (status.status === 'done' || status.status === 'failed') {
            stopPolling();
            stopSSEStream();
            // Fetch full task data only on completion
            const fullResp = await fetch(`${API}/tasks/${taskId}`);
            if (fullResp.ok) {
                const task = await fullResp.json();
                updateResult(task);
            }
            loadHistory();
            loadStorage();
        }
    } catch (err) {
        stopPolling();
        stopSSEStream();
        showError(err.message);
    }
}

function startSSEStream(taskId) {
    stopSSEStream();
    sseSource = new EventSource(`${API}/tasks/${taskId}/stream`);

    // Show summary section for streaming content
    $('#result-content').classList.remove('hidden');
    $('#result-summary').textContent = '';

    sseSource.onmessage = (event) => {
        const data = JSON.parse(event.data);
        if (data.chunk) {
            // Append streaming chunk
            $('#result-summary').textContent += data.chunk;
        }
        if (data.done) {
            stopSSEStream();
        }
    };

    sseSource.onerror = () => {
        stopSSEStream();
    };
}

function stopSSEStream() {
    if (sseSource) {
        sseSource.close();
        sseSource = null;
    }
}

function updateProgressOnly(status) {
    let statusLabel = STATUS_LABELS[status.status] || status.status;
    if (status.progress != null && status.status !== 'done' && status.status !== 'failed' && status.status !== 'pending') {
        statusLabel += ` ${status.progress}%`;
    }
    $('#status-text').textContent = statusLabel;
    const fill = $('#progress-fill');
    fill.style.width = (status.progress || PROGRESS_MAP[status.status]) + '%';
    fill.className = status.status === 'done' ? 'done' : status.status === 'failed' ? 'failed' : '';
}

// --- Batch polling ---
function showBatchSection() {
    $('#result-section').classList.remove('hidden');
    $('#result-content').classList.add('hidden');
    $('#result-error').classList.add('hidden');
    $('#result-tags').innerHTML = '';
    $('#result-description').classList.add('hidden');
    $('#toggle-transcript').classList.add('hidden');
    $('#result-transcript').classList.add('hidden');
    $('#show-frames').classList.add('hidden');
    $('#result-frames').classList.add('hidden');
    $('#delete-task-btn').classList.add('hidden');
    $('#export-markdown').classList.add('hidden');
    $('#export-review-doc').classList.add('hidden');
    $('#retry-task-btn').classList.add('hidden');
    $('#favorite-btn').classList.add('hidden');

    updateBatchProgress();
}

function updateBatchProgress() {
    const done = batchDone;
    const failed = batchFailed;
    const total = batchTotal;
    const processing = total - done - failed;

    let statusText = `Batch: ${done}/${total} done`;
    if (failed > 0) statusText += `, ${failed} failed`;
    if (processing > 0) statusText += `, ${processing} processing`;

    $('#status-text').textContent = statusText;

    const pct = total > 0 ? Math.round((done + failed) / total * 100) : 0;
    const fill = $('#progress-fill');
    fill.style.width = pct + '%';
    fill.className = (done + failed) >= total ? (failed > 0 ? 'failed' : 'done') : '';

    // Show summary
    const summaryEl = $('#result-summary');
    let html = '';
    for (const [taskId, info] of Object.entries(batchTasks)) {
        const label = STATUS_LABELS[info.status] || info.status;
        const statusClass = info.status === 'done' ? 'status-done' :
                           info.status === 'failed' ? 'status-failed' : 'status-pending';
        const shortId = taskId.slice(0, 8);
        const title = info.title || info.url.slice(0, 50);
        html += `<div class="batch-item">
            <span class="status-badge ${statusClass}">${label}</span>
            <span class="batch-title">${escapeHtml(title)}</span>
            <button class="ghost-btn small-btn" onclick="viewTask('${taskId}')">View</button>
        </div>`;
    }
    summaryEl.innerHTML = html;
}

function startBatchPolling() {
    stopBatchPolling();
    batchTimer = setInterval(pollAllBatchTasks, 2000);
    pollAllBatchTasks();
}

function stopBatchPolling() {
    if (batchTimer) {
        clearInterval(batchTimer);
        batchTimer = null;
    }
}

async function pollAllBatchTasks() {
    const pending = Object.keys(batchTasks).filter(id => {
        const s = batchTasks[id].status;
        return s !== 'done' && s !== 'failed';
    });

    if (pending.length === 0) {
        stopBatchPolling();
        loadHistory();
        loadStorage();
        return;
    }

    for (const taskId of pending) {
        try {
            const resp = await fetch(`${API}/tasks/${taskId}`);
            if (!resp.ok) continue;
            const task = await resp.json();

            const oldStatus = batchTasks[taskId].status;
            batchTasks[taskId].status = task.status;
            batchTasks[taskId].title = (task.metadata || {}).title || '';

            if (oldStatus !== 'done' && oldStatus !== 'failed') {
                if (task.status === 'done') batchDone++;
                else if (task.status === 'failed') batchFailed++;
            }
        } catch (_) {}
    }

    updateBatchProgress();

    if (batchDone + batchFailed >= batchTotal) {
        stopBatchPolling();
        loadHistory();
        loadStorage();
    }
}

// --- Result display ---
function showResultSection() {
    $('#result-section').classList.remove('hidden');
    $('#result-content').classList.add('hidden');
    $('#result-error').classList.add('hidden');
    $('#result-tags').innerHTML = '';
    $('#result-description').classList.add('hidden');
    $('#toggle-transcript').classList.add('hidden');
    $('#result-transcript').classList.add('hidden');
    $('#show-frames').classList.add('hidden');
    $('#result-frames').classList.add('hidden');
    $('#delete-task-btn').classList.add('hidden');
    $('#export-markdown').classList.add('hidden');
    $('#export-review-doc').classList.add('hidden');
    $('#retry-task-btn').classList.add('hidden');
    $('#favorite-btn').classList.remove('hidden');
}

const STATUS_LABELS = {
    pending: 'Pending',
    downloading: 'Downloading',
    transcribing: 'Transcribing',
    extracting_frames: 'Extracting Frames',
    classifying: 'Classifying',
    summarizing: 'Summarizing',
    done: 'Done',
    failed: 'Failed',
};

const PROGRESS_MAP = {
    pending: 5,
    downloading: 15,
    transcribing: 30,
    extracting_frames: 45,
    classifying: 55,
    summarizing: 80,
    done: 100,
    failed: 100,
};

function updateResult(task) {
    let statusLabel = STATUS_LABELS[task.status] || task.status;
    if (task.progress != null && task.status !== 'done' && task.status !== 'failed' && task.status !== 'pending') {
        statusLabel += ` ${task.progress}%`;
    }
    $('#status-text').textContent = statusLabel;
    const fill = $('#progress-fill');
    fill.style.width = (task.progress || PROGRESS_MAP[task.status]) + '%';
    fill.className = task.status === 'done' ? 'done' : task.status === 'failed' ? 'failed' : '';

    // Favorite star
    const favBtn = $('#favorite-btn');
    favBtn.classList.toggle('active', !!task.favorite);
    favBtn.innerHTML = task.favorite ? '&#9733;' : '&#9734;';
    favBtn.dataset.taskId = task.task_id;

    if (task.status === 'done') {
        $('#result-content').classList.remove('hidden');
        $('#result-error').classList.add('hidden');

        const meta = task.metadata || {};
        $('#result-title').textContent = meta.title || 'Untitled';

        // Meta line
        const metaParts = [];
        if (meta.uploader) metaParts.push(meta.uploader);
        if (meta.duration) metaParts.push(`Duration: ${formatDuration(meta.duration)}`);
        if (task.platform) metaParts.push(`Platform: ${task.platform}`);
        if (meta.view_count != null) metaParts.push(`Views: ${meta.view_count.toLocaleString()}`);
        if (meta.like_count != null) metaParts.push(`Likes: ${meta.like_count.toLocaleString()}`);
        $('#result-meta').textContent = metaParts.join(' | ');

        // Tags
        const tags = meta.tags || [];
        if (tags.length) {
            $('#result-tags').innerHTML = tags.slice(0, 15).map(t =>
                `<span class="tag">${escapeHtml(t)}</span>`
            ).join('');
        } else {
            $('#result-tags').innerHTML = '';
        }

        // Description
        const desc = (meta.description || '').trim();
        const descEl = $('#result-description');
        if (desc) {
            descEl.textContent = desc;
            descEl.classList.remove('hidden');
            descEl.classList.remove('expanded');
        } else {
            descEl.classList.add('hidden');
        }

        $('#result-summary').textContent = task.summary || '';

        // Transcript
        if (task.transcript) {
            $('#result-transcript').textContent = task.transcript;
            $('#toggle-transcript').classList.remove('hidden');
        }

        // Frames button
        $('#show-frames').classList.remove('hidden');
        $('#result-frames').classList.add('hidden');

        // Delete button
        $('#delete-task-btn').classList.remove('hidden');
        $('#delete-task-btn').dataset.taskId = task.task_id;

        // Export Markdown button
        if (task.summary) {
            $('#export-markdown').classList.remove('hidden');
        }

        // Review Doc button
        if (task.summary) {
            $('#export-review-doc').classList.remove('hidden');
        }

        // Publish button
        updatePublishButton(task);

        // Re-publish banner
        updatePublishBanner(task);

        // Metrics
        renderMetrics(meta.metrics);

    } else if (task.status === 'failed') {
        $('#result-content').classList.add('hidden');
        $('#result-error').classList.remove('hidden');
        $('#result-error').textContent = task.error || 'Unknown error';
        $('#retry-task-btn').classList.remove('hidden');
    }
}

function toggleTranscript() {
    const el = $('#result-transcript');
    const btn = $('#toggle-transcript');
    if (el.classList.contains('hidden')) {
        el.classList.remove('hidden');
        btn.textContent = 'Hide Transcript';
    } else {
        el.classList.add('hidden');
        btn.textContent = 'Show Transcript';
    }
}

// --- Favorite ---
async function handleToggleFavorite() {
    const btn = $('#favorite-btn');
    const taskId = btn.dataset.taskId || currentTaskId;
    if (!taskId) return;

    const isActive = btn.classList.contains('active');
    const newState = !isActive;

    try {
        const resp = await fetch(`${API}/tasks/${taskId}/favorite`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ favorite: newState }),
        });
        if (!resp.ok) throw new Error('Failed to update favorite');

        btn.classList.toggle('active', newState);
        btn.innerHTML = newState ? '&#9733;' : '&#9734;';
        loadHistory();
    } catch (err) {
        console.error(err);
    }
}

async function toggleFavoriteFromList(taskId, el) {
    const isActive = el.classList.contains('active');
    const newState = !isActive;

    try {
        const resp = await fetch(`${API}/tasks/${taskId}/favorite`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ favorite: newState }),
        });
        if (!resp.ok) throw new Error('Failed to update favorite');

        el.classList.toggle('active', newState);
        el.innerHTML = newState ? '&#9733;' : '&#9734;';
    } catch (err) {
        console.error(err);
    }
}

// --- Frames ---
async function toggleFrames() {
    const el = $('#result-frames');
    const btn = $('#show-frames');

    if (!el.classList.contains('hidden')) {
        el.classList.add('hidden');
        btn.textContent = 'View Frames';
        return;
    }

    if (!currentTaskId) return;
    btn.textContent = 'Loading frames...';

    try {
        const resp = await fetch(`${API}/tasks/${currentTaskId}/frames`);
        if (!resp.ok) throw new Error('Failed to load frames');
        const data = await resp.json();

        if (!data.count) {
            el.innerHTML = '<p style="color:var(--text-muted)">No frames available for this task.</p>';
        } else {
            lightboxFrames = data.frames.map(f =>
                `${API}/tasks/${currentTaskId}/frames/${f.filename}`
            );
            el.innerHTML = `<div class="frames-grid">${
                data.frames.map((f, i) =>
                    `<img class="frame-thumb" src="${API}/tasks/${currentTaskId}/frames/${f.filename}"
                          alt="frame ${i}" data-index="${i}" onclick="openLightbox(${i})">`
                ).join('')
            }</div>`;
        }

        el.classList.remove('hidden');
        btn.textContent = 'Hide Frames';
    } catch (err) {
        el.innerHTML = `<p style="color:var(--red)">${escapeHtml(err.message)}</p>`;
        el.classList.remove('hidden');
        btn.textContent = 'View Frames';
    }
}

// --- Lightbox ---
function openLightbox(index) {
    lightboxIndex = index;
    updateLightbox();
    $('#lightbox').classList.remove('hidden');
}

function closeLightbox() {
    $('#lightbox').classList.add('hidden');
}

function navLightbox(dir, e) {
    e.stopPropagation();
    lightboxIndex = (lightboxIndex + dir + lightboxFrames.length) % lightboxFrames.length;
    updateLightbox();
}

function updateLightbox() {
    $('#lightbox-img').src = lightboxFrames[lightboxIndex];
    $('#lightbox-counter').textContent = `${lightboxIndex + 1} / ${lightboxFrames.length}`;
}

function handleLightboxKey(e) {
    if ($('#lightbox').classList.contains('hidden')) return;
    if (e.key === 'Escape') closeLightbox();
    if (e.key === 'ArrowLeft') { lightboxIndex = (lightboxIndex - 1 + lightboxFrames.length) % lightboxFrames.length; updateLightbox(); }
    if (e.key === 'ArrowRight') { lightboxIndex = (lightboxIndex + 1) % lightboxFrames.length; updateLightbox(); }
}

// --- Delete task ---
async function handleDeleteTask() {
    const taskId = $('#delete-task-btn').dataset.taskId || currentTaskId;
    if (!taskId) return;
    if (!confirm('Delete this task and all associated files?')) return;

    try {
        const resp = await fetch(`${API}/tasks/${taskId}`, { method: 'DELETE' });
        if (!resp.ok) throw new Error('Delete failed');
        const data = await resp.json();

        showResultSection();
        $('#result-content').classList.add('hidden');
        $('#status-text').textContent = 'Deleted';
        const fill = $('#progress-fill');
        fill.className = 'failed';
        fill.style.width = '100%';

        currentTaskId = null;
        loadHistory();
        loadStorage();
    } catch (err) {
        alert(err.message);
    }
}

async function handleRetryTask() {
    const taskId = currentTaskId;
    if (!taskId) return;

    try {
        const resp = await fetch(`${API}/tasks/${taskId}/retry`, { method: 'POST' });
        if (!resp.ok) {
            const err = await resp.json();
            throw new Error(err.detail || 'Retry failed');
        }
        showResultSection();
        startPolling(taskId);
        loadHistory();
    } catch (err) {
        alert(err.message);
    }
}

function showError(msg) {
    showResultSection();
    $('#result-content').classList.add('hidden');
    $('#result-error').classList.remove('hidden');
    $('#result-error').textContent = msg;
    $('#status-text').textContent = 'Error';
    const fill = $('#progress-fill');
    fill.className = 'failed';
    fill.style.width = '100%';
}

// --- History ---
async function loadHistory() {
    try {
        const resp = await fetch(`${API}/tasks`);
        if (!resp.ok) return;
        const data = await resp.json();
        allTasks = data.tasks;
        applyHistoryFilters();
    } catch (_) {}
}

function applyHistoryFilters() {
    const search = ($('#history-search').value || '').toLowerCase();
    const platform = $('#filter-platform').value;
    const status = $('#filter-status').value;

    let filtered = allTasks;

    if (search) {
        filtered = filtered.filter(t => {
            const title = (t.metadata && t.metadata.title) || '';
            return title.toLowerCase().includes(search);
        });
    }

    if (platform) {
        filtered = filtered.filter(t => t.platform === platform);
    }

    if (status) {
        if (status === 'processing') {
            const processingStatuses = ['pending', 'downloading', 'transcribing', 'extracting_frames', 'classifying', 'summarizing'];
            filtered = filtered.filter(t => processingStatuses.includes(t.status));
        } else {
            filtered = filtered.filter(t => t.status === status);
        }
    }

    renderHistory(filtered);
}

function renderHistory(tasks) {
    const body = $('#history-body');
    const empty = $('#history-empty');

    if (!tasks.length) {
        body.innerHTML = '';
        empty.classList.remove('hidden');
        return;
    }

    empty.classList.add('hidden');
    tasks.sort((a, b) => new Date(b.created_at) - new Date(a.created_at));

    body.innerHTML = tasks.map(t => {
        const meta = t.metadata || {};
        const title = meta.title || truncateUrl(t.url);
        const time = formatTime(t.created_at);
        const statusLabel = STATUS_LABELS[t.status] || t.status;

        const tags = meta.tags || [];
        let tagsHtml = '';
        if (tags.length) {
            const shown = tags.slice(0, 3);
            const rest = tags.length - shown.length;
            tagsHtml = '<div class="history-tags">' +
                shown.map(tg => `<span class="history-tag">${escapeHtml(tg)}</span>`).join('') +
                (rest > 0 ? `<span class="history-tag more">+${rest}</span>` : '') +
                '</div>';
        }

        const favClass = t.favorite ? 'active' : '';
        const favChar = t.favorite ? '&#9733;' : '&#9734;';

        const publishUrl = (meta || {}).publish_url;
        let publishedHtml;
        if (publishUrl) {
            const pubDate = ((meta || {}).published_at || '').slice(0, 10);
            publishedHtml = `<span class="published-status">✓ ${pubDate}</span><br><a class="published-link" href="${publishUrl}" target="_blank">查看→</a>`;
        } else {
            publishedHtml = '<span class="published unpublished">-</span>';
        }

        return `<tr>
            <td><input type="checkbox" class="history-checkbox" data-task-id="${t.task_id}" onchange="updateBatchActions()"></td>
            <td><button class="star-btn-sm ${favClass}" onclick="toggleFavoriteFromList('${t.task_id}', this)">${favChar}</button></td>
            <td>${time}</td>
            <td>${escapeHtml(title)}</td>
            <td>${tagsHtml}</td>
            <td><span class="status-badge status-${t.status}">${statusLabel}</span></td>
            <td>${publishedHtml}</td>
            <td>
                <button class="ghost-btn small-btn" onclick="viewTask('${t.task_id}')">View</button>
                <button class="danger-ghost-btn small-btn" onclick="deleteTaskFromList('${t.task_id}')">Delete</button>
            </td>
        </tr>`;
    }).join('');
}

async function viewTask(taskId) {
    try {
        const resp = await fetch(`${API}/tasks/${taskId}`);
        if (!resp.ok) return;
        const task = await resp.json();
        currentTaskId = taskId;
        navigateTo('submit');
        showResultSection();
        updateResult(task);
        stopPolling();
        if (task.status !== 'done' && task.status !== 'failed') {
            startPolling(taskId);
        }
        $('#result-section').scrollIntoView({ behavior: 'smooth' });
    } catch (_) {}
}

async function deleteTaskFromList(taskId) {
    if (!confirm('Delete this task and all associated files?')) return;
    try {
        const resp = await fetch(`${API}/tasks/${taskId}`, { method: 'DELETE' });
        if (!resp.ok) throw new Error('Delete failed');
        loadHistory();
        loadStorage();
        if (currentTaskId === taskId) {
            showResultSection();
            $('#result-content').classList.add('hidden');
            $('#status-text').textContent = 'Deleted';
            currentTaskId = null;
        }
    } catch (err) {
        alert(err.message);
    }
}

// --- Storage ---
async function loadStorage() {
    try {
        const resp = await fetch(`${API}/storage`);
        if (!resp.ok) return;
        const data = await resp.json();
        const total = data.db_size_bytes + data.cache_size_bytes;
        $('#storage-info').textContent = `${data.task_count} tasks | ${formatBytes(total)}`;
    } catch (_) {}
}

async function handleCleanup() {
    if (!confirm('Clear all stored data? This cannot be undone.')) return;

    try {
        const resp = await fetch(`${API}/storage`, { method: 'DELETE' });
        if (!resp.ok) throw new Error('Cleanup failed');
        const data = await resp.json();
        loadStorage();
        loadHistory();
        alert(`Cleanup complete: deleted ${data.deleted_tasks} tasks, freed ${formatBytes(data.freed_bytes)}`);
    } catch (err) {
        alert(err.message);
    }
}

// --- Helpers ---
function formatBytes(bytes) {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const units = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return (bytes / Math.pow(k, i)).toFixed(1) + ' ' + units[i];
}

function formatDuration(seconds) {
    const m = Math.floor(seconds / 60);
    const s = Math.round(seconds % 60);
    return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

function formatTime(iso) {
    const d = new Date(iso);
    const pad = (n) => String(n).padStart(2, '0');
    return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function truncateUrl(url) {
    try {
        const u = new URL(url);
        return u.hostname + u.pathname.slice(0, 20);
    } catch {
        return url.slice(0, 30);
    }
}

function escapeHtml(str) {
    const el = document.createElement('span');
    el.textContent = str;
    return el.innerHTML;
}

// --- Export Markdown ---
function formatDurationHMS(seconds) {
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = Math.round(seconds % 60);
    const pad = (n) => String(n).padStart(2, '0');
    return h > 0 ? `${pad(h)}:${pad(m)}:${pad(s)}` : `${pad(m)}:${pad(s)}`;
}

function yamlEscape(str) {
    if (!str) return '""';
    return '"' + str.replace(/\\/g, '\\\\').replace(/"/g, '\\"') + '"';
}

function generateObsidianMarkdown(task) {
    const meta = task.metadata || {};
    const title = meta.title || 'Untitled';
    const author = meta.uploader || '';
    const url = task.url || '';
    const platform = task.platform || '';
    const tags = meta.tags || [];
    const date = new Date().toISOString().slice(0, 10);
    const duration = meta.duration ? formatDurationHMS(meta.duration) : '';
    const uploadDate = meta.upload_date || '';
    const contentType = meta.content_type || '';
    const language = meta.language || '';
    const description = (meta.description || '').trim();
    const summary = task.summary || '';

    const tagsYaml = tags.length > 0 ? `[${tags.join(', ')}]` : '[]';

    let frontmatter = '---\n';
    frontmatter += `title: ${yamlEscape(title)}\n`;
    frontmatter += `author: ${yamlEscape(author)}\n`;
    frontmatter += `url: ${yamlEscape(url)}\n`;
    frontmatter += `platform: ${platform}\n`;
    frontmatter += `tags: ${tagsYaml}\n`;
    frontmatter += `date: ${date}\n`;
    frontmatter += `duration: ${yamlEscape(duration)}\n`;
    frontmatter += `upload_date: ${yamlEscape(uploadDate)}\n`;
    frontmatter += `content_type: ${contentType}\n`;
    frontmatter += `language: ${language}\n`;

    if (description) {
        frontmatter += `description: |\n`;
        description.split('\n').forEach(line => {
            frontmatter += `  ${line}\n`;
        });
    } else {
        frontmatter += `description: ""\n`;
    }

    frontmatter += '---\n\n';
    frontmatter += `# ${title}\n\n`;
    frontmatter += `## 总结\n\n`;
    frontmatter += summary;

    return frontmatter;
}

async function copyToClipboard(text) {
    try {
        await navigator.clipboard.writeText(text);
        return true;
    } catch {
        try {
            const textarea = document.createElement('textarea');
            textarea.value = text;
            textarea.style.position = 'fixed';
            textarea.style.opacity = '0';
            document.body.appendChild(textarea);
            textarea.select();
            const ok = document.execCommand('copy');
            document.body.removeChild(textarea);
            return ok;
        } catch {
            return false;
        }
    }
}

function showToast(message, type) {
    const existing = document.querySelector('.toast');
    if (existing) existing.remove();

    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 2200);
}

async function handleExportMarkdown() {
    if (!currentTaskId) return;
    try {
        const resp = await fetch(`${API}/tasks/${currentTaskId}`);
        if (!resp.ok) throw new Error('Failed to fetch task');
        const task = await resp.json();
        const markdown = generateObsidianMarkdown(task);
        const ok = await copyToClipboard(markdown);
        if (ok) {
            showToast('Markdown copied to clipboard', 'success');
        } else {
            showToast('Failed to copy to clipboard', 'error');
        }
    } catch (err) {
        showToast('Export failed: ' + err.message, 'error');
    }
}

async function handleExportReviewDoc() {
    if (!currentTaskId) return;
    try {
        showToast('Generating review document...', 'info');
        const resp = await fetch(`${API}/tasks/${currentTaskId}/review-doc`);
        if (!resp.ok) {
            const err = await resp.json().catch(() => ({ detail: 'Unknown error' }));
            throw new Error(err.detail || 'Failed to generate');
        }
        const blob = await resp.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `review_${currentTaskId.slice(0, 8)}.html`;
        a.click();
        URL.revokeObjectURL(url);
        showToast('Review document downloaded', 'success');
    } catch (err) {
        showToast('Export failed: ' + err.message, 'error');
    }
}

// --- Publish ---
let publishDialogTaskId = null;

function updatePublishButton(task) {
    const btn = $('#publish-btn');
    const meta = task.metadata || {};
    if (task.status !== 'done') {
        btn.classList.add('hidden');
        return;
    }
    btn.classList.remove('hidden');
    if (meta.publish_url) {
        btn.textContent = '已发布 ✓';
        btn.classList.add('published');
        btn.onclick = () => {
            // Show options: view or unpublish
            publishDialogTaskId = task.task_id;
            showPublishedOptions(task);
        };
    } else {
        btn.textContent = 'Publish';
        btn.classList.remove('published');
        btn.onclick = handlePublishClick;
    }
}

function showPublishedOptions(task) {
    const meta = task.metadata || {};
    const dialog = $('#publish-dialog');
    const body = $('#publish-dialog-body');
    const confirmBtn = $('#publish-confirm');
    const cancelBtn = $('#publish-cancel');

    body.innerHTML = `
        <div class="dialog-info">此任务已发布到 GitHub Pages</div>
        <div class="dialog-url"><a href="${meta.publish_url}" target="_blank" style="color:var(--accent)">${meta.publish_url}</a></div>
    `;
    confirmBtn.textContent = '取消发布';
    confirmBtn.className = 'danger-ghost-btn small-btn';
    confirmBtn.onclick = handleUnpublishConfirm;
    cancelBtn.textContent = '关闭';
    dialog.classList.remove('hidden');
}

function updatePublishBanner(task) {
    const banner = $('#publish-banner');
    const meta = task.metadata || {};
    if (!meta.publish_url || !meta.published_at || !task.completed_at) {
        banner.classList.add('hidden');
        return;
    }
    // Check if content changed after publish
    if (task.completed_at > meta.published_at) {
        const publishDate = meta.published_at.slice(0, 10);
        banner.innerHTML = `
            <span class="banner-text">内容已变更，上次发布: ${publishDate}</span>
            <div>
                <button class="ghost-btn small-btn" onclick="handleRepublish()">重新发布</button>
                <button class="ghost-btn small-btn" onclick="$('#publish-banner').classList.add('hidden')">忽略</button>
            </div>
        `;
        banner.classList.remove('hidden');
    } else {
        banner.classList.add('hidden');
    }
}

async function handleRepublish() {
    if (!currentTaskId) return;
    await doPublish([currentTaskId]);
    $('#publish-banner').classList.add('hidden');
}

async function handlePublishClick() {
    if (!currentTaskId) return;

    // Check if GitHub is configured
    try {
        const resp = await fetch(`${API}/publish/status`);
        const status = await resp.json();
        if (!status.repo_configured) {
            showSetupInstructions();
            return;
        }
    } catch (_) {}

    // Fetch task for dialog info
    try {
        const resp = await fetch(`${API}/tasks/${currentTaskId}`);
        if (!resp.ok) return;
        const task = await resp.json();
        publishDialogTaskId = task.task_id;

        const meta = task.metadata || {};
        const title = meta.title || 'Untitled';
        const platform = task.platform || 'unknown';
        const tags = (meta.tags || []).concat(meta.content_type ? [meta.content_type] : []);

        // Predict URL
        let pagesUrl = '';
        try {
            const statusResp = await fetch(`${API}/publish/status`);
            const status = await statusResp.json();
            if (status.pages_url) {
                pagesUrl = `${status.pages_url.replace(/\/$/, '')}/reviews/${task.task_id}.html`;
            }
        } catch (_) {}

        const dialog = $('#publish-dialog');
        const body = $('#publish-dialog-body');
        const confirmBtn = $('#publish-confirm');
        const cancelBtn = $('#publish-cancel');

        body.innerHTML = `
            <div class="dialog-info">
                <div><span class="label">标题:</span> ${escapeHtml(title)}</div>
                <div><span class="label">平台:</span> ${platform}</div>
                ${tags.length ? `<div><span class="label">标签:</span> ${tags.map(t => escapeHtml(t)).join(', ')}</div>` : ''}
            </div>
            ${pagesUrl ? `<div class="dialog-url">发布后链接: ${pagesUrl}</div>` : ''}
        `;
        confirmBtn.textContent = '确认发布';
        confirmBtn.className = 'small-btn';
        confirmBtn.onclick = handlePublishConfirm;
        cancelBtn.textContent = '取消';
        dialog.classList.remove('hidden');
    } catch (err) {
        showToast('Failed to load task: ' + err.message, 'error');
    }
}

function showSetupInstructions() {
    const dialog = $('#publish-dialog');
    const body = $('#publish-dialog-body');
    const confirmBtn = $('#publish-confirm');
    const cancelBtn = $('#publish-cancel');

    body.innerHTML = `
        <div class="setup-instructions">
            <p>请先在 <code>.env</code> 中配置以下变量:</p>
            <p><code>GITHUB_REPO</code> = user/video-reviews</p>
            <p><code>GITHUB_TOKEN</code> = ghp_xxxx (PAT with repo scope)</p>
            <p><code>GITHUB_PAGES_URL</code> = https://user.github.io/video-reviews</p>
        </div>
    `;
    confirmBtn.textContent = '我知道了';
    confirmBtn.className = 'small-btn';
    confirmBtn.onclick = closePublishDialog;
    cancelBtn.classList.add('hidden');
    dialog.classList.remove('hidden');
}

function closePublishDialog() {
    $('#publish-dialog').classList.add('hidden');
    $('#publish-cancel').classList.remove('hidden');
    publishDialogTaskId = null;
}

async function handlePublishConfirm() {
    if (!publishDialogTaskId) return;
    closePublishDialog();
    await doPublish([publishDialogTaskId]);
}

async function handleUnpublishConfirm() {
    if (!publishDialogTaskId) return;
    const taskId = publishDialogTaskId;
    closePublishDialog();

    try {
        showToast('正在取消发布...', 'info');
        const resp = await fetch(`${API}/publish/${taskId}`, { method: 'DELETE' });
        if (!resp.ok) {
            const err = await resp.json().catch(() => ({ detail: 'Unknown error' }));
            throw new Error(err.detail || 'Unpublish failed');
        }
        showToast('已取消发布', 'success');
        // Refresh task view
        if (currentTaskId === taskId) {
            const taskResp = await fetch(`${API}/tasks/${taskId}`);
            if (taskResp.ok) updateResult(await taskResp.json());
        }
        loadHistory();
    } catch (err) {
        showToast('取消发布失败: ' + err.message, 'error');
    }
}

async function doPublish(taskIds) {
    try {
        showToast(`正在发布 ${taskIds.length} 个任务...`, 'info');
        const resp = await fetch(`${API}/publish`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ task_ids: taskIds }),
        });
        if (!resp.ok) {
            const err = await resp.json().catch(() => ({ detail: 'Unknown error' }));
            throw new Error(err.detail || 'Publish failed');
        }
        const result = await resp.json();

        if (result.published && result.published.length) {
            const url = result.published[0].url;
            showToast(`发布成功！共 ${result.published.length} 个`, 'success');

            // Show success dialog with URL
            showPublishSuccess(result.published);
        }
        if (result.failed && result.failed.length) {
            showToast(`${result.failed.length} 个任务发布失败`, 'error');
        }

        // Refresh task view
        if (taskIds.includes(currentTaskId)) {
            const taskResp = await fetch(`${API}/tasks/${currentTaskId}`);
            if (taskResp.ok) updateResult(await taskResp.json());
        }
        loadHistory();
    } catch (err) {
        showToast('发布失败: ' + err.message, 'error');
    }
}

function showPublishSuccess(published) {
    const dialog = $('#publish-dialog');
    const body = $('#publish-dialog-body');
    const confirmBtn = $('#publish-confirm');
    const cancelBtn = $('#publish-cancel');

    const urls = published.map(p => `<div class="dialog-url"><a href="${p.url}" target="_blank" style="color:var(--accent)">${p.url}</a></div>`).join('');

    body.innerHTML = `
        <div class="publish-success">
            <p>✓ 已发布 ${published.length} 个任务到 GitHub Pages</p>
            ${urls}
            <div class="actions">
                <button class="ghost-btn small-btn" onclick="copyUrl('${published[0].url}')">复制链接</button>
                <button class="ghost-btn small-btn" onclick="window.open('${published[0].url}', '_blank')">打开</button>
            </div>
        </div>
    `;
    confirmBtn.textContent = '关闭';
    confirmBtn.className = 'small-btn';
    confirmBtn.onclick = closePublishDialog;
    cancelBtn.classList.add('hidden');
    dialog.classList.remove('hidden');
}

function copyUrl(url) {
    navigator.clipboard.writeText(url).then(() => showToast('链接已复制', 'success'));
}

// --- Batch Publish ---
function handleSelectAll(e) {
    const checked = e.target.checked;
    document.querySelectorAll('.history-checkbox').forEach(cb => {
        cb.checked = checked;
    });
    updateBatchActions();
}

function updateBatchActions() {
    const checked = document.querySelectorAll('.history-checkbox:checked');
    const batchActions = $('#batch-actions');
    const batchCount = $('#batch-count');
    if (checked.length > 0) {
        batchActions.classList.remove('hidden');
        batchCount.textContent = `已选 ${checked.length} 个`;
    } else {
        batchActions.classList.add('hidden');
    }
}

async function handleBatchPublish(isPublish) {
    const checked = document.querySelectorAll('.history-checkbox:checked');
    const taskIds = Array.from(checked).map(cb => cb.dataset.taskId);
    if (!taskIds.length) return;

    if (isPublish) {
        await doPublish(taskIds);
    } else {
        // Batch unpublish
        const dialog = $('#batch-dialog');
        const body = $('#batch-progress-body');
        const closeBtn = $('#batch-close');
        body.innerHTML = '<div class="batch-progress-bar"><div class="batch-progress-fill" style="width:0%"></div></div>';
        closeBtn.classList.add('hidden');
        dialog.classList.remove('hidden');

        let done = 0;
        let failed = 0;
        for (const taskId of taskIds) {
            try {
                const resp = await fetch(`${API}/publish/${taskId}`, { method: 'DELETE' });
                if (resp.ok) done++; else failed++;
            } catch (_) {
                failed++;
            }
            const pct = Math.round(((done + failed) / taskIds.length) * 100);
            body.querySelector('.batch-progress-fill').style.width = `${pct}%`;
            body.innerHTML += `<div class="batch-item">${taskId.slice(0, 8)}: ${resp?.ok ? '✓ 已取消' : '✗ 失败'}</div>`;
        }

        body.innerHTML += `<div style="margin-top:12px">完成: ${done} 成功, ${failed} 失败</div>`;
        closeBtn.classList.remove('hidden');
        showToast(`批量取消发布完成: ${done} 成功, ${failed} 失败`, done > 0 ? 'success' : 'error');
        loadHistory();
    }
}

function closeBatchDialog() {
    $('#batch-dialog').classList.add('hidden');
}

// --- Prompt Management ---
document.addEventListener('DOMContentLoaded', () => {
    // Tabs
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            document.querySelectorAll('.tab-panel').forEach(p => p.classList.add('hidden'));
            btn.classList.add('active');
            $(`#tab-${btn.dataset.tab}`).classList.remove('hidden');
        });
    });

    // Classify
    $('#classify-load').addEventListener('click', loadClassifyPrompt);
    $('#classify-save').addEventListener('click', saveClassifyPrompt);
    $('#classify-reset').addEventListener('click', resetClassifyPrompt);

    // Summary
    $('#summary-load').addEventListener('click', loadSummaryPrompt);
    $('#summary-save').addEventListener('click', saveSummaryPrompt);
    $('#summary-reset').addEventListener('click', resetSummaryPrompt);
});

async function loadClassifyPrompt() {
    const lang = $('#classify-lang').value;
    const multimodal = $('#classify-multimodal').checked;
    try {
        const resp = await fetch(`${API}/prompts/classify?lang=${lang}&multimodal=${multimodal}`);
        if (!resp.ok) throw new Error('Failed to load');
        const data = await resp.json();
        $('#classify-prompt').value = data.prompt || '';
        showPromptStatus('classify', 'Loaded', 'success');
    } catch (err) {
        showPromptStatus('classify', err.message, 'error');
    }
}

async function saveClassifyPrompt() {
    const lang = $('#classify-lang').value;
    const multimodal = $('#classify-multimodal').checked;
    const prompt = $('#classify-prompt').value.trim();
    if (!prompt) {
        showPromptStatus('classify', 'Prompt cannot be empty', 'error');
        return;
    }
    try {
        const resp = await fetch(`${API}/prompts/classify`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ lang, prompt, multimodal }),
        });
        if (!resp.ok) throw new Error('Failed to save');
        showPromptStatus('classify', 'Saved', 'success');
    } catch (err) {
        showPromptStatus('classify', err.message, 'error');
    }
}

async function resetClassifyPrompt() {
    const lang = $('#classify-lang').value;
    const multimodal = $('#classify-multimodal').checked;
    try {
        const resp = await fetch(`${API}/prompts/classify?lang=${lang}&multimodal=${multimodal}`, { method: 'DELETE' });
        if (!resp.ok) throw new Error('Failed to reset');
        $('#classify-prompt').value = '';
        showPromptStatus('classify', 'Reset to default', 'success');
    } catch (err) {
        showPromptStatus('classify', err.message, 'error');
    }
}

async function loadSummaryPrompt() {
    const type = $('#summary-type').value;
    const lang = $('#summary-lang').value;
    try {
        const resp = await fetch(`${API}/prompts/summary/${type}?lang=${lang}`);
        if (!resp.ok) throw new Error('Failed to load');
        const data = await resp.json();
        $('#summary-prompt').value = data.prompt || '';
        showPromptStatus('summary', 'Loaded', 'success');
    } catch (err) {
        showPromptStatus('summary', err.message, 'error');
    }
}

async function saveSummaryPrompt() {
    const type = $('#summary-type').value;
    const lang = $('#summary-lang').value;
    const prompt = $('#summary-prompt').value.trim();
    if (!prompt) {
        showPromptStatus('summary', 'Prompt cannot be empty', 'error');
        return;
    }
    try {
        const resp = await fetch(`${API}/prompts/summary/${type}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ lang, prompt }),
        });
        if (!resp.ok) throw new Error('Failed to save');
        showPromptStatus('summary', 'Saved', 'success');
    } catch (err) {
        showPromptStatus('summary', err.message, 'error');
    }
}

async function resetSummaryPrompt() {
    const type = $('#summary-type').value;
    const lang = $('#summary-lang').value;
    try {
        const resp = await fetch(`${API}/prompts/summary/${type}?lang=${lang}`, { method: 'DELETE' });
        if (!resp.ok) throw new Error('Failed to reset');
        $('#summary-prompt').value = '';
        showPromptStatus('summary', 'Reset to default', 'success');
    } catch (err) {
        showPromptStatus('summary', err.message, 'error');
    }
}

function showPromptStatus(section, msg, type) {
    const el = $(`#${section}-status`);
    el.textContent = msg;
    el.className = `prompt-status ${type}`;
    setTimeout(() => { el.textContent = ''; el.className = 'prompt-status'; }, 3000);
}

// --- Cookies Management ---
async function loadCookiesStatus() {
    try {
        const resp = await fetch(`${API}/settings/cookies`);
        if (!resp.ok) throw new Error('Failed to check');
        const data = await resp.json();
        const el = $('#cookies-status');
        const labels = { valid: 'Valid', expired: 'EXPIRED', not_configured: 'Not Configured' };
        el.textContent = labels[data.status] || data.status;
        el.className = `status-badge status-${data.status === 'valid' ? 'done' : data.status === 'expired' ? 'failed' : 'pending'}`;
    } catch (err) {
        $('#cookies-status').textContent = 'Error';
        $('#cookies-status').className = 'status-badge status-failed';
    }
}

async function handleSaveCookies() {
    const cookies = $('#cookies-input').value.trim();
    if (!cookies) {
        showToast('Please paste cookies content', 'error');
        return;
    }
    try {
        const resp = await fetch(`${API}/settings/cookies`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ cookies }),
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.detail || 'Failed to save');
        showToast(`Cookies updated: ${data.status}`, data.status === 'valid' ? 'success' : 'error');
        loadCookiesStatus();
        $('#cookies-input').value = '';
    } catch (err) {
        showToast('Save failed: ' + err.message, 'error');
    }
}

// Auto-load cookies status when switching to settings page
function onSettingsPageLoad() {
    loadCookiesStatus();
}

// --- Metrics Display ---
function renderMetrics(metrics) {
    const el = $('#result-metrics');
    if (!metrics || Object.keys(metrics).length === 0) {
        el.classList.add('hidden');
        return;
    }

    const stages = ['download', 'transcribe', 'extract_frames', 'classify', 'summarize'];
    const labels = {
        download: 'Download',
        transcribe: 'Transcribe',
        extract_frames: 'Extract Frames',
        classify: 'Classify',
        summarize: 'Summarize',
    };
    const totalMs = metrics.total_duration_ms || 0;
    const maxMs = Math.max(...stages.map(s => (metrics[s] || {}).duration_ms || 0), 1);

    let html = '<div class="metrics-container">';
    html += '<div class="metrics-header"><strong>Pipeline Metrics</strong>';
    if (totalMs > 0) {
        html += ` <span class="metrics-total">Total: ${formatMs(totalMs)}</span>`;
    }
    html += '</div>';

    for (const stage of stages) {
        const data = metrics[stage];
        if (!data || !data.duration_ms) continue;
        const pct = Math.round((data.duration_ms / maxMs) * 100);
        const extras = [];
        if (data.file_size_bytes) extras.push(formatBytes(data.file_size_bytes));
        if (data.text_length) extras.push(`${(data.text_length / 1000).toFixed(1)}k chars`);
        if (data.frame_count) extras.push(`${data.frame_count} frames`);
        if (data.api_calls) extras.push(`${data.api_calls} API call(s)`);
        if (data.cached) extras.push('cached');

        html += `<div class="metrics-row">
            <span class="metrics-label">${labels[stage] || stage}</span>
            <div class="metrics-bar"><div class="metrics-fill" style="width:${pct}%"></div></div>
            <span class="metrics-value">${formatMs(data.duration_ms)}</span>
            ${extras.length ? `<span class="metrics-extras">${extras.join(', ')}</span>` : ''}
        </div>`;
    }

    html += '</div>';
    el.innerHTML = html;
    el.classList.remove('hidden');
}

function formatMs(ms) {
    if (ms < 1000) return `${ms}ms`;
    if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
    const m = Math.floor(ms / 60000);
    const s = Math.round((ms % 60000) / 1000);
    return `${m}m ${s}s`;
}
