// ======================== INTÉGRATION RADARR / SONARR ========================
let integrationWebhookUrl = '';
let integrationConfig = {base_url: '', cleanup: false, radarr: false, sonarr: false};
const integrationNames = {radarr: 'Radarr', sonarr: 'Sonarr'};

// Adresse du navigateur, seulement s'il est lui-même sur le réseau local (jamais un domaine ou un proxy)
function localOrigin() {
  const host = location.hostname;
  const privateAddress = /^(10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.)/.test(host) || host.endsWith('.local');
  return privateAddress ? location.origin : '';
}

// Le serveur choisit l'adresse finale ; le navigateur ne propose que la sienne si elle est locale
function integrationBase() {
  return localOrigin();
}

// Morceaux séparés : chacun est traduit pour lui-même
function describeLastWebhook(last) {
  if (!last) return ['No message received since startup'];
  return [last.event === 'Test' ? 'Webhook test' : 'Media added', ' · ', last.source, ' · ', formatRegional(last.at)];
}

// État de l'intégration par service ; les boutons sont inactifs si le service est absent ou non configuré
async function refreshIntegration() {
  const data = await api('/api/integration?base_url=' + encodeURIComponent(integrationBase()));
  integrationConfig = data.config || integrationConfig;
  const icons = {active: 'check', outdated: 'alert', absent: 'circle', error: 'x', unconfigured: 'circle'};
  for (const service of ['radarr', 'sonarr']) {
    const info = data.services[service] || {state: 'error', message: 'Unexpected response'};
    withIcon($('#integration' + integrationNames[service]), icons[info.state] || 'circle', info.message);
    $$(`[data-integration][data-service="${service}"]`).forEach(button => {
      button.disabled = info.state === 'unconfigured' || (button.dataset.integration !== 'install' && info.state === 'absent');
    });
  }
  $('#integrationCleanup').checked = !!integrationConfig.cleanup;
  integrationWebhookUrl = data.webhook_url || '';
  $('#integrationLast').replaceChildren(...describeLastWebhook(data.last_webhook));
}
// =================================================


// ======================== ACTIONS ========================

// Installer, tester ou retirer le webhook d'un service
async function integrationAction(action, service, button) {
  if (button) button.disabled = true;
  try {
    const result = await api('/api/integration/' + action, {method: 'POST', body: JSON.stringify({service, base_url: integrationBase()})});
    const label = integrationNames[service];
    if (action === 'install') {
      notice(`Webhook installed in ${label}. Click Test to check the link. Remember to untick automatic search on add in ${label}, otherwise two downloads are possible.`);
    } else if (action === 'remove') {
      notice(result.removed ? `Webhook removed from ${label}.` : `Nothing to remove in ${label}.`);
    } else {
      notice(result.message);
    }
  } catch (error) {
    notice(error.message, true);
  } finally {
    await refreshIntegration().catch(() => {});
  }
}

$$('[data-integration]').forEach(button => button.addEventListener('click', () => {
  integrationAction(button.dataset.integration, button.dataset.service, button);
}));

// Case « Retirer l'intégration à l'arrêt »
$('#integrationCleanup').addEventListener('change', async event => {
  try {
    await api('/api/settings', {method: 'POST', body: JSON.stringify({INTEGRATION_CLEANUP: event.target.checked})});
    notice(event.target.checked
      ? 'The integration will be removed when GentleSeed stops and restored at startup.'
      : 'The integration will stay in place when GentleSeed stops.');
  } catch (error) {
    notice(error.message, true);
    event.target.checked = !event.target.checked;
  } finally {
    await refreshIntegration().catch(() => {});
  }
});

$('#integrationRemoveAll').addEventListener('click', async () => {
  if (!await confirmDialog({message: 'Remove the GentleSeed integration from Radarr and Sonarr?', confirmLabel: 'Remove', danger: true})) return;
  const button = $('#integrationRemoveAll');
  button.disabled = true;
  try {
    const messages = [];
    for (const service of ['radarr', 'sonarr']) {
      try {
        const result = await api('/api/integration/remove', {method: 'POST', body: JSON.stringify({service})});
        messages.push(tr(`${integrationNames[service]}: ${result.removed ? 'removed' : 'nothing to remove'}`));
      } catch (error) {
        messages.push(`${integrationNames[service]}: ${tr(error.message)}`);
      }
    }
    notice(messages.join(' · '));
  } finally {
    button.disabled = false;
    await refreshIntegration().catch(() => {});
  }
});

$('#integrationToken').addEventListener('click', async () => {
  if (!await confirmDialog({message: 'Regenerate the token? Webhooks already installed will stop working until you reinstall them.', confirmLabel: 'Regenerate the token', danger: true})) return;
  try {
    await api('/api/integration/token', {method: 'POST', body: '{}'});
    notice('Token regenerated: reinstall the webhook in Radarr and Sonarr.');
    await refreshIntegration();
  } catch (error) {
    notice(error.message, true);
  }
});
// =================================================


// ======================== COPIE DE L'ADRESSE ========================

// Copie sans l'API moderne (page en http:// où elle est bloquée), via un champ caché dans la page
function copyWithFallback(text) {
  const area = document.createElement('textarea');
  area.value = text;
  area.setAttribute('readonly', '');
  area.style.cssText = 'position:fixed;top:0;left:0;opacity:0';
  document.body.append(area);
  area.focus();
  area.select();
  let copied = false;
  try {
    copied = document.execCommand('copy');
  } finally {
    area.parentNode.removeChild(area);
  }
  if (!copied) throw new Error('copy refused');
}

$('#integrationCopy').addEventListener('click', async () => {
  const button = $('#integrationCopy');
  try {
    await refreshIntegration();
    const text = integrationWebhookUrl;
    if (!text) throw new Error('address unavailable');
    if (navigator.clipboard && window.isSecureContext) await navigator.clipboard.writeText(text);
    else copyWithFallback(text);
    button.original = button.original || [...button.childNodes];  // garde le texte d'origine
    withIcon(button, 'check', 'Copied');
    button.classList.add('copied');
    clearTimeout(button.copiedTimer);
    button.copiedTimer = setTimeout(() => {
      button.replaceChildren(...button.original);
      button.classList.remove('copied');
    }, 2000);
  } catch (error) {
    notice('Copy failed: ' + error.message, true);
  }
});
// =================================================
