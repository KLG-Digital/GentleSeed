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
// ======================== NAVIGATION ========================
function closeSidebar() {
  $('#sidebar').classList.remove('open');
  $('#sidebarBackdrop').hidden = true;
  document.body.classList.remove('sidebar-open');
  $('#menuToggle').setAttribute('aria-expanded', 'false');
}

function openSidebar() {
  $('#sidebar').classList.add('open');
  $('#sidebarBackdrop').hidden = false;
  document.body.classList.add('sidebar-open');
  $('#menuToggle').setAttribute('aria-expanded', 'true');
}

// Titre de l'onglet du navigateur : « GentleSeed — <page> » (le nom vient du menu, donc déjà traduit)
let currentPage = 'dashboard';
function updatePageTitle() {
  const label = $(`.nav-item[data-page="${currentPage}"]`)?.textContent.trim();
  if (label) document.title = `GentleSeed — ${label}`;
}

// Affiche une page et charge ses données
function showPage(name, remember = true) {
  if (!['dashboard', 'search', 'activity', 'logs', 'settings', 'system'].includes(name)) return;
  $$('.page').forEach(page => {
    page.hidden = page.id !== `page-${name}`;
    page.classList.toggle('is-active', !page.hidden);
  });
  $$('.nav-item').forEach(button => button.classList.toggle('active', button.dataset.page === name));
  currentPage = name;
  updatePageTitle();
  closeSidebar();
  if (name === 'activity') startActivityPolling();
  else stopActivityPolling();
  // Chaque changement de page est ajouté à l'historique (bouton « précédent ») ; au démarrage et au retour arrière, on remplace
  try {
    if (location.hash !== '#' + name) history[remember ? 'pushState' : 'replaceState'](null, '', '#' + name);
  } catch (_) {}
  if (name === 'logs') refreshLogs().catch(error => notice(error.message, true));
  if (name === 'settings' && !hasUnsavedChanges()) refreshSettings().catch(error => notice(error.message, true));
}

// Quitter une page avec des modifications non enregistrées : fenêtre de confirmation (annuler = on reste sur la page)
async function confirmLeave() {
  if (!hasUnsavedChanges()) return true;
  const leave = await confirmDialog({
    title: 'Unsaved changes', message: 'You have unsaved changes, are you sure you want to leave this page?',
    confirmLabel: 'Discard changes and leave', cancelLabel: 'Stay and review changes', danger: true
  });
  if (leave) discardChanges();
  return leave;
}

// Va à une page, après confirmation s'il y a des modifications non enregistrées
async function goToPage(name, remember = true) {
  if (name !== currentPage && !(await confirmLeave())) {
    // Bouton « précédent » du navigateur : l'adresse a déjà changé, on la remet
    if (!remember) {
      try {
        history.pushState(null, '', '#' + currentPage);
      } catch (_) {}
    }
    return false;
  }
  showPage(name, remember);
  return true;
}

for (const attribute of ['page', 'go']) {
  $$(`[data-${attribute}]`).forEach(button => button.addEventListener('click', event => {
    event.preventDefault();
    goToPage(button.dataset[attribute]);
  }));
}

// Fermer ou recharger l'onglet : le navigateur affiche sa propre demande (son texte ne peut pas être changé)
window.addEventListener('beforeunload', event => {
  if (hasUnsavedChanges()) {
    event.preventDefault();
    event.returnValue = '';
  }
});

$('#menuToggle').setAttribute('aria-expanded', 'false');
$('#menuToggle').setAttribute('aria-controls', 'sidebar');
$('#menuToggle').onclick = () => $('#sidebar').classList.contains('open') ? closeSidebar() : openSidebar();
$('#sidebarBackdrop').addEventListener('click', closeSidebar);
// Un clic en dehors du menu latéral le referme (mobile)
document.addEventListener('pointerdown', event => {
  if ($('#sidebar').classList.contains('open') && !$('#sidebar').contains(event.target) && !$('#menuToggle').contains(event.target)) closeSidebar();
});
document.addEventListener('keydown', event => {
  if (event.key === 'Escape') closeSidebar();
});
window.addEventListener('resize', () => {
  if (window.innerWidth > 660) closeSidebar();
});
// Bouton « précédent » / « suivant » du navigateur, ou adresse modifiée à la main : on affiche la page de l'adresse
window.addEventListener('popstate', () => goToPage(location.hash.replace('#', '') || 'dashboard', false));
$('#quickPreview').onclick = () => goToPage('search');
$('#goDemo').onclick = async () => {
  if (await goToPage('search')) runDemo();
};
// =================================================


// ======================== MENU DU PROFIL ========================
const userMenuToggle = $('#userMenuToggle');
const userMenu = $('#userMenu');

function closeUserMenu() {
  userMenu.hidden = true;
  userMenuToggle.setAttribute('aria-expanded', 'false');
}

function toggleUserMenu() {
  userMenu.hidden = !userMenu.hidden;
  userMenuToggle.setAttribute('aria-expanded', String(!userMenu.hidden));
}

userMenuToggle.onclick = event => {
  event.stopPropagation();
  toggleUserMenu();
};
document.addEventListener('click', event => {
  if (!$('#userMenuAnchor').contains(event.target)) closeUserMenu();
});
document.addEventListener('keydown', event => {
  if (event.key === 'Escape') closeUserMenu();
});

$('#logout').onclick = async () => {
  closeUserMenu();
  if (!await confirmLeave()) return;
  try {
    await api('/api/logout', {method: 'POST', body: '{}'});
    location.replace('login');
  } catch (error) {
    notice(error.message, true);
  }
};
// =================================================


// ======================== ARRÊT ET REDÉMARRAGE ========================

