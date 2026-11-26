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
