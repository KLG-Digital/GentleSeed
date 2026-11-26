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