// Demande l'arrêt ou le redémarrage ; après un redémarrage, recharge la page dès que le serveur répond
async function serviceCommand(action) {
  closeUserMenu();
  const question = action === 'restart' ? 'Restart the GentleSeed service?' : 'Stop GentleSeed? You will have to start it again by hand.';
  if (!await confirmDialog({message: question, confirmLabel: 'Confirm', danger: action === 'stop'})) return;
  if (!await confirmLeave()) return;
  const buttons = [$('#serviceRestart'), $('#serviceStop')];
  buttons.forEach(button => button.disabled = true);
  try {
    await api('/api/service/' + action, {method: 'POST', body: '{}'});
    if (action === 'stop') {
      notice('GentleSeed is stopping. To start it again, run the start command (python main.py).');
      return;
    }
    notice('GentleSeed is restarting. The page will refresh as soon as the service responds.');
    // Le serveur peut encore répondre avant l'arrêt : court délai d'abord
    await new Promise(resolve => setTimeout(resolve, 1800));
    for (let attempt = 0; attempt < 35; attempt++) {
      try {
        const response = await fetch('api/status', {cache: 'no-store', signal: AbortSignal.timeout(1500)});
        if (response.ok) {
          location.reload();
          return;
        }
      } catch (_) { /* Le serveur n'est pas encore prêt */ }
      await new Promise(resolve => setTimeout(resolve, 800));
    }
    notice('Restart still in progress: refresh the page in a few moments.', true);
  } catch (error) {
    notice(error.message, true);
  } finally {
    buttons.forEach(button => button.disabled = false);
  }
}

$('#serviceRestart').onclick = () => serviceCommand('restart');
$('#serviceStop').onclick = () => serviceCommand('stop');
// =================================================
// ======================== ÉTAT GÉNÉRAL ========================

// Relit l'état du serveur : jeton CSRF, connexions, état du moteur, boutons du menu
async function refreshStatus() {
  const data = await api('/api/status');
  csrf = data.csrf;
  $('#logout').disabled = data.auth_mode === 'none';
  $('#logout').title = data.auth_mode === 'none' ? 'No session to sign out of (no-account mode)' : '';
  // État réel de la connexion (dernier contrôle ou test) : « Configured » seulement tant qu'aucun résultat n'est connu
  for (const service of ['radarr', 'sonarr']) {
    const health = (data.connections || {})[service];
    const field = $('#' + service);
    field.textContent = !data[service + '_configured'] ? 'Not configured'
      : health === true ? 'Connected'
      : health === false ? 'Connection failed' : 'Configured';
    field.classList.toggle('bad', health === false && !!data[service + '_configured']);
  }
  // La démonstration d'accueil n'apparaît que si aucun service n'est configuré
  const noService = !data.radarr_configured && !data.sonarr_configured;
  $('#demoCallout').hidden = !noService;
  $('#goDemo').hidden = !noService;
  const searchHelp = $('#emptySearchHelp');
  if (searchHelp) {
    searchHelp.textContent = noService
      ? 'Connect Radarr or Sonarr, or start the demo to compare fictitious data.'
      : 'Choose a media in the list to compare the releases actually available.';
  }

  const labels = {operational: 'Operational', paused: 'Paused', degraded: 'Degraded', running: 'Running', starting: 'Waiting'};
  $('#engineStatus').textContent = labels[data.engine_state] || 'Unknown';
  $('#engineStatus').dataset.state = data.engine_state || 'starting';
  $('#engineDetail').textContent = data.engine_detail || 'Status unavailable';
  $('#engineLastScan').textContent = data.last_scan ? ('Last check: ' + dateFormat(data.last_scan)) : 'Not checked yet';
  refreshUpdateChip(data);
  const controls = data.service_controls || {};
  $('#serviceRestart').hidden = !controls.restart;
  $('#serviceStop').hidden = !controls.stop;
  const versionField = $('#systemVersion');
  if (versionField) versionField.textContent = data.version || '—';
  const dataPathField = $('#systemDataPath');
  if (dataPathField) dataPathField.textContent = data.data_dir || '/data';

  form.elements.AUTO_ENABLED.disabled = false;
}
// =================================================
// ======================== PARAMÈTRES ========================

// Remplit le formulaire avec les réglages du serveur (les clés API ne reviennent jamais : seulement « enregistrée »)
async function refreshSettings() {
  const data = await api('/api/settings');
  // Fuseau absent de la liste de ce navigateur (Europe/Kyiv / Europe/Kiev…) : sinon plus rien ne s'enregistre
  const zone = form.elements.UI_TIMEZONE;
  if (data.UI_TIMEZONE && ![...zone.options].some(option => option.value === data.UI_TIMEZONE)) {
    zone.add(new Option(data.UI_TIMEZONE, data.UI_TIMEZONE));
  }
  for (const name of [...strings, ...numbers]) form.elements[name].value = data[name] ?? '';
  setIgnoredIndexers(data.IGNORED_INDEXERS_RADARR, data.IGNORED_INDEXERS_SONARR);
  applyTheme(data.UI_THEME);
  for (const name of toggles) form.elements[name].checked = !!data[name];
  try {
    applyRegionFromForm();
  } catch (error) {
    console.warn('Invalid regional settings', error);
  }

  form.elements.RADARR_API_KEY.value = '';
  form.elements.SONARR_API_KEY.value = '';
  $('#rkey').textContent = data.RADARR_API_KEY_SET ? 'Key saved' : 'Not configured';
  form.elements.RADARR_API_KEY.placeholder = data.RADARR_API_KEY_SET ? '•••••••••••• (key kept)' : 'Enter the API key';
  $('#skey').textContent = data.SONARR_API_KEY_SET ? 'Key saved' : 'Not configured';
  form.elements.SONARR_API_KEY.placeholder = data.SONARR_API_KEY_SET ? '•••••••••••• (key kept)' : 'Enter the API key';
}
// =================================================


// ======================== ENREGISTREMENT ========================
let settingsSaving = false;
let settingsDirty = false;

