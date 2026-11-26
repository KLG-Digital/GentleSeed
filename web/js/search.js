// ======================== LISTE DES MÉDIAS ========================
let itemsReady = false;
let itemsLoading = false;

// Portée de la recherche : saison complète (Sonarr) ou un seul épisode / film
function currentSearchScope() {
  return $('#service').value === 'sonarr' ? $('#searchScope').value : 'episode';
}

// Pendant une recherche ou un chargement de liste, on fige les commandes : changer de média
// ou relancer « Actualiser » en cours de route fausserait le résultat affiché.
function updatePreviewButton() {
  const button = $('#preview');
  button.disabled = isSearching || !itemsReady;
  button.title = itemsReady ? '' : 'Search impossible until the media list is loaded';
  $('#load').disabled = isSearching || itemsLoading;
  for (const id of ['#service', '#searchScope', '#media']) $(id).disabled = isSearching;
}

// Médias manquants du service choisi
async function refreshItems() {
  itemsReady = false;
  itemsLoading = true;
  updatePreviewButton();
  const service = $('#service').value;
  $('#searchScopeWrap').hidden = service !== 'sonarr';
  const scope = currentSearchScope();
  const select = $('#media');
  select.replaceChildren(element('option', '', 'Loading missing media…'));
  try {
    const response = await api('/api/items?service=' + service + '&scope=' + scope);
    select.replaceChildren();
    if (!response.items.length) {
      select.append(element('option', '', scope === 'season' ? 'No season with several missing episodes' : 'No missing media'));
      return;
    }
    itemsReady = true;
    for (const media of response.items) {
      // Saison : phrase composée par GentleSeed, à traduire ; film ou épisode : titre intact
      const option = (scope === 'season' ? element : dataElement)('option', '', media.title);
      option.value = media.id;
      if (scope === 'season') option.dataset.seasonNumber = media.seasonNumber;
      select.append(option);
    }
  } catch (error) {
    select.replaceChildren(element('option', '', error.message || 'List unavailable: check the connection to Radarr/Sonarr'));
  } finally {
    itemsLoading = false;
    updatePreviewButton();
  }
}

$('#service').onchange = refreshItems;
$('#searchScope').onchange = refreshItems;
$('#load').onclick = () => refreshItems().catch(error => notice(error.message, true));
// =================================================


// ======================== TITRE ET MOTIFS DE REFUS ========================

// Titre d'une release ; lien vers la page de l'indexeur seulement si l'adresse est en http(s)
function appendReleaseTitle(parent, release) {
  const url = release.infoUrl;
  if (typeof url === 'string' && /^https?:\/\/[^\s]+$/i.test(url)) {
    const link = dataElement('a', 'release-info-link', release.title);
    link.href = url;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    link.title = 'Open the torrent page on the indexer\'s site';
    const mark = element('span', 'external-link-mark');
    mark.append(icon('arrow-up-right'));
    link.append(mark);
    parent.append(link);
  } else {
    parent.setAttribute('translate', 'no');
    parent.textContent = release.title;
  }
}

// L'API garde le message anglais brut de Radarr/Sonarr ; ces modèles le simplifient, puis la traduction s'applique
function readableRejection(message) {
  return String(message)
    .replace(/Quality for release in queue already meets cutoff: ([^·]+)/gi, 'The release in the queue already meets the quality cutoff: $1')
    .replace(/([^·;\s][^·;]*?) is not wanted in profile/gi, 'Quality $1 not allowed by the profile')
    .replace(/Does not contain one of the required terms: ([^·]+)/gi, 'Required terms missing: $1')
    .replace(/French is wanted, but found English/gi, 'French requested, English detected')
    .replace(/Not enough seeders: (\d+)\. Minimum seeders: (\d+)/gi, 'Insufficient seeders: $1 (minimum: $2)');
}
// =================================================


// ======================== TABLEAUX DES RELEASES ========================

// Cellule du tableau pour une colonne donnée
function releaseCell(release, key, approved, index) {
  if (key === 'title') {
    const cell = element('td', 'release-name');
    appendReleaseTitle(cell, release);
    return cell;
  }
  if (['quality', 'source', 'indexer'].includes(key)) {
    return release[key] && release[key] !== 'Unknown' ? dataElement('td', '', release[key]) : element('td', '', 'Unknown');
  }
  if (key === 'codec') return element('td', '', ({h264: 'H.264 / AVC', h265: 'H.265 / HEVC'})[release.codec] || 'Unknown');
  if (key === 'size') return element('td', 'number', formatFileSize(release.size));
  if (['seeders', 'leechers'].includes(key)) return element('td', 'number', release[key] ?? '—');
  if (key === 'status') {
    const cell = element('td');
    if (approved) {
      cell.append(element('span', index === 0 ? 'tag tag-green' : 'tag tag-neutral', index === 0 ? 'PROPOSED' : 'ACCEPTED'));
    } else {
      const reasons = release.reasons?.length ? release.reasons : ['Not eligible'];
      const raw = reasons.join(' · ');
      const span = element('span', 'rejection');
      // Un nœud de texte par motif : la traduction reconnaît chaque motif, pas la phrase assemblée
      reasons.forEach((reason, position) => {
        if (position) span.append(' · ');
        span.append(readableRejection(reason));
      });
      if (raw !== readableRejection(raw)) span.title = raw;
      cell.append(span);
    }
    return cell;
  }
  return element('td', '', '—');
}

