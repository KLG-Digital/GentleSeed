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