// Enregistre le formulaire
async function saveSettings() {
  if (settingsSaving) return;
  settingsSaving = true;
  const submit = form.querySelector('button[type=submit]');
  const payload = {};
  for (const name of strings) payload[name] = form.elements[name].value.trim();
  for (const name of numbers) payload[name] = Number(form.elements[name].value);
  for (const name of toggles) payload[name] = form.elements[name].checked;
  Object.assign(payload, ignoredIndexersPayload());
  // Une clé vide veut dire « garder la clé enregistrée »
  for (const name of ['RADARR_API_KEY', 'SONARR_API_KEY']) {
    const key = form.elements[name].value.trim();
    if (key) payload[name] = key;
  }
  submit.disabled = true;
  try {
    await api('/api/settings', {method: 'POST', body: JSON.stringify(payload)});
    settingsDirty = false;
    try {
      localStorage.setItem('gentleseed.locale', payload.UI_LANGUAGE);
    } catch (_) {}
    await refreshSettings();
    await refreshStatus();
    withIcon($('#savedState'), 'check', 'Changes saved');
    await refreshItems();
    notice('Settings saved. The configuration is persistent.');
  } catch (error) {
    notice(error.message, true);
  } finally {
    submit.disabled = false;
    settingsSaving = false;
  }
}

form.addEventListener('submit', event => {
  event.preventDefault();
  saveSettings();
});
for (const eventName of ['input', 'change']) {
  form.addEventListener(eventName, () => {
    settingsDirty = true;
    withIcon($('#savedState'), 'dot', 'Unsaved changes');
  });
}

// Réglages ou compte modifiés mais pas encore enregistrés (la fenêtre « Unsaved changes » s'ouvre alors en quittant la page)
function hasUnsavedChanges() {
  return settingsDirty || securityDirty;
}

// Abandonne les modifications : le formulaire reprend les valeurs enregistrées (langue et thème aussi)
function discardChanges() {
  settingsDirty = false;
  securityDirty = false;
  $('#securityForm').reset();
  securityFields();
  refreshSecurity().catch(() => {});  // sinon le formulaire montre « Aucun » et un nom vide
  refreshSettings().then(() => withIcon($('#savedState'), 'check', 'No change')).catch(() => {});
}
// =================================================


// ======================== TEST DE CONNEXION ========================

// Teste l'accès à Radarr ou Sonarr et affiche le résultat à côté du bouton
async function checkConnection(service) {
  const label = $(`#connection-${service}`);
  const button = $(`.test-connection[data-service="${service}"]`);
  label.classList.remove('bad');
  label.textContent = 'Checking…';
  button.disabled = true;
  try {
    // L'adresse et la clé saisies sont testées telles quelles, sans être enregistrées (clé vide : celle déjà enregistrée)
    const result = await api('/api/connection', {method: 'POST', body: JSON.stringify({
      service, url: form.elements[service.toUpperCase() + '_URL'].value.trim(),
      api_key: form.elements[service.toUpperCase() + '_API_KEY'].value.trim()
    })});
    if (result.ok) {
      withIcon(label, 'check', result.message);
      label.append(` · v${result.version}`);
    } else label.textContent = result.message;
    label.classList.toggle('bad', !result.ok);
    if (result.ok) {
      await refreshStatus();
      if (result.saved) await refreshItems();
    } else {
      notice(label.textContent, true);
    }
    return !!result.ok;
  } catch (error) {
    label.textContent = error.message;
    label.classList.add('bad');
    notice(error.message, true);
    return false;
  } finally {
    button.disabled = false;
  }
}

// Le test utilise ce qui est saisi, même avant l'enregistrement
$$('.test-connection').forEach(button => button.addEventListener('click', () => checkConnection(button.dataset.service)));

// Entrée dans un champ de clé API : teste
for (const service of ['radarr', 'sonarr']) {
  form.elements[service.toUpperCase() + '_API_KEY'].addEventListener('keydown', event => {
    if (event.key === 'Enter' && !event.isComposing) {
      event.preventDefault();
      checkConnection(service);
    }
  });
}
// =================================================
// ======================== INDEXEURS À IGNORER ========================
// La liste vient de Radarr et de Sonarr (/api/indexers) ; les cases cochées sont enregistrées avec le formulaire des réglages.
const indexerServices = ['radarr', 'sonarr'];
let ignoredIndexers = {radarr: [], sonarr: []};
let knownIndexers = [];

// Reprend les listes enregistrées (appelé à chaque lecture des réglages)
function setIgnoredIndexers(radarr, sonarr) {
  ignoredIndexers = {radarr: [...(radarr || [])], sonarr: [...(sonarr || [])]};
  renderIndexers();
  loadIndexers(true).catch(() => {});  // chargement discret : aucune alerte si Radarr/Sonarr ne répond pas
}

// Listes à envoyer avec les réglages
function ignoredIndexersPayload() {
  return {IGNORED_INDEXERS_RADARR: ignoredIndexers.radarr, IGNORED_INDEXERS_SONARR: ignoredIndexers.sonarr};
}

function indexerCell(name, service, services) {
  const cell = document.createElement('td');
  const ignored = ignoredIndexers[service].includes(name);
  // Une case n'existe que si l'indexeur est dans ce service (ou déjà ignoré, pour pouvoir le décocher)
  if (!services.has(service) && !ignored) {
    cell.textContent = '—';
    return cell;
  }
  const box = document.createElement('input');
  box.type = 'checkbox';
  box.checked = ignored;
  box.setAttribute('aria-label', `${name} · ${serviceNames[service]}`);
  box.addEventListener('change', () => {
    const list = ignoredIndexers[service].filter(item => item !== name);
    if (box.checked) list.push(name);
    ignoredIndexers[service] = list;
  });
  cell.append(box);
  return cell;
}

function renderIndexers() {
  const body = $('#indexerRows');
  if (!body) return;
  const names = new Map();
  for (const item of knownIndexers) names.set(item.name, new Set(item.services));
  for (const service of indexerServices) {
    for (const name of ignoredIndexers[service]) if (!names.has(name)) names.set(name, new Set());
  }
  body.replaceChildren();
  if (!names.size) {
    const row = document.createElement('tr');
    const cell = document.createElement('td');
    cell.colSpan = 3;
    cell.append(trNode('Load the indexer list to choose.'));
    row.append(cell);
    body.append(row);
    return;
  }
  const sorted = [...names].sort((a, b) => a[0].localeCompare(b[0], undefined, {sensitivity: 'base'}));
  for (const [name, services] of sorted) {
    const row = document.createElement('tr');
    const label = document.createElement('td');
    label.textContent = name;
    label.setAttribute('translate', 'no');  // nom d'indexeur : jamais traduit
    row.append(label, ...indexerServices.map(service => indexerCell(name, service, services)));
    body.append(row);
  }
}

