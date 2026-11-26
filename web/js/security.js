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
