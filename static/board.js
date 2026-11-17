
const columns = [...document.querySelectorAll('[data-status]')];
const feedback = document.querySelector('#feedback');
const connection = document.querySelector('#connection');
const search = document.querySelector('#search');
const channel = document.querySelector('#channel');
const priorityFilter = document.querySelector('#priority-filter');
const sortOrder = document.querySelector('#sort-order');
const ageFilter = document.querySelector('#age-filter');
const agentFilter = document.querySelector('#agent-filter');
const stateFilter = document.querySelector('#state-filter');
const filters = [search, channel, priorityFilter, agentFilter, ageFilter, stateFilter, sortOrder];
let savedAgentFilter = '';
const agingThreshold = 24 * 60 * 60 * 1000;
const filterKey = 'support-board-filters';

function restoreFilters() {
  if (/^#ticket-[0-9]+$/.test(location.hash)) return;
  try {
    const saved = JSON.parse(sessionStorage.getItem(filterKey) ?? '{}');
    for (const field of filters) {
      const value = saved?.[field.id];
      if (typeof value !== 'string') continue;
      if (field === agentFilter) {
        savedAgentFilter = value;
        continue;
      }
      if (field instanceof HTMLSelectElement && ![...field.options].some(option => option.value === value)) continue;
      field.value = value;
    }
  } catch {
    // Storage can be unavailable in restricted browser contexts.
  }
}

function saveFilters() {
  try {
    const values = Object.fromEntries(filters.map(field => [field.id, field.value]));
    values[agentFilter.id] = savedAgentFilter || agentFilter.value;
    sessionStorage.setItem(filterKey, JSON.stringify(values));
  } catch {
    // Filters remain usable without session storage.
  }
}

function clearFilters() {
  search.value = '';
  channel.value = '';
  priorityFilter.value = '';
  ageFilter.value = '';
  stateFilter.value = '';
  savedAgentFilter = '';
  agentFilter.value = '';
  saveFilters();
}

const priorityRank = {urgent: 0, high: 1, normal: 2};
const dateFormat = new Intl.DateTimeFormat('az', {dateStyle: 'medium', timeStyle: 'short'});
const channelNames = {telegram: 'Telegram', whatsapp: 'WhatsApp', email: 'E-poçt', manual: 'Əl ilə'};
const priorityNames = {normal: 'Normal', high: 'Yüksək', urgent: 'Təcili'};
const channelSummary = document.querySelector('#channel-summary');
const channelButtons = new Map();
for (const [value, name] of Object.entries(channelNames)) {
  const button = document.createElement('button');
  button.type = 'button';
  button.textContent = name + ' · —';
  button.setAttribute('aria-pressed', 'false');
  button.addEventListener('click', () => {
    const active = channel.value === value && stateFilter.value === 'open';
    channel.value = active ? '' : value;
    stateFilter.value = active ? '' : 'open';
    channel.dispatchEvent(new Event('change'));
  });
  channelButtons.set(value, button);
  channelSummary.append(button);
}
let previous = '';
let currentTickets = [];
const openHistories = new Set();
const noteDrafts = new Map();
const assignmentDrafts = new Map();
let pending = false;
let pollDelay = 2000;

function setConnection(online) {
  const state = online ? 'online' : 'offline';
  if (connection.dataset.state === state) return;
  connection.dataset.state = state;
  connection.textContent = online ? 'Serverə qoşulub' : 'Bağlantı yoxdur · yenidən yoxlanılır';
}

function showError(message) {
  feedback.textContent = message;
  feedback.hidden = !message;
}

const createDialog = document.querySelector('#create-dialog');
const createError = document.querySelector('#create-error');
const toast = document.querySelector('#toast');
let toastTimer;

document.querySelector('#open-create').addEventListener('click', () => {
  createError.hidden = true;
  createDialog.showModal();
});
document.querySelector('#cancel-create').addEventListener('click', () => {
  if (!pending) createDialog.close();
});
createDialog.addEventListener('cancel', event => {
  if (pending) event.preventDefault();
});

function notify(message) {
  clearTimeout(toastTimer);
  toast.hidden = false;
  toast.textContent = message;
  toastTimer = setTimeout(() => { toast.hidden = true; }, 3500);
}

document.querySelector('#new-ticket').addEventListener('submit', async event => {
  event.preventDefault();
  if (pending) return;
  const form = event.currentTarget;
  const submit = form.querySelector('[type=submit]');
  createError.hidden = true;
  pending = true;
  submit.disabled = true;
  try {
    const response = await fetch('/api/tickets', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({text: form.elements.text.value})
    });
    if (!response.ok) throw new Error();
    form.reset();
    createDialog.close();
    clearFilters();
    notify('Müraciət yaradıldı.');
  } catch {
    createError.textContent = 'Müraciəti yaratmaq mümkün olmadı.';
    createError.hidden = false;
    return;
  } finally {
    pending = false;
    submit.disabled = false;
  }
  await refresh();
});

