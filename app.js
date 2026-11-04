const messages = [];
const conversation = document.querySelector('#conversation');
const form = document.querySelector('#chat-form');
const input = document.querySelector('#message');
const sendButton = document.querySelector('#send');
const statusLine = document.querySelector('#chat-status');

function safeAnswer(parent, text) {
  // Render plain text and links without inserting model output as HTML.
  const pattern = /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)|(https?:\/\/[^\s<>]+)/g;
  let cursor = 0;
  for (const match of text.matchAll(pattern)) {
    const index = match.index;
    if (index > cursor) parent.append(document.createTextNode(text.slice(cursor, index)));
    const label = match[1] || match[3];
    const href = match[2] || match[3];
    const link = document.createElement('a');
    link.href = href.replace(/[.,!?;:]$/, '');
    link.textContent = label.replace(/[.,!?;:]$/, '');
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    parent.append(link);
    if (/[.,!?;:]$/.test(label)) parent.append(document.createTextNode(label.slice(-1)));
    cursor = index + match[0].length;
  }
  if (cursor < text.length) parent.append(document.createTextNode(text.slice(cursor)));
}

function addBubble(role, text, pending = false) {
  const row = document.createElement('div');
  row.className = `message-row ${role}`;
  const bubble = document.createElement('div');
  bubble.className = 'bubble';
  if (pending) {
    bubble.classList.add('thinking');
    bubble.textContent = 'Thinking';
  } else if (role === 'assistant') {
    safeAnswer(bubble, text);
  } else {
    bubble.textContent = text;
  }
  row.append(bubble);
  conversation.append(row);
  conversation.scrollTop = conversation.scrollHeight;
  return row;
}

function removeEmptyState() {
  conversation.querySelector('.empty-state')?.remove();
}

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  const content = input.value.trim();
  if (!content || sendButton.disabled) return;
  removeEmptyState();
  messages.push({ role: 'user', content });
  addBubble('user', content);
  input.value = '';
  input.style.height = 'auto';
  sendButton.disabled = true;
  statusLine.textContent = '';
  const pending = addBubble('assistant', '', true);
  try {
    const response = await fetch('/api/chat', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ messages })
    });
    const result = await response.json();
    pending.remove();
    if (!response.ok) throw new Error(result.error || 'The request failed.');
    messages.push({ role: 'assistant', content: result.answer });
    addBubble('assistant', result.answer);
  } catch (error) {
    pending.remove();
    addBubble('assistant', error.message);
    statusLine.textContent = 'Could not complete that request.';
  } finally {
    sendButton.disabled = false;
    input.focus();
  }
});

input.addEventListener('input', () => {
  input.style.height = 'auto';
  input.style.height = `${Math.min(input.scrollHeight, 140)}px`;
});
input.addEventListener('keydown', (event) => {
  if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); form.requestSubmit(); }
});
document.querySelector('#clear-chat').addEventListener('click', () => {
  messages.length = 0;
  conversation.replaceChildren();
  const empty = document.createElement('div');
  empty.className = 'empty-state';
  empty.innerHTML = '<div class="spark">✳</div><p>Ask Gemma anything to get started.</p><span>Your uploaded documents can help answer questions, too.</span>';
  conversation.append(empty);
  statusLine.textContent = '';
  input.focus();
});

const tabs = [...document.querySelectorAll('.tab')];
tabs.forEach((tab) => tab.addEventListener('click', () => {
  tabs.forEach((item) => item.classList.toggle('active', item === tab));
  document.querySelector('#chat-view').classList.toggle('hidden', tab.dataset.view !== 'chat');
  document.querySelector('#documents-view').classList.toggle('hidden', tab.dataset.view !== 'documents');
  if (tab.dataset.view === 'documents') loadDocuments();
}));

const fileInput = document.querySelector('#file');
fileInput.addEventListener('change', () => {
  document.querySelector('#file-name').textContent = fileInput.files[0]?.name || 'No file chosen';
});

async function loadDocuments() {
  const list = document.querySelector('#file-list');
  try {
    const response = await fetch('/api/documents');
    const files = await response.json();
    if (!response.ok) throw new Error(files.error || 'Could not load files.');
    document.querySelector('#nav-count').textContent = files.length;
    document.querySelector('#file-total').textContent = `${files.length} ${files.length === 1 ? 'file' : 'files'}`;
    document.querySelector('#no-files').classList.toggle('hidden', files.length > 0);
    list.replaceChildren();
    for (const file of files) {
      const item = document.createElement('li');
      item.className = 'file-item';
      const icon = document.createElement('span'); icon.className = 'file-icon'; icon.textContent = file.name.toLowerCase().endsWith('.pdf') ? 'PDF' : 'TXT';
      const info = document.createElement('div'); info.className = 'file-info';
      const name = document.createElement('strong'); name.textContent = file.name;
      const size = document.createElement('span'); size.textContent = formatSize(file.size);
      info.append(name, size);
      const remove = document.createElement('button'); remove.className = 'delete-button'; remove.textContent = 'Delete'; remove.type = 'button';
      remove.addEventListener('click', async () => {
        remove.disabled = true;
        const result = await fetch(`/api/documents/${encodeURIComponent(file.id)}`, { method: 'DELETE' });
        if (result.ok) loadDocuments(); else { remove.disabled = false; showUploadStatus('Could not delete that file.', true); }
      });
      item.append(icon, info, remove); list.append(item);
    }
  } catch (error) { showUploadStatus(error.message, true); }
}

function formatSize(bytes) {
  return bytes < 1024 * 1024 ? `${Math.max(1, Math.round(bytes / 1024))} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}
function showUploadStatus(text, error = false) {
  const status = document.querySelector('#upload-status');
  status.textContent = text;
  status.classList.toggle('error', error);
}
document.querySelector('#upload-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  if (!fileInput.files.length) { showUploadStatus('Choose a file first.', true); return; }
  const button = event.currentTarget.querySelector('button');
  button.disabled = true; showUploadStatus('Uploading…');
  try {
    const data = new FormData(); data.append('file', fileInput.files[0]);
    const response = await fetch('/api/documents', { method: 'POST', body: data });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Upload failed.');
    fileInput.value = ''; document.querySelector('#file-name').textContent = 'No file chosen';
    showUploadStatus(`Uploaded ${result.name}.`); await loadDocuments();
  } catch (error) { showUploadStatus(error.message, true); }
  finally { button.disabled = false; }
});

loadDocuments();
