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