async function loadIndexers(quiet = false) {
  const data = await api('/api/indexers');
  knownIndexers = data.indexers || [];
  renderIndexers();
  if (!quiet) for (const message of Object.values(data.errors || {})) notice(message, true);
}

$('#indexerLoad').addEventListener('click', () => {
  loadIndexers().catch(error => notice(error.message, true));
});
// =================================================
// ======================== VÉRIFICATION MANUELLE ========================

// Bouton « Check now » : demande un passage immédiat du moteur automatique
$('#scanNow').addEventListener('click', async event => {
  event.preventDefault();
  const button = $('#scanNow');
  button.disabled = true;
  try {
    const result = await api('/api/scan', {method: 'POST', body: '{}'});
    notice(result.message || 'Check requested');
  } catch (error) {
    notice(error.message, true);
  } finally {
    button.disabled = false;
  }
});
// =================================================
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
// ======================== JOURNAUX ========================

// Relit les événements du serveur (tableau de la page Journaux et 4 dernières lignes du tableau de bord)
async function refreshLogs() {
  const level = $('#loglevel').value;
  const events = await api('/api/logs?limit=300&level=' + encodeURIComponent(level));
  lastEvents = events;
  renderEventsTable();
  const recent = $('#recentLogs');
  recent.replaceChildren();
  if (!events.length) recent.append(element('div', 'empty', 'No log available for now.'));
  for (const event of [...events].reverse().slice(0, 4)) {
    recent.append(recentRow(event));
  }
}

$('#loglevel').onchange = () => {
  tableState.events.page = 0;
  refreshLogs().catch(error => notice(error.message, true));
};
$('#refresh').onclick = () => refreshLogs().catch(error => notice(error.message, true));
// =================================================
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
// ======================== SOUS-MENUS ========================

// Affiche un onglet de la page Paramètres ou Système
function switchTab(group, name) {
  $$(`[data-${group}-content]`).forEach(el => el.hidden = el.dataset[`${group}Content`] !== name);
  $$(`[data-${group}-tab]`).forEach(el => el.classList.toggle('active', el.dataset[`${group}Tab`] === name));
  if (group === 'settings') {
    $('#settingsSavebar').hidden = name === 'security' || name === 'integration';
    if (name === 'security') refreshSecurity().catch(error => notice(error.message, true));
    if (name === 'integration') refreshIntegration().catch(error => notice(error.message, true));
  }
  if (group === 'system') loadSystemTab(name).catch(error => notice(error.message, true));
}

$$('[data-settings-tab]').forEach(button => button.addEventListener('click', event => {
  event.preventDefault();
  switchTab('settings', button.dataset.settingsTab);
}));
$$('[data-system-tab]').forEach(button => button.addEventListener('click', event => {
  event.preventDefault();
  switchTab('system', button.dataset.systemTab);
}));

$('#advancedToggle').onclick = () => {
  advancedEnabled = !advancedEnabled;
  document.body.classList.toggle('show-advanced', advancedEnabled);
  withIcon($('#advancedToggle'), 'gear', advancedEnabled ? 'Hide advanced settings' : 'Show advanced settings');
};
// =================================================


// ======================== SÉCURITÉ ========================
async function refreshSecurity() {
  const data = await api('/api/security');
  securityMode = data.mode;
  const security = $('#securityForm');
  security.elements.mode.value = data.mode;
  security.elements.mode.querySelector('[value=none]').disabled = !data.no_auth_allowed;
  $('#securityNoneHint').hidden = data.no_auth_allowed;
  security.elements.username.value = data.username || '';
  securityFields();
  $('#securityCurrentRow').hidden = data.mode === 'none';
}

// Champs de compte : visibles et obligatoires seulement en mode Formulaire
function securityFields() {
  const enabled = $('#securityMode').value === 'form';
  $$('.security-credential').forEach(row => row.hidden = !enabled);
  const security = $('#securityForm');
  security.elements.username.required = enabled;
  const newAccount = securityMode === 'none';
  security.elements.password.required = enabled && newAccount;
  security.elements.confirm_password.required = enabled && newAccount;
  $('#securityCurrentRow').hidden = securityMode === 'none';
}

$('#securityMode').onchange = securityFields;

// Champs du compte modifiés mais pas encore envoyés (voir hasUnsavedChanges)
let securityDirty = false;
$('#securityForm').addEventListener('input', () => {
  securityDirty = true;
});
$('#securityForm').addEventListener('change', () => {
  securityDirty = true;
});
$('#securityForm').addEventListener('reset', () => {
  securityDirty = false;
});

$('#securityForm').addEventListener('submit', async event => {
  event.preventDefault();
  const security = $('#securityForm');
  const button = security.querySelector('button[type=submit]');
  const data = {
    mode: security.elements.mode.value,
    username: security.elements.username.value.trim(),
    password: security.elements.password.value,
    confirm_password: security.elements.confirm_password.value,
    current_password: security.elements.current_password.value
  };
  if (data.mode === 'none' && !await confirmDialog({message: 'Disable form sign-in? Without authentication, access is limited to PCs on the local network.', danger: true})) return;
  button.disabled = true;
  try {
    const answer = await api('/api/security', {method: 'POST', body: JSON.stringify(data)});
    csrf = answer.csrf;
    security.reset();
    await refreshSecurity();
    await refreshStatus();
    notice('Security updated. Old sessions were invalidated.');
  } catch (error) {
    notice(error.message, true);
  } finally {
    button.disabled = false;
  }
});
// =================================================
// ======================== INTÉGRATION RADARR / SONARR ========================
let integrationWebhookUrl = '';
let integrationConfig = {base_url: '', cleanup: false, radarr: false, sonarr: false};
const integrationNames = {radarr: 'Radarr', sonarr: 'Sonarr'};

