// ======================== THÈMES ========================
// Le thème est partagé entre la configuration, la connexion et l'application.
// Les identifiants « sombre », « clair » et « maillot-* » sont enregistrés dans settings.json : ne pas les renommer.
'use strict';
(() => {
  const supported = new Set(['sombre', 'clair', 'auto', 'maillot-rose', 'maillot-noir', 'maillot-paris', 'maillot-worlds', 'maillot-violet']);
  const lightJerseys = new Set(['maillot-rose', 'maillot-paris', 'maillot-worlds']);
  let current = 'auto';

  // Applique un thème : classe « clair », variante « maillot » et couleur de la barre du navigateur
  function apply(mode) {
    current = supported.has(mode) ? mode : 'auto';
    const jersey = current.startsWith('maillot-');
    const autoLight = window.matchMedia('(prefers-color-scheme: light)').matches;
    const light = current === 'clair' || lightJerseys.has(current) || (current === 'auto' && autoLight);
    document.documentElement.classList.toggle('light-theme', light);
    document.documentElement.dataset.theme = jersey ? current : 'standard';
    document.documentElement.dataset.themeChoice = current;
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) {
      const colors = {
        'sombre': '#943B70', 'clair': '#C24C92', 'maillot-rose': '#E8B8D6',
        'maillot-paris': '#6F63B6', 'maillot-worlds': '#1E5FBF', 'maillot-noir': '#273245', 'maillot-violet': '#46207C'
      };
      meta.content = colors[current] || (light ? '#C24C92' : '#943B70');
    }
  }

  // Thème enregistré sur le serveur (route publique : sert aussi à la page de connexion)
  async function load() {
    try {
      const response = await fetch('api/theme', {credentials: 'same-origin', cache: 'no-store'});
      if (response.ok) {
        const data = await response.json();
        apply(data.theme);
      }
    } catch (_error) {
      apply(current);
    }
  }

  // En mode « auto », suit le thème du système en direct
  window.matchMedia('(prefers-color-scheme: light)').addEventListener('change', () => {
    if (current === 'auto') apply('auto');
  });

  window.GentleSeedTheme = {apply, load, supported};
})();
// =================================================
