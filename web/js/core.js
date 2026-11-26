// ======================== ÉTAT ET CONSTANTES ========================
'use strict';
const $ = selector => document.querySelector(selector);
const $$ = selector => [...document.querySelectorAll(selector)];
const form = $('#settings');
const numbers = ['MIN_SEEDERS', 'CHECK_INTERVAL', 'PROBE_INTERVAL', 'NEW_DEMAND_DELAY', 'RETRY_INTERVAL', 'REQUEST_TIMEOUT', 'MAX_SEARCHES_PER_CYCLE', 'LANGUAGE_FALLBACK_AFTER'];
const strings = ['RADARR_URL', 'SONARR_URL', 'UI_THEME', 'UI_LANGUAGE', 'UI_TIMEZONE', 'UI_HOUR_FORMAT', 'UI_DATE_FORMAT', 'LOG_LEVEL', 'PREFERRED_CODEC', 'CODEC_PRIORITY', 'TEAM_PREFERENCE'];
const toggles = ['ONLY_NEW', 'AUTO_ENABLED', 'ALLOW_UNKNOWN_SEEDERS', 'UI_SHOW_SECONDS'];
let csrf = '';
let isSearching = false;
let securityMode = 'none';
let advancedEnabled = false;
let lastResults = null;
let lastEvents = [];
let lastDownloads = [];
let optionsTarget = 'releases';
// =================================================


// ======================== COLONNES DES TABLEAUX ========================
const tableDefinition = {
  releases: [['title', 'Release'], ['quality', 'Quality'], ['source', 'Source'], ['indexer', 'Indexer'],
             ['seeders', 'Seeders'], ['codec', 'Codec'], ['size', 'Size'], ['leechers', 'Leechers'], ['status', 'Status / rejection']],
  events: [['level', 'Level'], ['time', 'Time'], ['component', 'Component'], ['message', 'Message'], ['actions', 'Actions']],
  downloads: [['time', 'Time'], ['service', 'Service'], ['release', 'Release'], ['indexer', 'Indexer'], ['status', 'Status']],
  imported: [['time', 'Time'], ['service', 'Service'], ['release', 'Release'], ['indexer', 'Indexer']]
};
const defaultColumns = {
  releases: ['title', 'quality', 'source', 'indexer', 'seeders', 'codec', 'size', 'status'],
  events: ['level', 'time', 'message', 'actions'],  // « component » reste disponible dans les options (toujours GentleSeed)
  downloads: ['time', 'service', 'release', 'indexer', 'status'],
  imported: ['time', 'service', 'release', 'indexer']
};
const optionTitles = {releases: 'Search results options', events: 'Log table options',
                      downloads: 'Download table options', imported: 'Finished table options'};
const unpaged = ['downloads', 'imported'];  // tableaux courts : pas de « lignes par page »
const tableState = {};

// État de départ d'un tableau : colonnes par défaut, 25 lignes par page
function defaultTableState(target) {
  return {order: tableDefinition[target].map(([key]) => key), visible: new Set(defaultColumns[target]), pageSize: 25, page: 0};
}

// Relit les options enregistrées dans le navigateur (colonnes, ordre, taille de page)
for (const target of Object.keys(tableDefinition)) {
  try {
    const cached = JSON.parse(localStorage.getItem('gentleseed.table.' + target) || '{}');
    const available = new Set(tableDefinition[target].map(([key]) => key));
    const known = list => list.filter(key => available.has(key));
    const order = [...new Set(Array.isArray(cached.order) ? known(cached.order) : defaultColumns[target])];
    for (const [key] of tableDefinition[target]) if (!order.includes(key)) order.push(key);
    const visible = Array.isArray(cached.visible) ? known(cached.visible) : [...defaultColumns[target]];
    tableState[target] = {
      order,
      visible: new Set(visible.length ? visible : defaultColumns[target]),
      pageSize: [10, 25, 50, 100].includes(cached.pageSize) ? cached.pageSize : 25,
      page: 0
    };
  } catch (_) {
    tableState[target] = defaultTableState(target);
  }
}

function saveTableState(target) {
  const state = tableState[target];
  try {
    localStorage.setItem('gentleseed.table.' + target, JSON.stringify({order: state.order, visible: [...state.visible], pageSize: state.pageSize}));
  } catch (_) {}
}
// =================================================


// ======================== OUTILS WEB ========================