async function move(id, status) {
  if (pending) return;
  pending = true;
  try {
    const response = await fetch('/api/tickets/' + id, {
      method: 'PATCH',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({status})
    });
    if (!response.ok) throw new Error();
  } catch {
    previous = '';
    showError('Müraciətin statusunu dəyişmək mümkün olmadı.');
    return;
  } finally {
    pending = false;
  }
  await refresh();
}

for (const column of columns) {
  column.addEventListener('dragover', event => event.preventDefault());
  column.addEventListener('drop', event => {
    event.preventDefault();
    const id = event.dataTransfer.getData('text/plain');
    if (/^[0-9]+$/.test(id)) move(id, column.dataset.status);
  });
}

async function refresh() {
  if (pending) return;
  try {
    const response = await fetch('/api/tickets', {
      cache: 'no-cache',
      signal: AbortSignal.timeout(5000)
    });
    if (!response.ok) throw new Error();
    const tickets = await response.json();
    setConnection(true);
    pollDelay = 2000;
    if (pending || document.activeElement?.matches('article input, article textarea')
        || document.querySelector('article details form button:disabled')) return;
    updateMetrics(tickets);
    const snapshot = JSON.stringify(tickets.map(ticket => [ticket, isAging(ticket)]));
    if (snapshot === previous) return;
    previous = snapshot;
    const firstLoad = currentTickets.length === 0;
    currentTickets = tickets;
    updateAgentOptions(tickets);
    renderTickets();
    if (firstLoad) openLinkedTicket();
    showError('');
  } catch {
    setConnection(false);
    pollDelay = Math.min(pollDelay * 2, 15000);
  }
}
function isAging(ticket) {
  if (ticket.status === 'Resolved' || !ticket.received_at) return false;
  const received = Date.parse(ticket.received_at.replace(' ', 'T') + 'Z');
  return Date.now() - received >= agingThreshold;
}

function updateAgentOptions(tickets) {
  const selected = savedAgentFilter || agentFilter.value;
  savedAgentFilter = '';
  const names = new Set(tickets.map(ticket => ticket.agent).filter(Boolean));
  if (selected.startsWith('agent:')) names.add(selected.slice(6));
  agentFilter.replaceChildren(
    new Option('Bütün agentlər', ''),
    new Option('Təyin edilməyib', 'unassigned'),
    ...[...names].sort((a, b) => a.localeCompare(b, 'az')).map(name => new Option(name, 'agent:' + name))
  );
  agentFilter.value = selected;
}

function matchesAgent(ticket, selected) {
  if (!selected) return true;
  return selected === 'unassigned' ? !ticket.agent : 'agent:' + ticket.agent === selected;
}

function resolutionMinutes(ticket) {
  if (!ticket.received_at || !ticket.resolved_at) return null;
  const parse = value => Date.parse(value.replace(' ', 'T') + 'Z');
  const minutes = (parse(ticket.resolved_at) - parse(ticket.received_at)) / 60000;
  return Number.isFinite(minutes) && minutes >= 0 ? minutes : null;
}

function formatDuration(minutes) {
  const rounded = Math.floor(minutes);
  if (rounded < 1) return '< 1 dəq';
  const days = Math.floor(rounded / 1440);
  const hours = Math.floor((rounded % 1440) / 60);
  if (days) return days + ' gün ' + hours + ' saat';
  return hours ? hours + ' saat ' + (rounded % 60) + ' dəq' : rounded + ' dəq';
}

