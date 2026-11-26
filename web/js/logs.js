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