// Icône du sprite SVG de layout.html (jamais d'émoji ni de symbole Unicode décoratif)
const SVG_NS = 'http://www.w3.org/2000/svg';
function icon(name) {
  const svg = document.createElementNS(SVG_NS, 'svg');
  svg.setAttribute('class', 'icon');
  svg.setAttribute('aria-hidden', 'true');
  svg.setAttribute('focusable', 'false');
  const use = document.createElementNS(SVG_NS, 'use');
  use.setAttribute('href', '#i-' + name);
  svg.append(use);
  return svg;
}

// Traduit un texte du serveur ou composé par l'interface (sans traduction, il reste en anglais)
function tr(text) {
  return window.GentleSeedI18n?.t(String(text)) || String(text);
}

// Texte traduit qui reste traduisible si la langue change ensuite
function trNode(text) {
  return window.GentleSeedI18n?.textNode(text) || document.createTextNode(String(text));
}

// Icône suivie d'un texte traduit
function withIcon(node, name, text = '') {
  node.textContent = '';
  node.append(icon(name));
  if (text) node.append(' ', trNode(text));
  return node;
}

// Crée un élément ; le texte passe par textContent (jamais innerHTML : titres de torrents non fiables)
function element(tag, className = '', value = '') {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (value !== '') node.append(trNode(value));
  return node;
}

// Élément contenant une donnée venue de l'extérieur (titre, release, indexeur, nom de fichier) : jamais traduit
function dataElement(tag, className = '', value = '') {
  const node = document.createElement(tag);
  if (className) node.className = className;
  node.setAttribute('translate', 'no');
  node.textContent = value;
  return node;
}

// Durée avec son unité écrite dans la langue choisie
function formatUnit(value, unit) {
  return new Intl.NumberFormat(selectedLocale(), {style: 'unit', unit, unitDisplay: 'short'}).format(value);
}

// Notification flottante (8 s), visible où que l'on soit dans la page ; un clic la ferme.
// Elle utilise l'API popover quand le navigateur la connaît (passe alors au-dessus des fenêtres de dialogue).
function showNotice(box) {
  if (box.showPopover) {
    if (!box.matches(':popover-open')) box.showPopover();
  } else {
    box.hidden = false;
  }
}

function hideNotice(box) {
  if (box.hidePopover) {
    if (box.matches(':popover-open')) box.hidePopover();
  } else {
    box.hidden = true;
  }
}

function notice(message, isError = false) {
  const box = $('#notification');
  box.replaceChildren(trNode(message));
  box.classList.toggle('error', isError);
  showNotice(box);
  clearTimeout(window.noticeTimeout);
  window.noticeTimeout = setTimeout(() => hideNotice(box), 8000);
}

// Sans API popover, la boîte démarre cachée ; un clic sur la notification la ferme
if (!$('#notification').showPopover) $('#notification').hidden = true;
$('#notification').addEventListener('click', event => hideNotice(event.currentTarget));

// Appel de l'API : jeton CSRF sur les actions, redirection si la session a expiré
async function api(path, options = {}) {
  const headers = {...(options.headers || {})};
  if (options.method && options.method !== 'GET') {
    headers['Content-Type'] = 'application/json';
    headers['X-CSRF-Token'] = csrf;
  }
  const response = await fetch(path.replace(/^\//, ''), {...options, headers});
  if (response.status === 401) {
    location.replace('login');
    throw Error('Session expired');
  }
  if (response.status === 409 && path === '/api/status') {
    location.replace('setup');
    throw Error('Initial configuration required');
  }
  // Un proxy peut renvoyer une page HTML (ex. 504 après 60 s) : on l'explique au lieu d'afficher « Unexpected token '<' »
  const raw = await response.text();
  let data;
  try {
    data = JSON.parse(raw);
  } catch (_error) {
    if (response.status === 524) {
      throw Error("Response interrupted (HTTP 524): Cloudflare, placed in front of the server, cut the request after about 100 s without a response. The search may still have been running. This is not a \"no result\". For a long search, open GentleSeed directly through its local address, without Cloudflare.");
    }
    const timeoutLike = [408, 502, 503, 504].includes(response.status);
    throw Error(timeoutLike
      ? `Response interrupted (HTTP ${response.status}): the server or an intermediate proxy cut the request, probably a timeout. This is not a "no result".`
      : `Unexpected server response (HTTP ${response.status}), unreadable.`);
  }
  if (!response.ok) throw Error(typeof data.detail === 'string' ? data.detail : 'Unexpected error');
  return data;
}

// Taille lisible (B, KiB, MiB…) selon la langue choisie
function formatFileSize(bytes) {
  if (!Number.isFinite(bytes) || bytes < 0) return '—';
  const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB'];
  let value = bytes;
  let index = 0;
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024;
    index++;
  }
  return `${value.toLocaleString(selectedLocale(), {maximumFractionDigits: index === 0 ? 0 : 2})} ${units[index]}`;
}
// =================================================


// ======================== FORMATS RÉGIONAUX ========================
let regional = {UI_LANGUAGE: 'auto', UI_TIMEZONE: 'auto', UI_HOUR_FORMAT: 'auto', UI_DATE_FORMAT: 'auto', UI_SHOW_SECONDS: true};

function browserLocale() {
  return navigator.language || 'en';
}

function selectedLocale() {
  return window.GentleSeedI18n?.locale(regional.UI_LANGUAGE) || browserLocale();
}

function detectedBrowserZone() {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
  } catch (_) {
    return 'UTC';
  }
}

