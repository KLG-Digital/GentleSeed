// ======================== SYSTÈME : SAUVEGARDES ========================

// Liste des sauvegardes avec télécharger, restaurer et supprimer
async function loadBackups() {
  const data = await api('/api/backups');
  const body = $('#backupRows');
  body.replaceChildren();
  if (!data.items.length) {
    const row = element('tr');
    const cell = element('td', '', 'No backup yet.');
    cell.colSpan = 5;
    row.append(cell);
    body.append(row);
  }
  for (const item of data.items) {
    const row = element('tr');
    row.append(dataElement('td', '', item.name), element('td', '', item.created ? dateTime(item.created) : '—'),
               element('td', '', formatFileSize(item.size)), element('td', '', item.includes_keys ? 'Included' : 'No'));
    const actions = element('td', 'task-actions');
    const download = element('a', 'button button-subtle', 'Download');
    download.href = 'api/backups/' + encodeURIComponent(item.name);
    download.download = item.name;
    const restore = element('button', 'button button-subtle', 'Restore');
    restore.type = 'button';
    restore.addEventListener('click', () => restoreBackup({name: item.name}, item.name));
    const remove = element('button', 'button button-subtle', 'Delete');
    remove.type = 'button';
    remove.addEventListener('click', async () => {
      if (!await confirmDialog({message: `Delete the backup ${item.name}?`, confirmLabel: 'Delete', danger: true})) return;
      try {
        await api('/api/backups/' + encodeURIComponent(item.name) + '/delete', {method: 'POST', body: '{}'});
        await loadBackups();
      } catch (error) {
        notice(error.message, true);
      }
    });
    actions.append(download, restore, remove);
    row.append(actions);
    body.append(row);
  }
  $('#backupFooter').textContent = `The last ${data.keep} backups are kept in the data folder, plus the last ${data.keep_safety} safety copies made before a restore (pre-restore).`;
}

// Restaure une sauvegarde du dossier ({name}) ou un fichier importé ({content}) ; le serveur fait d'abord une copie de sécurité
async function restoreBackup(payload, label) {
  if (!await confirmDialog({message: `Restore "${label}"? Your current settings will be replaced. A safety copy is created just before.`, confirmLabel: 'Restore'})) return;
  try {
    const result = await api('/api/backups/restore', {method: 'POST', body: JSON.stringify(payload)});
    if (result.cleared?.length) {
      notice(`Settings restored. Enter the API key again for ${result.cleared.join(', ')}. Safety copy: ${result.safety}`, true);
    } else {
      notice('Settings restored. Safety copy: ' + result.safety);
    }
    await refreshSettings().catch(() => {});
    await refreshStatus().catch(() => {});
    await loadBackups();
  } catch (error) {
    notice(error.message, true);
  }
}
// =================================================


// ======================== CRÉER ET IMPORTER ========================
$('#backupCreate').addEventListener('click', async () => {
  const button = $('#backupCreate');
  const keys = $('#backupKeys').checked;
  if (keys && !await confirmDialog({message: 'The file will contain your API keys and give access to Radarr and Sonarr. Continue?'})) return;
  button.disabled = true;
  try {
    const result = await api('/api/backups', {method: 'POST', body: JSON.stringify({include_keys: keys})});
    notice('Backup created: ' + result.name);
    await loadBackups();
  } catch (error) {
    notice(error.message, true);
  } finally {
    button.disabled = false;
  }
});

$('#backupImport').addEventListener('click', () => $('#backupFile').click());

$('#backupFile').addEventListener('change', async event => {
  const file = event.target.files[0];
  event.target.value = '';
  if (!file) return;
  if (file.size > 1000000) {
    notice('File too large (1 MB maximum).', true);
    return;
  }
  let content;
  try {
    content = JSON.parse(await file.text());
  } catch (_) {
    notice('This file is not valid JSON.', true);
    return;
  }
  await restoreBackup({content}, file.name);
});
// =================================================
