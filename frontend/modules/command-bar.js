// ─── Command Bar Module ─────────────────────────────────────────────────────
// Global search overlay (Cmd+K / Ctrl+K) reusing the existing #spotlightModal.
// Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7
const CommandBar = (() => {
  let debounceTimer = null;
  const DEBOUNCE_MS = 300;

  // DOM refs (resolved on init)
  let modal, input, results;

  function init() {
    modal   = document.getElementById('spotlightModal');
    input   = document.getElementById('spotlightInput');
    results = document.getElementById('spotlightResults');
    if (!modal || !input || !results) return;

    // Keyboard shortcut: Cmd+K / Ctrl+K to open
    document.addEventListener('keydown', (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        open();
      }
      if (e.key === 'Escape' && !modal.classList.contains('hidden')) {
        e.preventDefault();
        close();
      }
    });

    // Backdrop click to close
    const backdrop = modal.querySelector('.modal-backdrop');
    if (backdrop) backdrop.addEventListener('click', close);

    // Debounced search on input
    input.addEventListener('input', () => {
      clearTimeout(debounceTimer);
      const q = input.value.trim();
      if (!q) { results.innerHTML = ''; return; }
      debounceTimer = setTimeout(() => search(q), DEBOUNCE_MS);
    });
  }

  function open() {
    if (!modal) return;
    modal.classList.remove('hidden');
    input.value = '';
    results.innerHTML = '';
    input.focus();
  }

  function close() {
    if (!modal) return;
    modal.classList.add('hidden');
    clearTimeout(debounceTimer);
    input.value = '';
    results.innerHTML = '';
  }

  async function search(query) {
    const projectId = (typeof StateManager !== 'undefined' && StateManager.activeProjectId)
      ? StateManager.activeProjectId : null;
    let url = `${typeof API_BASE !== 'undefined' ? API_BASE : ''}/api/search?q=${encodeURIComponent(query)}`;
    if (projectId) url += `&project_id=${encodeURIComponent(projectId)}`;

    try {
      const res = await fetch(url);
      if (!res.ok) throw new Error(res.statusText);
      const data = await res.json();
      const items = data.results || [];
      renderResults(items);
    } catch (_err) {
      results.innerHTML = '<div class="spotlight-item" style="color:var(--text-muted);">Search unavailable</div>';
    }
  }

  function renderResults(items) {
    results.innerHTML = '';
    if (!items.length) {
      results.innerHTML = '<div class="spotlight-item" style="color:var(--text-muted);">No results found</div>';
      return;
    }
    items.forEach((item) => {
      const btn = document.createElement('button');
      btn.className = 'spotlight-item';
      btn.type = 'button';

      const info = document.createElement('div');
      info.style.cssText = 'display:flex;flex-direction:column;gap:2px;overflow:hidden;';

      const top = document.createElement('span');
      top.style.cssText = 'font-size:0.8rem;color:var(--text-muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;';
      top.textContent = `${item.project_name || 'Unknown'} — ${item.file_path || item.file_name || ''}`;

      const snippet = document.createElement('span');
      snippet.style.cssText = 'font-size:0.82rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;';
      snippet.textContent = (item.snippet || '').replace(/\n/g, ' ').slice(0, 120);

      info.appendChild(top);
      info.appendChild(snippet);
      btn.appendChild(info);

      btn.addEventListener('click', () => insertSnippet(item));
      results.appendChild(btn);
    });
  }

  function insertSnippet(item) {
    const chatInput = document.getElementById('messageInput');
    if (!chatInput) return;
    const prefix = item.file_path || item.file_name || 'unknown';
    const content = (item.snippet || '').trim();
    const insertion = `[${prefix}]: ${content}`;
    chatInput.value += (chatInput.value ? '\n' : '') + insertion;
    chatInput.focus();
    close();
  }

  return { init, open, close, search, renderResults, insertSnippet };
})();

window.CommandBar = CommandBar;
