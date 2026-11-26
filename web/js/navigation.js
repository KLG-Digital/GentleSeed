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
