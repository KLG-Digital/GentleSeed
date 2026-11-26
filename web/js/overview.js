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
