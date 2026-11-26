// ======================== PARAMÈTRES ========================

// Remplit le formulaire avec les réglages du serveur (les clés API ne reviennent jamais : seulement « enregistrée »)
async function refreshSettings() {
  const data = await api('/api/settings');
  // Fuseau absent de la liste de ce navigateur (Europe/Kyiv / Europe/Kiev…) : sinon plus rien ne s'enregistre
  const zone = form.elements.UI_TIMEZONE;
  if (data.UI_TIMEZONE && ![...zone.options].some(option => option.value === data.UI_TIMEZONE)) {
    zone.add(new Option(data.UI_TIMEZONE, data.UI_TIMEZONE));
  }
  for (const name of [...strings, ...numbers]) form.elements[name].value = data[name] ?? '';
  setIgnoredIndexers(data.IGNORED_INDEXERS_RADARR, data.IGNORED_INDEXERS_SONARR);
  applyTheme(data.UI_THEME);
  for (const name of toggles) form.elements[name].checked = !!data[name];
  try {
    applyRegionFromForm();
  } catch (error) {
    console.warn('Invalid regional settings', error);
  }

  form.elements.RADARR_API_KEY.value = '';
  form.elements.SONARR_API_KEY.value = '';
  $('#rkey').textContent = data.RADARR_API_KEY_SET ? 'Key saved' : 'Not configured';
  form.elements.RADARR_API_KEY.placeholder = data.RADARR_API_KEY_SET ? '•••••••••••• (key kept)' : 'Enter the API key';
  $('#skey').textContent = data.SONARR_API_KEY_SET ? 'Key saved' : 'Not configured';
  form.elements.SONARR_API_KEY.placeholder = data.SONARR_API_KEY_SET ? '•••••••••••• (key kept)' : 'Enter the API key';
}
// =================================================


// ======================== ENREGISTREMENT ========================
let settingsSaving = false;
let settingsDirty = false;

// Enregistre le formulaire
async function saveSettings() {
  if (settingsSaving) return;
  settingsSaving = true;
  const submit = form.querySelector('button[type=submit]');
  const payload = {};
  for (const name of strings) payload[name] = form.elements[name].value.trim();
  for (const name of numbers) payload[name] = Number(form.elements[name].value);
  for (const name of toggles) payload[name] = form.elements[name].checked;
  Object.assign(payload, ignoredIndexersPayload());
  // Une clé vide veut dire « garder la clé enregistrée »
  for (const name of ['RADARR_API_KEY', 'SONARR_API_KEY']) {
    const key = form.elements[name].value.trim();
    if (key) payload[name] = key;
  }
  submit.disabled = true;
  try {
    await api('/api/settings', {method: 'POST', body: JSON.stringify(payload)});
    settingsDirty = false;
    try {
      localStorage.setItem('gentleseed.locale', payload.UI_LANGUAGE);
    } catch (_) {}
    await refreshSettings();
    await refreshStatus();
    withIcon($('#savedState'), 'check', 'Changes saved');
    await refreshItems();
    notice('Settings saved. The configuration is persistent.');
  } catch (error) {
    notice(error.message, true);
  } finally {
    submit.disabled = false;
    settingsSaving = false;
  }
}

form.addEventListener('submit', event => {
  event.preventDefault();
  saveSettings();
});
for (const eventName of ['input', 'change']) {
  form.addEventListener(eventName, () => {
    settingsDirty = true;
    withIcon($('#savedState'), 'dot', 'Unsaved changes');
  });
}

// Réglages ou compte modifiés mais pas encore enregistrés (la fenêtre « Unsaved changes » s'ouvre alors en quittant la page)
function hasUnsavedChanges() {
  return settingsDirty || securityDirty;
}

// Abandonne les modifications : le formulaire reprend les valeurs enregistrées (langue et thème aussi)
function discardChanges() {
  settingsDirty = false;
  securityDirty = false;
  $('#securityForm').reset();
  securityFields();
  refreshSecurity().catch(() => {});  // sinon le formulaire montre « Aucun » et un nom vide
  refreshSettings().then(() => withIcon($('#savedState'), 'check', 'No change')).catch(() => {});
}
// =================================================


// ======================== TEST DE CONNEXION ========================

// Teste l'accès à Radarr ou Sonarr et affiche le résultat à côté du bouton
async function checkConnection(service) {
  const label = $(`#connection-${service}`);
  const button = $(`.test-connection[data-service="${service}"]`);
  label.classList.remove('bad');
  label.textContent = 'Checking…';
  button.disabled = true;
  try {
    // L'adresse et la clé saisies sont testées telles quelles, sans être enregistrées (clé vide : celle déjà enregistrée)
    const result = await api('/api/connection', {method: 'POST', body: JSON.stringify({
      service, url: form.elements[service.toUpperCase() + '_URL'].value.trim(),
      api_key: form.elements[service.toUpperCase() + '_API_KEY'].value.trim()
    })});
    if (result.ok) {
      withIcon(label, 'check', result.message);
      label.append(` · v${result.version}`);
    } else label.textContent = result.message;
    label.classList.toggle('bad', !result.ok);
    if (result.ok) {
      await refreshStatus();
      if (result.saved) await refreshItems();
    } else {
      notice(label.textContent, true);
    }
    return !!result.ok;
  } catch (error) {
    label.textContent = error.message;
    label.classList.add('bad');
    notice(error.message, true);
    return false;
  } finally {
    button.disabled = false;
  }
}

// Le test utilise ce qui est saisi, même avant l'enregistrement
$$('.test-connection').forEach(button => button.addEventListener('click', () => checkConnection(button.dataset.service)));

// Entrée dans un champ de clé API : teste
for (const service of ['radarr', 'sonarr']) {
  form.elements[service.toUpperCase() + '_API_KEY'].addEventListener('keydown', event => {
    if (event.key === 'Enter' && !event.isComposing) {
      event.preventDefault();
      checkConnection(service);
    }
  });
}
// =================================================