// Tableau des releases acceptées ou refusées (bouton « Choose » sur les acceptées, hors démonstration)
function releaseTable(records, title, approved) {
  const section = element('section');
  section.append(element('h3', 'result-table-title', title));
  const scroll = element('div', 'table-scroll');
  const table = element('table', 'data-table releases-table');
  const columns = activeColumns('releases');
  const head = element('thead');
  const headRow = element('tr');
  for (const key of columns) headRow.append(element('th', '', tableDefinition.releases.find(([name]) => name === key)[1]));
  const canChoose = approved && lastResults && !lastResults.demo;
  // Refusées pour leur seule langue : « Send anyway », sur confirmation (film muet, non traduit…)
  const canOverride = !approved && lastResults && !lastResults.demo && records.some(release => release.overridable);
  if (canChoose || canOverride) headRow.append(element('th', '', 'ACTION'));
  head.append(headRow);
  table.append(head);
  const tbody = element('tbody');
  for (const [index, release] of records.entries()) {
    // Pagination commune aux deux groupes : le résultat sélectionné reste présent dans le bandeau supérieur
    const row = element('tr', approved && index === 0 ? 'chosen-row' : '');
    columns.forEach(key => row.append(releaseCell(release, key, approved, index)));
    if (canChoose) {
      const action = element('td');
      const button = element('button', 'button button-subtle', 'Choose');
      button.type = 'button';
      button.addEventListener('click', () => chooseRelease(release, button));
      action.append(button);
      row.append(action);
    } else if (canOverride) {
      const action = element('td');
      if (release.overridable) {
        const button = element('button', 'button button-subtle', 'Send anyway');
        button.type = 'button';
        button.addEventListener('click', () => chooseRelease(release, button, true));
        action.append(button);
      }
      row.append(action);
    }
    tbody.append(row);
  }
  if (!records.length) {
    const row = element('tr');
    const cell = element('td', 'empty', 'No result for this page');
    cell.colSpan = columns.length;
    row.append(cell);
    tbody.append(row);
  }
  table.append(tbody);
  scroll.append(table);
  section.append(scroll);
  return section;
}
// =================================================


// ======================== AFFICHAGE DES RÉSULTATS ========================

// Release proposée : titre, indexeur, codec, taille et seeders
function winnerCard(selected) {
  const winner = element('div', 'winner-card');
  winner.style.marginTop = '17px';
  const text = element('div');
  text.append(withIcon(element('strong'), 'star', 'Proposed release'));
  const proposed = element('p');
  appendReleaseTitle(proposed, selected);
  text.append(proposed);
  const codec = {h264: 'H.264', h265: 'H.265'}[selected.codec] || 'Unknown';
  text.append(element('span', 'winner-context', `Indexer: ${selected.indexer || 'Unknown'} · Codec: ${codec} · Size: ${formatFileSize(selected.size)}`));
  winner.append(text, element('strong', 'winner-count', `${selected.seeders ?? '?'} seeders`));
  return winner;
}

