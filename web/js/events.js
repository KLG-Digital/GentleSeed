// ======================== TABLEAU DES ÉVÉNEMENTS ========================

// Cellule du tableau pour une colonne donnée
function eventCell(event, key) {
  if (key === 'level') {
    const cell = element('td');
    cell.append(element('span', 'log-badge ' + event.level, event.level));
    return cell;
  }
  if (key === 'time') return element('td', '', dateTime(event.time));
  if (key === 'component') return element('td', '', event.component || 'GentleSeed');
  if (key === 'message') {
    const cell = element('td', 'event-message');
    cell.append(messageNode(event.message));
    return cell;
  }
  if (key === 'actions') {
    const cell = element('td');
    const button = element('button', 'event-detail-button', 'Details');
    button.type = 'button';
    button.addEventListener('click', click => {
      click.stopPropagation();
      showEventDetails(event);
    });
    cell.append(button);
    return cell;
  }
  return element('td', '', '—');
}

// Tableau filtré par la recherche, du plus récent au plus ancien, avec pagination
function renderEventsTable() {
  const tbody = $('#eventRows');
  const thead = $('#eventHead');
  if (!tbody || !thead) return;
  tbody.replaceChildren();
  thead.replaceChildren();
  const columns = activeColumns('events');
  const head = element('tr');
  for (const key of columns) {
    const label = tr(tableDefinition.events.find(([name]) => name === key)[1]);
    head.append(element('th', '', label.toLocaleUpperCase(selectedLocale())));
  }
  thead.append(head);
  const query = ($('#logsearch')?.value || '').trim().toLocaleLowerCase();
  const events = [...lastEvents].reverse().filter(event => !query
    || [event.message, event.component, event.level].some(part => String(part || '').toLocaleLowerCase().includes(query)));
  const state = tableState.events;
  const start = state.page * state.pageSize;
  for (const event of events.slice(start, start + state.pageSize)) {
    const row = element('tr', 'event-row');
    row.tabIndex = 0;
    row.title = 'Show details';
    columns.forEach(key => row.append(eventCell(event, key)));
    row.addEventListener('click', () => showEventDetails(event));
    row.addEventListener('keydown', keyEvent => {
      if (keyEvent.key === 'Enter' || keyEvent.key === ' ') {
        keyEvent.preventDefault();
        showEventDetails(event);
      }
    });
    tbody.append(row);
  }
  if (!events.length) {
    const row = element('tr');
    const cell = element('td', 'empty', 'No events');
    cell.colSpan = columns.length;
    row.append(cell);
    tbody.append(row);
  }
  tablePager('events', events.length, $('#eventPager'));
}

$('#logsearch').addEventListener('input', () => {
  tableState.events.page = 0;
  renderEventsTable();
});
// =================================================