// Adresse du navigateur, seulement s'il est lui-même sur le réseau local (jamais un domaine ou un proxy)
function localOrigin() {
  const host = location.hostname;
  const privateAddress = /^(10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.)/.test(host) || host.endsWith('.local');
  return privateAddress ? location.origin : '';
}

// Le serveur choisit l'adresse finale ; le navigateur ne propose que la sienne si elle est locale
function integrationBase() {
  return localOrigin();
}

// Morceaux séparés : chacun est traduit pour lui-même
function describeLastWebhook(last) {
  if (!last) return ['No message received since startup'];
  return [last.event === 'Test' ? 'Webhook test' : 'Media added', ' · ', last.source, ' · ', formatRegional(last.at)];
}

// État de l'intégration par service ; les boutons sont inactifs si le service est absent ou non configuré
async function refreshIntegration() {
  const data = await api('/api/integration?base_url=' + encodeURIComponent(integrationBase()));
  integrationConfig = data.config || integrationConfig;
  const icons = {active: 'check', outdated: 'alert', absent: 'circle', error: 'x', unconfigured: 'circle'};
  for (const service of ['radarr', 'sonarr']) {
    const info = data.services[service] || {state: 'error', message: 'Unexpected response'};
    withIcon($('#integration' + integrationNames[service]), icons[info.state] || 'circle', info.message);
    $$(`[data-integration][data-service="${service}"]`).forEach(button => {
      button.disabled = info.state === 'unconfigured' || (button.dataset.integration !== 'install' && info.state === 'absent');
    });
  }
  $('#integrationCleanup').checked = !!integrationConfig.cleanup;
  integrationWebhookUrl = data.webhook_url || '';
  $('#integrationLast').replaceChildren(...describeLastWebhook(data.last_webhook));
}
// =================================================


// ======================== ACTIONS ========================

// Installer, tester ou retirer le webhook d'un service
async function integrationAction(action, service, button) {
  if (button) button.disabled = true;
  try {
    const result = await api('/api/integration/' + action, {method: 'POST', body: JSON.stringify({service, base_url: integrationBase()})});
    const label = integrationNames[service];
    if (action === 'install') {
      notice(`Webhook installed in ${label}. Click Test to check the link. Remember to untick automatic search on add in ${label}, otherwise two downloads are possible.`);
    } else if (action === 'remove') {
      notice(result.removed ? `Webhook removed from ${label}.` : `Nothing to remove in ${label}.`);
    } else {
      notice(result.message);
    }
  } catch (error) {
    notice(error.message, true);
  } finally {
    await refreshIntegration().catch(() => {});
  }
}

$$('[data-integration]').forEach(button => button.addEventListener('click', () => {
  integrationAction(button.dataset.integration, button.dataset.service, button);
}));

// Case « Retirer l'intégration à l'arrêt »
$('#integrationCleanup').addEventListener('change', async event => {
  try {
    await api('/api/settings', {method: 'POST', body: JSON.stringify({INTEGRATION_CLEANUP: event.target.checked})});
    notice(event.target.checked
      ? 'The integration will be removed when GentleSeed stops and restored at startup.'
      : 'The integration will stay in place when GentleSeed stops.');
  } catch (error) {
    notice(error.message, true);
    event.target.checked = !event.target.checked;
  } finally {
    await refreshIntegration().catch(() => {});
  }
});

$('#integrationRemoveAll').addEventListener('click', async () => {
  if (!await confirmDialog({message: 'Remove the GentleSeed integration from Radarr and Sonarr?', confirmLabel: 'Remove', danger: true})) return;
  const button = $('#integrationRemoveAll');
  button.disabled = true;
  try {
    const messages = [];
    for (const service of ['radarr', 'sonarr']) {
      try {
        const result = await api('/api/integration/remove', {method: 'POST', body: JSON.stringify({service})});
        messages.push(tr(`${integrationNames[service]}: ${result.removed ? 'removed' : 'nothing to remove'}`));
      } catch (error) {
        messages.push(`${integrationNames[service]}: ${tr(error.message)}`);
      }
    }
    notice(messages.join(' · '));
  } finally {
    button.disabled = false;
    await refreshIntegration().catch(() => {});
  }
});

$('#integrationToken').addEventListener('click', async () => {
  if (!await confirmDialog({message: 'Regenerate the token? Webhooks already installed will stop working until you reinstall them.', confirmLabel: 'Regenerate the token', danger: true})) return;
  try {
    await api('/api/integration/token', {method: 'POST', body: '{}'});
    notice('Token regenerated: reinstall the webhook in Radarr and Sonarr.');
    await refreshIntegration();
  } catch (error) {
    notice(error.message, true);
  }
});
// =================================================


// ======================== COPIE DE L'ADRESSE ========================

