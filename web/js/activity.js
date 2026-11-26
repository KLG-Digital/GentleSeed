// ======================== EN COURS : OUTILS ========================
let activityTimer = null;
let activityOffset = 0;  // écart entre l'horloge du serveur et celle du navigateur
const serviceNames = {radarr: 'Radarr', sonarr: 'Sonarr'};

function activityCell(text, className) {
  const cell = document.createElement('td');
  cell.textContent = text;
  if (className) cell.className = className;
  return cell;
}

// Titre d'un média : intact, sauf les libellés composés par GentleSeed (saison entière, demande sans titre)
function mediaTitle(title) {
  const composed = title === 'New request' || / · season \d+ \(\d+ episodes\)$/.test(title);
  return composed ? element('span', '', title) : dataElement('span', '', title);
}

function titleCell(title) {
  const cell = activityCell('');
  cell.append(mediaTitle(title));
  return cell;
}

// Cellule contenant une release ou un indexeur : jamais traduit
function dataCell(text) {
  const cell = activityCell(text);
  cell.setAttribute('translate', 'no');
  return cell;
}

// Remplit un tableau ; une ligne unique « vide » s'il n'y a rien à montrer
function activityRows(body, rows, columns, empty) {
  body.replaceChildren();
  if (!rows.length) {
    const row = document.createElement('tr');
    const cell = activityCell(empty);
    cell.colSpan = columns;
    row.append(cell);
    body.append(row);
    return;
  }
  rows.forEach(cells => {
    const row = document.createElement('tr');
    cells.forEach(cell => row.append(cell));
    body.append(row);
  });
}

function formatElapsed(seconds) {
  seconds = Math.max(0, Math.round(seconds));
  const rest = formatUnit(seconds % 60, 'second');
  return seconds >= 60 ? `${formatUnit(Math.floor(seconds / 60), 'minute')} ${rest}` : rest;
}

function formatClock(epoch) {
  return formatRegional(new Date(epoch * 1000).toISOString(), false);  // mêmes réglages d'heure que partout
}

function activityItem(iconName, title, detail) {
  const box = document.createElement('div');
  box.className = 'activity-item';
  const strong = document.createElement('strong');
  strong.append(icon(iconName), ' ', mediaTitle(title));
  const small = document.createElement('span');
  small.className = 'muted';
  small.textContent = detail;
  box.append(strong, small);
  return box;
}
// =================================================


// ======================== EN COURS : AFFICHAGE ========================

// Recherche en cours, demandes reçues, file d'attente et résultats récents
function renderActivity(data) {
  activityOffset = Date.now() / 1000 - data.now;
  const running = $('#activityRunning');
  running.replaceChildren();
  if (data.running.length) {
    data.running.forEach(entry => {
      const elapsed = formatElapsed(data.now - entry.started);
      running.append(activityItem('play', `${entry.title}`,
        `${serviceNames[entry.service] || entry.service} · ${tr(entry.kind)}${entry.fresh ? ' · ' + tr('new') : ''} · ${tr(entry.phase)} · ${elapsed}`));
    });
  } else {
    const idle = document.createElement('p');
    idle.className = 'muted';
    idle.textContent = !data.auto_enabled ? 'Automatic monitoring is paused: no automatic search.'
      : data.cycle_running ? 'Pass in progress: reading the Radarr and Sonarr catalogs…'
      : 'Nothing running. The engine wakes up immediately if a new request arrives.';
    running.append(idle);
  }
  const parts = [];
  if (data.waiting_retry) {
    parts.push(tr(`${data.waiting_retry} media waiting for a new attempt`)
      + (data.next_retry ? ' (' + tr(`next at ${formatClock(data.next_retry)}`) + ')' : ''));
  }
  if (data.last_scan) parts.push(tr(`last pass: ${formatRegional(data.last_scan)}`));
  $('#activitySummary').textContent = parts.join(' · ');

  const inbox = $('#activityInbox');
  inbox.replaceChildren();
  if (data.inbox.length) {
    data.inbox.forEach(entry => inbox.append(activityItem('circle-dot', entry.title,
      tr(`${serviceNames[entry.service] || entry.service} · received at ${formatClock(entry.at)} · will be analyzed first`))));
  } else {
    const none = document.createElement('p');
    none.className = 'muted';
    none.textContent = 'None.';
    inbox.append(none);
  }

  $('#activityQueueCount').textContent = data.queue_total ? `(${data.queue_total})` : '';
  activityRows($('#activityQueue'), data.queue.map(entry => [
    activityCell(entry.fresh ? 'New' : 'Backlog', entry.fresh ? 'activity-new' : ''),
    activityCell(serviceNames[entry.service] || entry.service),
    activityCell(entry.kind),
    titleCell(entry.title)
  ]), 4, 'Nothing waiting.');
  if (data.queue_total > data.queue.length) {
    $('#activityQueueCount').textContent += ' · ' + tr(`${data.queue.length} shown`);
  }

  activityRows($('#activityRecent'), data.recent.map(entry => {
    const ok = entry.result === 'grabbed' || entry.result === 'simulated';
    const bad = entry.result === 'timeout' || entry.result === 'error';
    const result = activityCell('');
    withIcon(result, ok ? 'check' : bad ? 'alert' : 'circle', entry.label);
    if (entry.detail && bad) result.append(' — ', entry.detail);
    return [activityCell(formatClock(entry.at)), activityCell(serviceNames[entry.service] || entry.service),
            titleCell(entry.title), result, activityCell(formatElapsed(entry.seconds))];
  }), 5, 'Nothing finished since startup.');
}