function renderResults(result) {
  if (result !== lastResults) tableState.releases.page = 0;  // nouvelle recherche : on repart de la première page
  lastResults = result;
  const box = $('#previewResult');
  box.replaceChildren();
  const panel = element('section', 'panel results-panel');
  const title = element('div', 'panel-title');
  title.append(element('h2', '', result.demo ? 'Demo · Fictitious data' : 'Search results'));
  const actions = element('div', 'table-tools');
  actions.append(element('span', 'tag tag-green', 'READ-ONLY'));
  const options = withIcon(element('button', 'button button-subtle'), 'gear', 'Table options');
  options.type = 'button';
  options.addEventListener('click', () => openTableOptions('releases'));
  actions.append(options);
  title.append(actions);
  panel.append(title);

  const stats = element('div', 'results-stats');
  for (const value of [`${result.total} releases found`, `${result.accepted} eligible`, `${result.total - result.accepted} rejected`]) {
    stats.append(element('span', 'stat-chip', value));
  }
  if (result.queued) stats.append(element('span', 'stat-chip', 'Media already in the queue'));
  panel.append(stats);

  if (result.selected) {
    panel.append(winnerCard(result.selected));
  } else {
    const message = result.total === 0
      ? 'No release found. The search is finished, but Radarr/Sonarr returned no result for this media.'
      : `${result.total} releases found, but none eligible. See the rejection reasons below.`;
    panel.append(element('div', 'empty search-feedback-empty', message));
  }

  // Acceptées d'abord, puis refusées, sur une pagination commune
  const state = tableState.releases;
  const merged = [...(result.approved || []).map(item => ({...item, approved: true})),
                  ...(result.rejected || []).map(item => ({...item, approved: false}))];
  const start = state.page * state.pageSize;
  const current = merged.slice(start, start + state.pageSize);
  const approved = current.filter(item => item.approved);
  const rejected = current.filter(item => !item.approved);
  if (approved.length) panel.append(releaseTable(approved, 'Eligible releases', true));
  if (rejected.length) panel.append(releaseTable(rejected, 'Rejected releases', false));
  // Des refus de langue existent mais aucun n'est le seul motif : on explique pourquoi « Send anyway » n'est pas proposé
  // Jamais pour un pack de saison : aucun envoi forcé n'y est proposé, même si la langue est le seul motif
  if (!result.demo && result.scope !== 'season' && merged.some(item => !item.approved && item.languageRefused)
      && !merged.some(item => item.overridable)) {
    panel.append(element('p', 'muted',
      'Some releases are refused for their language, but each has another reason too (size, quality, seeders…): none can be sent anyway.'));
  }
  if (!current.length && result.total > 0) panel.append(element('div', 'empty', 'No result on this page.'));
  const pager = element('div');
  tablePager('releases', merged.length, pager);
  panel.append(pager);
  box.append(panel);
}
// =================================================


// ======================== CHOIX MANUEL ET CONFIRMATION ========================

// Envoie la release choisie à Radarr/Sonarr (après confirmation de l'utilisateur)
async function chooseRelease(release, button, overrideLanguage = false) {
  const shown = lastResults;  // une nouvelle recherche vide lastResults pendant l'envoi
  if (!shown || shown.demo || !shown.service || !shown.mediaId) return;
  if (!release.guid || !Number.isInteger(release.indexerId)) return notice('Release cannot be selected', true);
  if (shown.queued) return notice('Media already in the Radarr/Sonarr queue.', true);
  const question = overrideLanguage
    ? await confirmDialog({message: `This release is rejected only for its language: ${(release.reasons || []).map(reason => tr(readableRejection(reason))).join(' · ')}. Send it anyway?`,
                           confirmLabel: 'Send anyway', danger: true})
    : await confirmDialog({message: 'Send this release to Radarr/Sonarr? The *arr application will handle the download.'});
  if (!question) return;
  button.disabled = true;
  notice('Checking with Radarr/Sonarr before sending… This can take a few minutes for a season.');
  try {
    const result = await api('/api/choose', {method: 'POST', body: JSON.stringify({
      service: shown.service, id: shown.mediaId, guid: release.guid, indexerId: release.indexerId,
      scope: shown.scope || 'episode', ...(shown.scope === 'season' ? {seasonNumber: shown.seasonNumber} : {}),
      ...(overrideLanguage ? {overrideLanguage: true} : {})
    })});
    notice(result.message);
    await refreshLogs();
    await refreshStatus();
    if (result.accepted_by_api && !result.simulation) {
      // Non bloquant : la recherche manuelle reste réactive pendant la vérification
      void verifyAcceptedRelease(shown.service, result.verifyMediaId || shown.verifyMediaId || shown.mediaId);
    }
  } catch (error) {
    notice(error.message, true);
  } finally {
    button.disabled = false;
  }
}

// Confirmation différée (lecture seule) : l'API peut accepter une requête sans que le téléchargement soit encore visible.
// Jamais de succès définitif annoncé sans preuve dans la file de Radarr/Sonarr.
async function verifyAcceptedRelease(service, mediaId) {
  const label = service === 'radarr' ? 'Radarr' : 'Sonarr';
  for (let attempt = 0; attempt < 4; attempt++) {
    if (attempt) await sleep(5000);
    try {
      const result = await api(`/api/verify-choice?service=${encodeURIComponent(service)}&media_id=${encodeURIComponent(mediaId)}`);
      if (result.confirmed) {
        notice(`Confirmation: ${label} shows the media in its queue.`);
        await refreshLogs();
        return;
      }
    } catch (error) {
      notice(`Verification impossible: ${error.message}. Check the queue and the logs of Radarr/Sonarr.`, true);
      return;
    }
  }
  notice(`Request accepted by the API: the delayed confirmation continues in the GentleSeed logs. Check the ${label} history if in doubt.`);
}
// =================================================