// Copie sans l'API moderne (page en http:// où elle est bloquée), via un champ caché dans la page
function copyWithFallback(text) {
  const area = document.createElement('textarea');
  area.value = text;
  area.setAttribute('readonly', '');
  area.style.cssText = 'position:fixed;top:0;left:0;opacity:0';
  document.body.append(area);
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

$('#integrationCopy').addEventListener('click', async () => {
  const button = $('#integrationCopy');
  try {
    await refreshIntegration();
    const text = integrationWebhookUrl;
    if (!text) throw new Error('address unavailable');
    if (navigator.clipboard && window.isSecureContext) await navigator.clipboard.writeText(text);
    else copyWithFallback(text);
    button.original = button.original || [...button.childNodes];  // garde le texte d'origine
    withIcon(button, 'check', 'Copied');
    button.classList.add('copied');
    clearTimeout(button.copiedTimer);
    button.copiedTimer = setTimeout(() => {
      button.replaceChildren(...button.original);
      button.classList.remove('copied');
    }, 2000);
  } catch (error) {
    notice('Copy failed: ' + error.message, true);
  }
});
// =================================================
// ======================== COULEURS DES JOURNAUX ========================
// Fonction pure (aucun accès à la page) : elle ne renvoie qu'un nom de classe pour une ligne de journal.
//   erreur → rouge    avertissement → orange    démarrage / arrêt → bleu
//   succès (demande acceptée, release confirmée, importation…) → vert    le reste → couleur normale
const LOG_SUCCESS_WORDS = [
  'request accepted', 'release confirmed by', 'import confirmed by', 'pack handed to', 'season handed to',
  'link operational', 'release is in the queue', 'gentleseed webhook installed',
  // Journaux écrits avant le passage à l'anglais
  'demande acceptée', "confirmée par l'historique", 'confirmée par l’historique', 'importation confirmée',
  'pack transmis', 'saison transmise', 'liaison opérationnelle', 'release présente dans la file', 'webhook gentleseed installé'
];

function classifyLogLine(line) {
  const text = String(line);
  const level = (/^\[[^\]]*\]\s*\[(ERROR|WARN|INFO|DEBUG)\]/.exec(text) || [])[1];
  if (level === 'ERROR') return 'log-error';
  if (level === 'WARN') return 'log-warn';
  if (text.includes('──') && /(Startup|Shutdown|Démarrage|Arrêt)/.test(text)) return 'log-lifecycle';
  if (/web interface and engine (started|stopped)|interface Web et moteur (démarrés|arrêtés)/.test(text)) return 'log-lifecycle';
  const lower = text.toLowerCase();
  if (LOG_SUCCESS_WORDS.some(word => lower.includes(word))) return 'log-ok';
  return '';
}

// Remplit un élément <pre> ligne par ligne ; le texte reste identique (copie et export inchangés)
function renderColoredLog(container, text, kinds) {
  container.replaceChildren();
  const lines = String(text).split('\n');
  lines.forEach((line, index) => {
    const span = document.createElement('span');
    const kind = kinds ? (kinds[index] || '') : classifyLogLine(line);
    if (kind) span.className = kind;
    span.textContent = index < lines.length - 1 ? line + '\n' : line;
    container.append(span);
  });
}
// =================================================
// ======================== SYSTÈME : ÉTAT ========================

function formatDuration(seconds) {
  seconds = Math.max(0, Math.round(seconds));
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor(seconds % 86400 / 3600);
  const minutes = Math.floor(seconds % 3600 / 60);
  const d = formatUnit(days, 'day'), h = formatUnit(hours, 'hour'), m = formatUnit(minutes, 'minute');
  return days ? `${d} ${h}` : hours ? `${h} ${m}` : m;
}

function overviewFact(label, value) {
  const row = element('div', 'fact');
  row.append(element('span', '', label), element('strong', '', value));
  return row;
}

// Une ligne de santé pour un service ; le lien d'aide ne s'ouvre que sur une adresse https
function healthLine(item) {
  const line = element('p', 'overview-line ' + (item.type === 'error' ? 'overview-bad' : 'overview-warn'));
  withIcon(line, item.type === 'error' ? 'x' : 'alert', item.message);
  if (item.wiki) {
    const link = element('a', 'download-link', 'Help');
    link.href = item.wiki;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    line.append(' ', link);
  }
  return line;
}

// Santé de Radarr et Sonarr, informations de version et état de GentleSeed
function renderOverview(data) {
  const me = data.gentleseed;
  $('#systemUptime').textContent = formatDuration(me.uptime);
  $('#systemWatch').replaceChildren(trNode(me.auto_enabled ? 'Active' : 'Paused'),
    ...(me.last_scan ? [' · ', trNode(`last pass ${dateFormat(me.last_scan)}`)] : []));
  const names = {radarr: 'Radarr', sonarr: 'Sonarr'};
  const entries = Object.entries(data.services);

  const health = $('#overviewHealth');
  health.replaceChildren();
  const about = $('#overviewAbout');
  about.replaceChildren();
  if (!entries.length) {
    for (const box of [health, about]) box.append(element('p', 'muted', 'No service configured (Settings → Connections).'));
    return;
  }
  for (const [name, info] of entries) {
    const label = names[name] || name;
    // Santé
    health.append(element('strong', '', label));
    if (!info.ok) {
      const line = element('p', 'overview-line overview-bad');
      withIcon(line, 'x', `${label} is not responding (${info.error || 'error'}).`);
      health.append(line);
    } else if (!info.health.length && !info.health_error) {
      const line = element('p', 'overview-line overview-good');
      withIcon(line, 'check', 'No problem detected.');
      health.append(line);
    } else {
      for (const item of info.health) health.append(healthLine(item));
      if (info.health_error) health.append(element('p', 'muted', 'Health checks unavailable.'));
    }
    // À propos
    about.append(overviewFact(label, info.ok ? `${info.version}${info.branch ? ' · ' + info.branch : ''}` : 'Unreachable'));
    if (info.ok) {
      if (info.os) about.append(overviewFact(`${label} · system`, info.os + (info.docker ? ' · Docker' : '')));
      if (info.runtime) about.append(overviewFact(`${label} · .NET`, info.runtime));
      if (info.start_time) about.append(overviewFact(`${label} · started`, dateFormat(info.start_time)));
    }
  }
  about.append(overviewFact('GentleSeed', `${me.version} · Python ${me.python} · ${me.tracked} media tracked`));
}

async function refreshOverview() {
  renderOverview(await api('/api/overview'));
}
// =================================================
// ======================== SYSTÈME : SAUVEGARDES ========================