// Téléchargements suivis (file puis historique de Radarr/Sonarr), du plus récent au plus ancien
const downloadStates = {
  api_accepted: ['circle-dot', 'Sent, awaiting confirmation'], queued: ['play', 'In the queue'], grabbed: ['check', 'Sent to the download client'],
  imported: ['check', 'Imported'], removed: ['alert', 'Removed from the queue'], failed: ['alert', 'Failed'], unconfirmed: ['alert', 'Not confirmed'], uncertain: ['alert', 'Not confirmed']
};

// Une cellule d'un téléchargement suivi, selon la colonne
function downloadCell(entry, key) {
  const time = entry.updated || entry.created;
  if (key === 'time') return activityCell(time ? formatRegional(time) : '');
  if (key === 'service') return activityCell(serviceNames[entry.service] || entry.service);
  if (key === 'release') return dataCell(entry.release);
  if (key === 'indexer') return dataCell(entry.indexer || '—');
  const [icon, label] = downloadStates[entry.status] || ['circle', entry.status];
  const downloading = entry.status === 'queued' && typeof entry.progress === 'number';
  const status = activityCell('');
  const problem = entry.status === 'queued' && entry.problem;
  // Radarr/Sonarr signale un souci (tracker qui refuse, client bloqué…) : son message est dans l'infobulle
  withIcon(status, problem ? 'alert' : icon, problem ? 'Download problem' : downloading ? 'Downloading' : label);
  if (problem) status.title = entry.problem;
  if (downloading) status.append(document.createTextNode(` · ${entry.progress} %` + (entry.timeleft ? ` · ${entry.timeleft}` : '')));
  return status;
}

// En-têtes et lignes selon les colonnes choisies dans les options du tableau
function renderDownloadTable(target, head, body, rows, empty) {
  const columns = activeColumns(target);
  head.replaceChildren(...columns.map(key => element('th', '', tableDefinition[target].find(([name]) => name === key)[1])));
  activityRows(body, rows.map(entry => columns.map(key => downloadCell(entry, key))), columns.length, empty);
}

// Les importés ont leur propre tableau « terminé » ; le reste (en cours, en attente, en échec) reste dans Téléchargements
function renderDownloads(rows) {
  lastDownloads = rows;
  const imported = rows.filter(entry => entry.status === 'imported')
    .sort((a, b) => String(b.updated || b.created).localeCompare(String(a.updated || a.created)));
  renderDownloadTable('imported', $('#importedHead'), $('#activityImported'), imported, 'Nothing imported yet.');
  renderDownloadTable('downloads', $('#downloadsHead'), $('#activityDownloads'),
    rows.filter(entry => entry.status !== 'imported'), 'No download in progress.');
}

async function refreshActivity() {
  const [activity, downloads] = await Promise.all([api('/api/activity'), api('/api/deliveries').catch(() => null)]);
  renderActivity(activity);
  if (downloads) {
    renderDownloads(downloads);
  } else if (!lastDownloads.length) {
    // Lecture impossible : ne pas laisser croire que l'historique est vide (sinon on garde le dernier affiché)
    for (const [target, body] of [['imported', $('#activityImported')], ['downloads', $('#activityDownloads')]]) {
      activityRows(body, [], activeColumns(target).length, 'Download tracking is temporarily unavailable.');
    }
  }
}
// =================================================


// ======================== EN COURS : ACTUALISATION ========================

// Actualisation toutes les 2,5 s, seulement tant que la page est visible
function startActivityPolling() {
  stopActivityPolling();
  refreshActivity().catch(error => notice(error.message, true));
  activityTimer = setInterval(() => {
    if (!document.hidden) refreshActivity().catch(() => {});
  }, 2500);
}

function stopActivityPolling() {
  if (activityTimer) {
    clearInterval(activityTimer);
    activityTimer = null;
  }
}
// =================================================