function updateMetrics(tickets) {
  const open = tickets.filter(ticket => ticket.status !== 'Resolved');
  const counts = new Map();
  for (const ticket of open) counts.set(ticket.channel, (counts.get(ticket.channel) ?? 0) + 1);
  for (const [value, button] of channelButtons) {
    button.textContent = channelNames[value] + ' · ' + (counts.get(value) ?? 0);
  }
  document.querySelector('#metric-open').textContent = open.length;
  document.querySelector('#metric-unassigned').textContent = open.filter(ticket => !ticket.agent).length;
  document.querySelector('#metric-urgent').textContent =
    open.filter(ticket => ticket.priority === 'urgent').length;
  document.querySelector('#metric-aging').textContent = open.filter(isAging).length;
  document.querySelector('#metric-resolved').textContent = tickets.length - open.length;
  const durations = tickets.map(resolutionMinutes).filter(value => value !== null).sort((a, b) => a - b);
  const middle = Math.floor(durations.length / 2);
  const median = durations.length % 2
    ? durations[middle]
    : (durations[middle - 1] + durations[middle]) / 2;
  document.querySelector('#metric-median').textContent = durations.length ? formatDuration(median) : '—';
}

function visibleTickets() {
  const query = search.value.trim().toLocaleLowerCase('az');
  const number = /^#?([0-9]+)$/.exec(query);
  const matches = currentTickets.filter(ticket => {
    const text = [ticket.body, ticket.agent].join(' ').toLocaleLowerCase('az');
    return (!channel.value || ticket.channel === channel.value)
      && (!priorityFilter.value || ticket.priority === priorityFilter.value)
      && (!ageFilter.value || isAging(ticket))
      && (!stateFilter.value || (ticket.status === 'Resolved') === (stateFilter.value === 'resolved'))
      && matchesAgent(ticket, agentFilter.value)
      && (number ? String(ticket.id) === number[1] || (!query.startsWith('#') && text.includes(query)) : text.includes(query));
  });
  if (sortOrder.value === 'oldest') {
    matches.sort((a, b) => priorityRank[a.priority] - priorityRank[b.priority] || a.id - b.id);
  }
  return matches;
}

document.querySelector('#export').addEventListener('click', () => {
  const escapeCell = value => {
    const text = String(value ?? '');
    const safe = /^[=+@-]/.test(text.trimStart()) || /^[\t\r\n]/.test(text) ? "'" + text : text;
    return '"' + safe.replaceAll('"', '""') + '"';
  };
  const rows = [
    ['ID', 'Kanal', 'Müraciət', 'Status', 'Təyinat', 'Prioritet', 'Qəbul vaxtı (UTC)', 'Həll vaxtı (UTC)'],
    ...visibleTickets().map(ticket => [
      ticket.id, channelNames[ticket.channel], ticket.body, ticket.status, ticket.agent, priorityNames[ticket.priority], ticket.received_at, ticket.resolved_at
    ]),
  ];
  const csv = rows.map(row => row.map(escapeCell).join(',')).join('\r\n');
  const url = URL.createObjectURL(new Blob(['\uFEFF', csv], {type: 'text/csv;charset=utf-8'}));
  const link = document.createElement('a');
  link.href = url;
  link.download = 'muracietler.csv';
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});