// Fuseau d'affichage ; un nom inconnu d'Intl (Europe/Kyiv sur un ancien navigateur) ferait planter les dates
const knownZones = new Map();  // nom de fuseau -> accepté par ce navigateur

function zoneSupported(zone) {
  if (!knownZones.has(zone)) {
    try {
      new Intl.DateTimeFormat('en', {timeZone: zone});
      knownZones.set(zone, true);
    } catch (_) {
      knownZones.set(zone, false);
    }
  }
  return knownZones.get(zone);
}

function regionalZone() {
  const zone = regional.UI_TIMEZONE;
  return zone !== 'auto' && zoneSupported(zone) ? zone : detectedBrowserZone();
}

// Date et heure selon les réglages (langue, fuseau, 12/24 h, format de date, secondes)
function formatRegional(raw, includeDate = true) {
  if (!raw) return '—';
  const date = new Date(raw);
  if (Number.isNaN(date.getTime())) return String(raw);
  const options = {
    hour: '2-digit', minute: '2-digit',
    hour12: regional.UI_HOUR_FORMAT === 'auto' ? undefined : regional.UI_HOUR_FORMAT === '12'
  };
  if (regional.UI_SHOW_SECONDS) options.second = '2-digit';
  options.timeZone = regionalZone();
  const format = regional.UI_DATE_FORMAT;
  if (!includeDate) return new Intl.DateTimeFormat(selectedLocale(), options).format(date);
  const withDate = {...options, year: 'numeric', month: '2-digit', day: '2-digit'};
  if (format === 'auto') return new Intl.DateTimeFormat(selectedLocale(), withDate).format(date);
  // Format de date imposé : on assemble les morceaux nous-mêmes
  const parts = new Intl.DateTimeFormat(selectedLocale(), withDate).formatToParts(date);
  const get = kind => parts.find(part => part.type === kind)?.value || '';
  const day = get('day'), month = get('month'), year = get('year');
  const datePart = format === 'ch' ? [day, month, year].join('.')
    : format === 'eu' ? [day, month, year].join('/')
    : format === 'us' ? [month, day, year].join('/')
    : [year, month, day].join('-');
  const timeParts = [get('hour'), get('minute')];
  if (regional.UI_SHOW_SECONDS) timeParts.push(get('second'));
  const marker = get('dayPeriod') ? ' ' + get('dayPeriod') : '';  // présent seulement en format 12 h
  return datePart + ' ' + timeParts.join(':') + marker;
}

function dateFormat(raw) {
  return formatRegional(raw, true);
}

function dateTime(raw) {
  return formatRegional(raw, true);
}

// Texte d'un message de journal : la ligne de séparation (démarrage/arrêt) reçoit sa classe pour rester sur une ligne sur téléphone
function messageNode(message) {
  const text = message || '';
  return /^─{4,}\s/.test(text) ? element('span', 'log-separator', text) : document.createTextNode(text);
}

// Une ligne de l'activité récente (tableau de bord)
function recentRow(event) {
  const row = element('div', 'recent-entry');
  row.append(element('span', 'log-badge ' + event.level, event.level));
  const content = element('div');
  const message = element('p');
  message.append(messageNode(event.message));
  content.append(message);
  content.append(element('small', '', dateTime(event.time)));
  row.append(content);
  return row;
}

function updateRegionalPreview() {
  const preview = $('#regionalPreview');
  if (!preview) return;
  preview.textContent = formatRegional(new Date().toISOString());
  if (regional.UI_TIMEZONE !== 'auto' && !zoneSupported(regional.UI_TIMEZONE)) {
    preview.append(' · ', trNode('This browser does not know the saved time zone: times use the browser time zone.'));
  }
}

