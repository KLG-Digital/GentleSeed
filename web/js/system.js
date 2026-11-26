// ======================== SYSTÈME : ONGLETS ========================

// Charge le contenu de l'onglet Système demandé
async function loadSystemTab(name) {
  if (name === 'health') await refreshOverview();
  if (name === 'backups') await loadBackups();
  if (name === 'updates') await loadUpdates();
  if (name === 'tasks') await loadTasks();
  if (name === 'files') await loadLogFiles();
}

// Tâches planifiées : lancer maintenant, ou voir leurs journaux
async function loadTasks() {
  const data = await api('/api/system');
  const tbody = $('#taskRows');
  tbody.replaceChildren();
  for (const task of data.tasks) {
    const row = element('tr');
    row.append(element('td', '', task.name));
    row.append(element('td', '', task.interval === null ? 'Manual' : `${task.interval} s`));
    row.append(element('td', '', task.last_run ? dateTime(task.last_run) : '—'));
    row.append(element('td', '', task.next_run ? dateTime(task.next_run) : '—'));
    row.append(element('td', '', task.status));
    const actions = element('td', 'task-actions');
    const run = element('button', 'button button-subtle', task.id === 'manual' ? 'Open' : 'Run');
    run.type = 'button';
    run.disabled = task.can_run === false;
    run.addEventListener('click', async () => {
      if (task.id === 'manual') {
        await goToPage('search');
        return;
      }
      run.disabled = true;
      try {
        const result = await api('/api/tasks/' + encodeURIComponent(task.id) + '/run', {method: 'POST', body: '{}'});
        notice(result.message);
        setTimeout(() => loadSystemTab('tasks').catch(() => {}), 1100);
      } catch (error) {
        notice(error.message, true);
        run.disabled = false;
      }
    });
    const logs = element('button', 'button button-subtle', 'View logs');
    logs.type = 'button';
    logs.addEventListener('click', async () => {
      if (!await goToPage('logs')) return;
      $('#logsearch').value = task.log_filter || '';
      renderEventsTable();
    });
    actions.append(run, logs);
    row.append(actions);
    tbody.append(row);
  }
}

// Fichiers journaux : détails (aperçu) et téléchargement
async function loadLogFiles() {
  const data = await api('/api/logfiles');
  const tbody = $('#fileRows');
  tbody.replaceChildren();
  for (const file of data) {
    const row = element('tr');
    row.append(dataElement('td', '', file.name));
    row.append(element('td', '', formatFileSize(file.size)));
    row.append(element('td', '', dateTime(file.modified)));
    const cell = element('td', 'file-actions');
    const details = element('button', 'button button-subtle', 'Details');
    details.type = 'button';
    details.addEventListener('click', () => openLogFile(file.name));
    const link = element('a', 'download-link', 'Download');
    link.href = 'api/logfiles/' + encodeURIComponent(file.name) + '?lang=' + encodeURIComponent(selectedLocale());
    link.download = file.name;
    cell.append(details, link);
    row.append(cell);
    tbody.append(row);
  }
  if (!data.length) {
    const row = element('tr');
    const cell = element('td', 'empty', 'No files');
    cell.colSpan = 4;
    row.append(cell);
    tbody.append(row);
  }
}
// =================================================


// ======================== LECTEUR DE FICHIERS JOURNAUX ========================
let logViewRaw = null;
let logViewKinds = null;
let logViewName = '';

// Remet les dates du fichier au fuseau et au format choisis (fichiers .jsonl ou .log)
function localizeLogContent(source, filename) {
  const lines = String(source).split(/\r?\n/);
  if (filename.endsWith('.jsonl')) {
    return lines.map(line => {
      if (!line.trim()) return line;
      try {
        const event = JSON.parse(line);
        if (!event || typeof event !== 'object' || !event.time) return line;
        return '[' + dateTime(event.time) + '] [' + (event.level || 'INFO') + '] ' + (event.message || '');
      } catch (_) {
        return line;
      }
    }).join('\n');
  }
  return lines.map(line => line.replace(/^\[(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2}))\]/,
    (_, instant) => '[' + dateTime(instant) + ']')).join('\n');
}

