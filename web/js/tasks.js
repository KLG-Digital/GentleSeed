// ======================== VÉRIFICATION MANUELLE ========================

// Bouton « Check now » : demande un passage immédiat du moteur automatique
$('#scanNow').addEventListener('click', async event => {
  event.preventDefault();
  const button = $('#scanNow');
  button.disabled = true;
  try {
    const result = await api('/api/scan', {method: 'POST', body: '{}'});
    notice(result.message || 'Check requested');
  } catch (error) {
    notice(error.message, true);
  } finally {
    button.disabled = false;
  }
});
// =================================================