function readRegionalForm() {
  for (const name of ['UI_LANGUAGE', 'UI_TIMEZONE', 'UI_HOUR_FORMAT', 'UI_DATE_FORMAT']) regional[name] = form.elements[name].value;
  regional.UI_SHOW_SECONDS = form.elements.UI_SHOW_SECONDS.checked;
}

// Applique la langue et les formats choisis à tout ce qui est déjà affiché
function applyRegionFromForm() {
  readRegionalForm();
  document.documentElement.lang = selectedLocale().split('-')[0];
  Promise.resolve(window.GentleSeedI18n?.apply(regional.UI_LANGUAGE)).then(() => {
    updatePageTitle();
    updateRegionalPreview();
    renderEventsTable();
    if (lastResults) renderResults(lastResults);
  });
  updateRegionalPreview();
  renderEventsTable();
  const recent = $('#recentLogs');
  if (recent && lastEvents.length) {
    recent.replaceChildren();
    for (const event of [...lastEvents].reverse().slice(0, 4)) {
      recent.append(recentRow(event));
    }
  }
  if ($('#fileDetailsDialog')?.open && logViewRaw !== null) updateLogFilePreview();
  if (lastResults) renderResults(lastResults);
  if (!$('#page-system').hidden) {
    const selected = $('[data-system-tab].active');
    if (selected) void loadSystemTab(selected.dataset.systemTab).catch(() => {});
  }
}

// Liste des fuseaux horaires du navigateur (liste courte si non disponible)
function initTimezones() {
  const select = $('#uiTimezone');
  if (!select) return;
  let names = [];
  try {
    names = Intl.supportedValuesOf('timeZone');
  } catch (_) {
    names = ['Europe/Zurich', 'Europe/Paris', 'Europe/London', 'America/New_York', 'America/Los_Angeles', 'America/Sao_Paulo', 'Asia/Tokyo', 'Asia/Seoul', 'Asia/Shanghai', 'UTC'];
  }
  if (!names.includes('UTC')) names.unshift('UTC');
  const autoOption = select.querySelector('option[value="auto"]');
  if (autoOption) autoOption.textContent = 'Automatic (browser: ' + detectedBrowserZone() + ')';
  for (const zone of names) {
    const option = document.createElement('option');
    option.value = zone;
    option.textContent = zone;
    select.append(option);
  }
}
initTimezones();

for (const name of ['UI_LANGUAGE', 'UI_TIMEZONE', 'UI_HOUR_FORMAT', 'UI_DATE_FORMAT', 'UI_SHOW_SECONDS']) {
  form.elements[name].addEventListener('change', () => {
    try {
      applyRegionFromForm();
    } catch (error) {
      notice(error.message, true);
    }
  });
}
// =================================================


// ======================== FENÊTRES ET OPTIONS DES TABLEAUX ========================
function openDialog(id) {
  const dialog = $('#' + id);
  if (dialog && !dialog.open) dialog.showModal();
}

function closeDialog(id) {
  const dialog = $('#' + id);
  if (dialog && dialog.open) dialog.close();
}

$$('[data-close-dialog]').forEach(button => button.addEventListener('click', () => closeDialog(button.dataset.closeDialog)));
// Un clic en dehors de la fenêtre la ferme
$$('.gs-dialog').forEach(dialog => dialog.addEventListener('click', event => {
  if (event.target === dialog) dialog.close();
}));

// Fenêtre de confirmation aux couleurs du thème (remplace confirm() : textes traduits, bouton d'action en évidence).
// Renvoie une promesse : vrai si l'utilisateur confirme ; Échap, la croix ou un clic à côté valent « annuler ».
function confirmDialog({title = 'Confirmation', message, confirmLabel = 'Confirm', cancelLabel = 'Cancel', danger = false}) {
  const dialog = $('#confirmDialog');
  if (dialog.open) return Promise.resolve(false);
  return new Promise(resolve => {
    let answer = false;
    $('#confirmTitle').textContent = tr(title);
    $('#confirmMessage').textContent = tr(message);
    $('#confirmOk').textContent = tr(confirmLabel);
    $('#confirmOk').classList.toggle('button-danger', danger);
    $('#confirmOk').classList.toggle('button-primary', !danger);
    $('#confirmCancel').textContent = tr(cancelLabel);
    $('#confirmOk').onclick = () => {
      answer = true;
      dialog.close();
    };
    $('#confirmCancel').onclick = () => dialog.close();
    $('#confirmClose').onclick = () => dialog.close();
    dialog.addEventListener('close', () => resolve(answer), {once: true});
    dialog.showModal();
    $('#confirmCancel').focus();  // la touche Entrée ne valide jamais une action risquée par mégarde
  });
}