// ======================== DÉMONSTRATION ========================
async function runDemo() {
  const box = $('#previewResult');
  lastResults = null;  // les anciens résultats ne doivent pas revenir pendant le chargement
  box.replaceChildren(element('div', 'preview-placeholder', 'Loading the demo…'));
  try {
    renderResults(await api('/api/demo'));
    await refreshLogs();
  } catch (error) {
    box.replaceChildren();
    notice(error.message, true);
  }
}

$('#demo').onclick = runDemo;
// =================================================


// ======================== RECHERCHE EN ARRIÈRE-PLAN ========================
// La recherche est lancée côté serveur puis suivie par de courtes requêtes : aucune ne dure longtemps,
// donc les proxys (Cloudflare, ~100 s) ne la coupent pas.

// Étapes envoyées par le serveur (identifiants internes) et leur libellé affiché
const PHASE_LABELS = {
  'waiting for the lock': 'waiting for another operation', 'configuration': 'preparation', 'recherche': 'preparation',
  'version_sonarr': 'checking the Sonarr version', 'inventaire_episodes': 'inventory of episodes', 'file_attente': 'checking the queue',
  'release_saison': 'searching the season\'s releases', 'release': 'searching releases', 'classement': 'ranking the results', 'fin': 'finishing up'
};
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

// Lance la recherche et interroge son avancement toutes les 2 s ; renvoie le résultat
async function runPreviewJob(payload, onProgress) {
  const {job} = await api('/api/preview/start', {method: 'POST', body: JSON.stringify(payload)});
  let failures = 0;
  for (;;) {
    await sleep(2000);
    let status;
    try {
      status = await api('/api/preview/status?job=' + encodeURIComponent(job));
      failures = 0;
    } catch (error) {
      // Coupure réseau brève : on réessaie ; la recherche continue côté serveur
      if (++failures >= 5) throw error;
      continue;
    }
    if (onProgress) onProgress(status);
    if (status.state === 'done') return status.result;
    if (status.state === 'error') throw Error(status.message || 'Search interrupted');
  }
}

$('#preview').onclick = async () => {
  if (isSearching) return;
  const id = Number($('#media').value);
  const service = $('#service').value;
  const scope = currentSearchScope();
  const seasonNumber = scope === 'season' ? Number($('#media').selectedOptions[0]?.dataset.seasonNumber) : null;
  if (!Number.isInteger(id) || id < 1 || (scope === 'season' && !Number.isInteger(seasonNumber))) {
    notice('Choose an available media, or start the demo.', true);
    return;
  }
  isSearching = true;
  lastResults = null;  // idem pour une recherche en cours ou en échec
  updatePreviewButton();
  const feedback = element('div', 'panel search-feedback search-feedback-loading');
  const title = element('strong', '', 'Search in progress in Radarr/Sonarr…');
  const explanation = element('p', '', scope === 'season'
    ? 'Searching a pack for the selected season. Indexers may take a while to respond.'
    : 'Querying the indexers synchronized by Prowlarr.');
  const elapsed = element('small', '', 'Elapsed time: 0 s');
  feedback.append(title, explanation, elapsed);
  $('#previewResult').replaceChildren(feedback);
  const started = Date.now();
  const elapsedTimer = setInterval(() => {
    elapsed.textContent = `Elapsed time: ${Math.floor((Date.now() - started) / 1000)} s`;
  }, 1000);
  try {
    const result = await runPreviewJob({service, id, scope, ...(scope === 'season' ? {seasonNumber} : {})}, status => {
      const label = PHASE_LABELS[status.phase];
      elapsed.textContent = tr(`Elapsed time: ${Math.floor(status.elapsed)} s`) + (label ? ' · ' + tr(`step: ${label}`) : '');
    });
    renderResults(result);
    await refreshLogs();
  } catch (error) {
    const detail = element('div', 'panel search-feedback search-feedback-error');
    detail.append(element('strong', '', 'Search not finished'));
    detail.append(element('p', '', error.message.includes('Failed to fetch')
      ? 'Connection to the GentleSeed server interrupted during the search.'
      : error.message));
    const retry = withIcon(element('button', 'button button-subtle'), 'refresh', 'Try again');
    retry.type = 'button';
    retry.addEventListener('click', () => $('#preview').click());
    detail.append(retry);
    $('#previewResult').replaceChildren(detail);
  } finally {
    clearInterval(elapsedTimer);
    isSearching = false;
    updatePreviewButton();
  }
};
// =================================================