// Liste des sauvegardes avec télécharger, restaurer et supprimer
async function loadBackups() {
  const data = await api('/api/backups');
  const body = $('#backupRows');
  body.replaceChildren();
  if (!data.items.length) {
    const row = element('tr');
    const cell = element('td', '', 'No backup yet.');
    cell.colSpan = 5;
    row.append(cell);
    body.append(row);
  }
  for (const item of data.items) {
    const row = element('tr');
    row.append(dataElement('td', '', item.name), element('td', '', item.created ? dateTime(item.created) : '—'),
               element('td', '', formatFileSize(item.size)), element('td', '', item.includes_keys ? 'Included' : 'No'));
    const actions = element('td', 'task-actions');
    const download = element('a', 'button button-subtle', 'Download');
    download.href = 'api/backups/' + encodeURIComponent(item.name);
    download.download = item.name;
    const restore = element('button', 'button button-subtle', 'Restore');
    restore.type = 'button';
    restore.addEventListener('click', () => restoreBackup({name: item.name}, item.name));
    const remove = element('button', 'button button-subtle', 'Delete');
    remove.type = 'button';
    remove.addEventListener('click', async () => {
      if (!await confirmDialog({message: `Delete the backup ${item.name}?`, confirmLabel: 'Delete', danger: true})) return;
      try {
        await api('/api/backups/' + encodeURIComponent(item.name) + '/delete', {method: 'POST', body: '{}'});
        await loadBackups();
      } catch (error) {
        notice(error.message, true);
      }
    });
    actions.append(download, restore, remove);
    row.append(actions);
    body.append(row);
  }
  $('#backupFooter').textContent = `The last ${data.keep} backups are kept in the data folder, plus the last ${data.keep_safety} safety copies made before a restore (pre-restore).`;
}

// Restaure une sauvegarde du dossier ({name}) ou un fichier importé ({content}) ; le serveur fait d'abord une copie de sécurité
async function restoreBackup(payload, label) {
  if (!await confirmDialog({message: `Restore "${label}"? Your current settings will be replaced. A safety copy is created just before.`, confirmLabel: 'Restore'})) return;
  try {
    const result = await api('/api/backups/restore', {method: 'POST', body: JSON.stringify(payload)});
    if (result.cleared?.length) {
      notice(`Settings restored. Enter the API key again for ${result.cleared.join(', ')}. Safety copy: ${result.safety}`, true);
    } else {
      notice('Settings restored. Safety copy: ' + result.safety);
    }
    await refreshSettings().catch(() => {});
    await refreshStatus().catch(() => {});
    await loadBackups();
  } catch (error) {
    notice(error.message, true);
  }
}
// =================================================


// ======================== CRÉER ET IMPORTER ========================
$('#backupCreate').addEventListener('click', async () => {
  const button = $('#backupCreate');
  const keys = $('#backupKeys').checked;
  if (keys && !await confirmDialog({message: 'The file will contain your API keys and give access to Radarr and Sonarr. Continue?'})) return;
  button.disabled = true;
  try {
    const result = await api('/api/backups', {method: 'POST', body: JSON.stringify({include_keys: keys})});
    notice('Backup created: ' + result.name);
    await loadBackups();
  } catch (error) {
    notice(error.message, true);
  } finally {
    button.disabled = false;
  }
});

$('#backupImport').addEventListener('click', () => $('#backupFile').click());

$('#backupFile').addEventListener('change', async event => {
  const file = event.target.files[0];
  event.target.value = '';
  if (!file) return;
  if (file.size > 1000000) {
    notice('File too large (1 MB maximum).', true);
    return;
  }
  let content;
  try {
    content = JSON.parse(await file.text());
  } catch (_) {
    notice('This file is not valid JSON.', true);
    return;
  }
  await restoreBackup({content}, file.name);
});
// =================================================
// ======================== SYSTÈME : MISES À JOUR ========================

// Historique des versions ; bandeau et commandes de mise à jour seulement si une version plus récente existe
async function loadUpdates(refresh = false) {
  const data = await api('/api/updates' + (refresh ? '?refresh=1' : ''));
  $('#updateCheck').checked = data.enabled;
  const banner = $('#updateBanner');
  banner.replaceChildren();
  banner.hidden = true;
  const list = $('#updateList');
  list.replaceChildren();
  if (data.state === 'disabled') {
    list.append(element('p', 'muted', 'Check disabled.'));
    return;
  }
  if (data.state === 'no_repo') {
    list.append(element('p', 'muted', 'Check disabled.'));
    return;
  }
  if (data.state === 'error') list.append(element('p', 'overview-line overview-bad', data.error));
  if (data.update_available) {
    banner.hidden = false;
    banner.append(element('strong', '', `Version ${data.latest} available (you are using ${data.current}).`),
      element('span', 'muted', ' With the published Docker image:'), element('code', '', 'sudo docker compose pull && sudo docker compose up -d'),
      element('span', 'muted', ' Or, if you build from the source:'), element('code', '', 'sudo docker compose up --build -d'));
  } else if (data.state === 'ok' && data.latest) {
    // « À jour » seulement si une version publiée existe et qu'on ne la dépasse pas
    const line = element('p', 'overview-line overview-good');
    withIcon(line, 'check', `GentleSeed ${data.current} is up to date.`);
    list.append(line);
  }
  for (const release of data.releases || []) list.append(releaseBox(release, data.current));
  if (!(data.releases || []).length && data.state === 'ok') list.append(element('p', 'muted', 'No published release.'));
}

// Une version : titre, date, notes et lien vers GitHub
function releaseBox(release, current) {
  const box = element('div', 'activity-item');
  const title = element('strong');
  title.append(dataElement('span', '', release.name || release.tag), ` — ${release.published ? dateTime(release.published) : ''}`);
  if (release.tag === 'v' + current || release.tag === current) title.append(' · ', 'installed');
  box.append(title);
  if (release.notes) box.append(dataElement('p', 'release-notes', release.notes));
  if (release.url) {
    const link = element('a', 'download-link', 'View on GitHub');
    link.href = release.url;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    box.append(link);
  }
  return box;
}
// =================================================


// ======================== ACTIONS ET PASTILLE ========================
$('#updateRefresh').addEventListener('click', () => loadUpdates(true).catch(error => notice(error.message, true)));