function showEventDetails(event) {
  $('#detailLevel').textContent = event.level || 'INFO';
  $('#detailLevel').className = 'log-badge ' + (event.level || 'INFO');
  $('#detailDate').textContent = dateTime(event.time);
  $('#detailComponent').textContent = event.component || 'GentleSeed';
  $('#detailMessage').textContent = tr(event.message || 'No message');  // <pre> : non suivi par la traduction
  openDialog('detailsDialog');
}

function activeColumns(target) {
  const state = tableState[target];
  return state.order.filter(key => state.visible.has(key));
}

function openTableOptions(target) {
  optionsTarget = target;
  $('#optionsTitle').textContent = optionTitles[target];
  $('#tablePageSizeRow').hidden = unpaged.includes(target);
  $('#tablePageSize').value = String(tableState[target].pageSize);
  renderOptionRows();
  openDialog('tableOptionsDialog');
}

// Une ligne par colonne : case à cocher (une colonne au moins reste visible) et flèches pour l'ordre
function renderOptionRows() {
  const target = optionsTarget;
  const state = tableState[target];
  const root = $('#tableColumnOptions');
  root.replaceChildren();
  for (const key of state.order) {
    const label = tableDefinition[target].find(([name]) => name === key)?.[1] || key;
    const row = element('div', 'column-option');
    const text = element('label', 'column-option-label');
    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.checked = state.visible.has(key);
    checkbox.addEventListener('change', () => {
      if (checkbox.checked) state.visible.add(key);
      else if (state.visible.size > 1) state.visible.delete(key);
      else checkbox.checked = true;
      saveTableState(target);
      updateTables();
    });
    text.append(checkbox, element('span', '', label));
    row.append(text);
    for (const [direction, symbol] of [[-1, 'arrow-up'], [1, 'arrow-down']]) {
      const move = withIcon(element('button', 'column-move'), symbol);
      move.type = 'button';
      move.title = tr(direction < 0 ? 'Move up' : 'Move down');
      const position = state.order.indexOf(key);
      move.disabled = position + direction < 0 || position + direction >= state.order.length;
      move.addEventListener('click', () => {
        const index = state.order.indexOf(key);
        const other = index + direction;
        [state.order[index], state.order[other]] = [state.order[other], state.order[index]];
        saveTableState(target);
        renderOptionRows();
        updateTables();
      });
      row.append(move);
    }
    root.append(row);
  }
}

$('#tablePageSize').addEventListener('change', event => {
  const state = tableState[optionsTarget];
  state.pageSize = Number(event.target.value);
  state.page = 0;
  saveTableState(optionsTarget);
  updateTables();
});

$('#resetTableOptions').addEventListener('click', () => {
  const target = optionsTarget;
  tableState[target] = defaultTableState(target);
  saveTableState(target);
  $('#tablePageSize').value = '25';
  renderOptionRows();
  updateTables();
});

document.addEventListener('click', event => {
  const button = event.target.closest('[data-table-options]');
  if (button) openTableOptions(button.dataset.tableOptions);
});

// Pagination « 1–25 of N » avec flèches précédent / suivant
function tablePager(target, length, targetNode) {
  const state = tableState[target];
  const pages = Math.max(1, Math.ceil(length / state.pageSize));
  state.page = Math.min(state.page, pages - 1);
  const wrap = element('div', 'table-pager-inner');
  const first = length ? state.page * state.pageSize + 1 : 0;
  const last = Math.min(length, (state.page + 1) * state.pageSize);
  wrap.append(element('span', '', `${first}–${last} of ${length}`));
  for (const [label, direction] of [['‹', -1], ['›', 1]]) {
    const button = element('button', 'button button-subtle', label);
    button.type = 'button';
    button.disabled = state.page + direction < 0 || state.page + direction >= pages;
    button.addEventListener('click', () => {
      state.page += direction;
      updateTables();
    });
    wrap.append(button);
  }
  targetNode.replaceChildren(wrap);
}

function updateTables() {
  if (lastResults) renderResults(lastResults);
  renderEventsTable();
  renderDownloads(lastDownloads);
}
// =================================================
