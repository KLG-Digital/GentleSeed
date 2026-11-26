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