function renderTickets() {
  for (const [value, button] of channelButtons) {
    button.setAttribute('aria-pressed', String(channel.value === value && stateFilter.value === 'open'));
  }
  for (const column of columns) column.querySelector('.tickets').replaceChildren();
  for (const ticket of visibleTickets()) {
    const column = columns.find(element => element.dataset.status === ticket.status);
    const card = document.createElement('article');
    card.id = 'ticket-' + ticket.id;
    card.draggable = true;
    card.dataset.priority = ticket.priority;
    card.addEventListener('dragstart', event => {
      event.dataTransfer.setData('text/plain', String(ticket.id));
    });
    const number = document.createElement('a');
    number.className = 'ticket-number';
    number.href = '#' + card.id;
    number.textContent = '#' + ticket.id;
    number.setAttribute('aria-label', 'Müraciət ' + ticket.id + ' üçün birbaşa keçid');
    const meta = document.createElement('small');
    meta.textContent = [channelNames[ticket.channel], ticket.agent].filter(Boolean).join(' · ');
    const body = document.createElement('p');
    body.textContent = ticket.body;
    const select = document.createElement('select');
    select.setAttribute('aria-label', 'Müraciət ' + ticket.id + ' üçün status');
    for (const target of columns) {
      select.add(new Option(target.querySelector('h2').firstChild.textContent.trim(), target.dataset.status));
    }
    select.value = ticket.status;
    select.addEventListener('change', () => {
      const status = select.value;
      select.value = ticket.status;
      move(ticket.id, status);
    });
    const copy = document.createElement('button');
    copy.type = 'button';
    copy.textContent = 'Mətni kopyala';
    copy.addEventListener('click', async () => {
      try {
        await navigator.clipboard.writeText(ticket.body);
        copy.textContent = 'Kopyalandı';
      } catch {
        showError('Mətni kopyalamaq mümkün olmadı.');
      }
    });
    const assignment = document.createElement('form');
    const label = document.createElement('label');
    label.textContent = 'Agent';
    const agent = document.createElement('input');
    agent.maxLength = 100;
    agent.value = assignmentDrafts.get(ticket.id) ?? ticket.agent ?? '';
    agent.addEventListener('input', () => {
      if (agent.value === (ticket.agent ?? '')) assignmentDrafts.delete(ticket.id);
      else assignmentDrafts.set(ticket.id, agent.value);
    });
    agent.placeholder = 'Təyin edilməyib';
    label.append(agent);
    const save = document.createElement('button');
    save.textContent = 'Təyinatı saxla';
    assignment.append(label, save);
    assignment.addEventListener('submit', async event => {
      event.preventDefault();
      if (pending) return;
      pending = true;
      save.disabled = true;
      try {
        const response = await fetch('/api/tickets/' + ticket.id + '/assignment', {
          method: 'PUT',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({agent: agent.value})
        });
        if (!response.ok) throw new Error();
        assignmentDrafts.delete(ticket.id);
        previous = '';
      } catch {
        showError('Təyinatı saxlamaq mümkün olmadı.');
        return;
      } finally {
        pending = false;
        save.disabled = false;
      }
      agent.blur();
      await refresh();
    });
    const priorityLabel = document.createElement('label');
    priorityLabel.textContent = 'Prioritet';
    const priority = document.createElement('select');
    for (const [value, name] of Object.entries(priorityNames)) {
      priority.add(new Option(name, value));
    }
    priority.value = ticket.priority;
    priorityLabel.append(priority);
    priority.addEventListener('change', async () => {
      const value = priority.value;
      priority.value = ticket.priority;
      if (pending) return;
      pending = true;
      priority.disabled = true;
      try {
        const response = await fetch('/api/tickets/' + ticket.id + '/priority', {
          method: 'PUT',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({priority: value})
        });
        if (!response.ok) throw new Error();
      } catch {
        showError('Prioriteti dəyişmək mümkün olmadı.');
        return;
      } finally {
        pending = false;
        priority.disabled = false;
      }
      await refresh();
    });
    const history = document.createElement('details');
    const summary = document.createElement('summary');
    summary.textContent = 'Tarixçə';
    const activity = document.createElement('div');
    activity.setAttribute('role', 'status');
    const noteForm = document.createElement('form');
    const noteLabel = document.createElement('label');
    noteLabel.textContent = 'Daxili qeyd';
    const note = document.createElement('textarea');
    note.maxLength = 1000;
    note.required = true;
    note.rows = 2;
    note.value = noteDrafts.get(ticket.id) ?? '';
    note.addEventListener('input', () => {
      if (note.value) noteDrafts.set(ticket.id, note.value);
      else noteDrafts.delete(ticket.id);
    });
    noteLabel.append(note);
    const addNote = document.createElement('button');
    addNote.textContent = 'Qeydi əlavə et';
    const noteFeedback = document.createElement('span');
    noteFeedback.setAttribute('role', 'status');
    noteForm.append(noteLabel, addNote, noteFeedback);
    history.append(summary, activity, noteForm);

    async function loadHistory() {
      activity.textContent = 'Yüklənir…';
      try {
        const response = await fetch('/api/tickets/' + ticket.id + '/events');
        if (!response.ok) throw new Error();
        const events = await response.json();
        if (!events.length) {
          activity.textContent = 'Tarixçə boşdur.';
          return;
        }
        const list = document.createElement('ul');
        for (const event of events) {
          const item = document.createElement('li');
          const status = columns.find(target => target.dataset.status === event.detail);
          const label = {
            received: 'Qəbul edildi · ' + channelNames[event.detail],
            assignment: event.detail ? 'Təyinat · ' + event.detail : 'Təyinat silindi',
            note: 'Qeyd · ' + event.detail,
            priority: 'Prioritet · ' + priorityNames[event.detail],
            status: status ? status.querySelector('h2').firstChild.textContent.trim() : event.detail
          }[event.kind];
          const date = new Date(event.recorded_at.replace(' ', 'T') + 'Z');
          item.textContent = label + ' · ' + date.toLocaleString('az');
          list.append(item);
        }
        activity.replaceChildren(list);
      } catch {
        activity.textContent = 'Tarixçəni yükləmək mümkün olmadı.';
      }
    }
    history.addEventListener('toggle', () => {
      if (!history.isConnected) return;
      if (history.open) {
        openHistories.add(ticket.id);
        loadHistory();
      } else {
        openHistories.delete(ticket.id);
      }
    });
    history.open = openHistories.has(ticket.id);
    noteForm.addEventListener('submit', async event => {
      event.preventDefault();
      if (!note.value.trim()) {
        noteFeedback.textContent = 'Qeyd boş ola bilməz.';
        return;
      }
      addNote.disabled = true;
      note.readOnly = true;
      try {
        const response = await fetch('/api/tickets/' + ticket.id + '/notes', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({text: note.value})
        });
        if (!response.ok) throw new Error();
        noteDrafts.delete(ticket.id);
        noteForm.reset();
        noteFeedback.textContent = 'Qeyd saxlanıldı.';
        await loadHistory();
      } catch {
        noteFeedback.textContent = 'Qeydi saxlamaq mümkün olmadı.';
      } finally {
        addNote.disabled = false;
        note.readOnly = false;
      }
    });
    card.append(number, meta);
    if (ticket.received_at) {
      const received = document.createElement('time');
      received.dateTime = ticket.received_at.replace(' ', 'T') + 'Z';
      received.textContent = dateFormat.format(new Date(received.dateTime));
      card.append(received);
    }
    const minutes = resolutionMinutes(ticket);
    if (minutes !== null) {
      const duration = document.createElement('small');
      duration.textContent = 'Həll müddəti · ' + formatDuration(minutes);
      card.append(duration);
    }
    if (isAging(ticket)) {
      const aging = document.createElement('span');
      aging.className = 'aging';
      aging.textContent = '24 saatdan çox açıq';
      card.append(aging);
    }
    card.append(body, select, priorityLabel, assignment, copy, history);
    column.querySelector('.tickets').append(card);
  }
  for (const column of columns) {
    const cards = column.querySelector('.tickets');
    column.querySelector('.count').textContent = cards.childElementCount;
    if (cards.childElementCount === 0) {
      const empty = document.createElement('p');
      empty.className = 'empty';
      empty.textContent = 'Müraciət yoxdur';
      cards.append(empty);
    }
  }
}
for (const field of filters) {
  field.addEventListener(field === search ? 'input' : 'change', () => {
    if (field === agentFilter) savedAgentFilter = '';
    saveFilters();
    renderTickets();
  });
}
document.querySelector('#clear-filters').addEventListener('click', () => {
  clearFilters();
  renderTickets();
  search.focus();
});

function openLinkedTicket() {
  const id = /^#ticket-([0-9]+)$/.exec(location.hash);
  if (!id) return;
  const card = document.getElementById('ticket-' + id[1]);
  if (card) card.scrollIntoView({block: 'nearest'});
}
window.addEventListener('hashchange', () => {
  if (!/^#ticket-[0-9]+$/.test(location.hash)) return;
  if (!document.getElementById(location.hash.slice(1))) {
    clearFilters();
    renderTickets();
  }
  openLinkedTicket();
});

async function poll() {
  await refresh();
  setTimeout(poll, pollDelay);
}
restoreFilters();
poll();