function updateLogFilePreview() {
  if (logViewRaw === null) return;
  renderColoredLog($('#fileDetailsContent'), localizeLogContent(logViewRaw, logViewName), logViewKinds);
  $('#fileDetailsMeta').textContent = 'Time zone: ' + regionalZone() + ' · Format: ' + (regional.UI_HOUR_FORMAT === 'auto' ? 'browser' : regional.UI_HOUR_FORMAT + ' h');
}

// Ouvre l'aperçu d'un fichier ; le serveur le traduit dans la langue choisie
async function openLogFile(name) {
  logViewName = name;
  logViewRaw = null;
  logViewKinds = null;
  $('#fileDetailsTitle').textContent = name;
  $('#fileDetailsContent').textContent = tr('Loading the log file…');  // <pre> : non suivi par la traduction
  $('#fileDetailsStatus').textContent = '';
  $('#fileDownload').href = 'api/logfiles/' + encodeURIComponent(name) + '?lang=' + encodeURIComponent(selectedLocale());
  $('#fileDownload').download = name;
  openDialog('fileDetailsDialog');
  try {
    const data = await api('/api/logfiles/' + encodeURIComponent(name) + '/content?lang=' + encodeURIComponent(selectedLocale()));
    if (logViewName !== name) return;
    logViewRaw = data.content;
    logViewKinds = data.kinds || null;
    updateLogFilePreview();
    $('#fileDetailsStatus').textContent = data.truncated ? 'End of the log shown (large file)' : 'File content · ' + formatFileSize(data.size);
  } catch (error) {
    $('#fileDetailsContent').textContent = tr('Cannot read the file: ' + error.message);
  }
}

$('#fileExportLocalized').addEventListener('click', () => {
  if (logViewRaw === null) {
    notice('No log content loaded.', true);
    return;
  }
  const output = $('#fileDetailsContent').textContent;
  const object = URL.createObjectURL(new Blob([output], {type: 'text/plain;charset=utf-8'}));
  const link = document.createElement('a');
  link.href = object;
  link.download = logViewName.replace(/\.(?:jsonl|log)$/i, '') + '-view.txt';
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(object), 10000);
});

$('#fileCopy').addEventListener('click', async () => {
  const button = $('#fileCopy');
  try {
    const text = $('#fileDetailsContent').textContent;
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
    } else {
      // Page en http:// (hors localhost) : l'API moderne est bloquée, on utilise l'ancienne méthode
      const area = document.createElement('textarea');
      area.value = text;
      area.setAttribute('readonly', '');
      area.style.cssText = 'position:fixed;top:0;left:0;opacity:0';
      (button.closest('dialog') || document.body).append(area);
      area.focus();
      area.select();
      let copied = false;
      try {
        copied = document.execCommand('copy');
      } finally {
        area.parentNode.removeChild(area);
      }
      if (!copied) throw new Error('copy refused');
    }
    // Retour visuel sur le bouton lui-même : vert + « Copied », puis retour à l'état normal
    button.original = button.original || [...button.childNodes];  // garde le texte d'origine
    withIcon(button, 'check', 'Copied');
    button.classList.add('copied');
    clearTimeout(button.copiedTimer);
    button.copiedTimer = setTimeout(() => {
      button.replaceChildren(...button.original);
      button.classList.remove('copied');
    }, 2000);
  } catch (_) {
    notice('Copy unavailable in this browser.', true);
  }
});
// =================================================


// ======================== ACTUALISATION AUTOMATIQUE ========================

// Fichiers journaux : toutes les 10 s tant que l'onglet est affiché
setInterval(() => {
  if (!document.hidden && !$('#page-system').hidden && !document.querySelector('[data-system-content="files"]').hidden) {
    loadSystemTab('files').catch(() => {});
  }
}, 10000);

// Onglet État : toutes les 30 s tant qu'il est affiché
setInterval(() => {
  if (!document.hidden && !$('#page-system').hidden && !document.querySelector('[data-system-content="health"]').hidden) {
    refreshOverview().catch(() => {});
  }
}, 30000);
// =================================================