// La case enregistre tout de suite (le dépôt vérifié est fixe : aucun champ à remplir)
$('#updateCheck').addEventListener('change', async () => {
  try {
    await api('/api/settings', {method: 'POST', body: JSON.stringify({UPDATE_CHECK: $('#updateCheck').checked})});
    notice('Update settings saved.');
    await loadUpdates(true);
  } catch (error) {
    notice(error.message, true);
  }
});

// Pastille « Update x.y.z » du menu : ouvre l'onglet Mises à jour
$('#updateChip').addEventListener('click', async event => {
  event.preventDefault();
  if (await goToPage('system')) switchTab('system', 'updates');
});

function refreshUpdateChip(data) {
  const chip = $('#updateChip');
  chip.hidden = !data.update_available;
  if (data.update_available) chip.textContent = `Update ${data.latest_version}`;
}
// =================================================
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
// ======================== TABLEAU DES ÉVÉNEMENTS ========================

// Cellule du tableau pour une colonne donnée
function eventCell(event, key) {
  if (key === 'level') {
    const cell = element('td');
    cell.append(element('span', 'log-badge ' + event.level, event.level));
    return cell;
  }
  if (key === 'time') return element('td', '', dateTime(event.time));
  if (key === 'component') return element('td', '', event.component || 'GentleSeed');
  if (key === 'message') {
    const cell = element('td', 'event-message');
    cell.append(messageNode(event.message));
    return cell;
  }
  if (key === 'actions') {
    const cell = element('td');
    const button = element('button', 'event-detail-button', 'Details');
    button.type = 'button';
    button.addEventListener('click', click => {
      click.stopPropagation();
      showEventDetails(event);
    });
    cell.append(button);
    return cell;
  }
  return element('td', '', '—');
}

// Tableau filtré par la recherche, du plus récent au plus ancien, avec pagination
function renderEventsTable() {
  const tbody = $('#eventRows');
  const thead = $('#eventHead');
  if (!tbody || !thead) return;
  tbody.replaceChildren();
  thead.replaceChildren();
  const columns = activeColumns('events');
  const head = element('tr');
  for (const key of columns) {
    const label = tr(tableDefinition.events.find(([name]) => name === key)[1]);
    head.append(element('th', '', label.toLocaleUpperCase(selectedLocale())));
  }
  thead.append(head);
  const query = ($('#logsearch')?.value || '').trim().toLocaleLowerCase();
  const events = [...lastEvents].reverse().filter(event => !query
    || [event.message, event.component, event.level].some(part => String(part || '').toLocaleLowerCase().includes(query)));
  const state = tableState.events;
  const start = state.page * state.pageSize;
  for (const event of events.slice(start, start + state.pageSize)) {
    const row = element('tr', 'event-row');
    row.tabIndex = 0;
    row.title = 'Show details';
    columns.forEach(key => row.append(eventCell(event, key)));
    row.addEventListener('click', () => showEventDetails(event));
    row.addEventListener('keydown', keyEvent => {
      if (keyEvent.key === 'Enter' || keyEvent.key === ' ') {
        keyEvent.preventDefault();
        showEventDetails(event);
      }
    });
    tbody.append(row);
  }
  if (!events.length) {
    const row = element('tr');
    const cell = element('td', 'empty', 'No events');
    cell.colSpan = columns.length;
    row.append(cell);
    tbody.append(row);
  }
  tablePager('events', events.length, $('#eventPager'));
}

$('#logsearch').addEventListener('input', () => {
  tableState.events.page = 0;
  renderEventsTable();
});
// =================================================
// ======================== APPARENCE ========================
function applyTheme(mode) {
  window.GentleSeedTheme.apply(mode);
}

form.elements.UI_THEME.addEventListener('change', event => applyTheme(event.target.value));
window.matchMedia('(prefers-color-scheme: light)').addEventListener('change', () => applyTheme(form.elements.UI_THEME.value));
// =================================================


// ======================== DÉMARRAGE ========================
(async () => {
  try {
    await refreshStatus();
    await refreshSettings();
    await refreshLogs();
    await refreshItems();
    const page = location.hash.replace('#', '');
    showPage(page || 'dashboard', false);
    switchTab('settings', 'connections');
    switchTab('system', 'health');
    if (!form.elements.RADARR_URL.value && !form.elements.SONARR_URL.value && !page) {
      showPage('settings', false);
      notice('Welcome! Configure Radarr or Sonarr, or try the demo without a connection.');
    }
  } catch (error) {
    notice(error.message, true);
  }
})();

// État et journaux actualisés toutes les 4 s
setInterval(() => {
  refreshStatus().catch(() => {});
  refreshLogs().catch(() => {});
}, 4000);
// =================================================


// ======================== LOGOS DES APPLICATIONS ========================
// Les lettres R et S restent invisibles tant que les logos officiels sont chargés.
// Une initiale n'apparaît qu'en dernier recours, si les deux sources SVG échouent.
// (Le logo GentleSeed est un fichier statique : web/assets/gentleseed-logo.svg.)
for (const logo of document.querySelectorAll('[data-service-logo]')) {
  const fallback = logo.parentElement.querySelector('.service-logo-fallback');
  const original = {
    radarr: 'https://raw.githubusercontent.com/Radarr/Radarr/develop/Logo/Radarr.svg',
    sonarr: 'https://raw.githubusercontent.com/Sonarr/Sonarr/develop/Logo/Sonarr.svg'
  }[logo.dataset.serviceLogo];
  let fallbackAttempted = false;
  logo.addEventListener('load', () => {
    if (fallback) fallback.hidden = true;
    logo.hidden = false;
  });
  logo.addEventListener('error', () => {
    if (!fallbackAttempted && original) {
      fallbackAttempted = true;
      logo.src = original;
    } else {
      logo.hidden = true;
      if (fallback) fallback.hidden = false;
    }
  });
  // Si une image a échoué avant la pose des écouteurs (ressource en cache)
  if (logo.complete && logo.naturalWidth === 0) {
    logo.dispatchEvent(new Event('error'));
  }
}
// =================================================
