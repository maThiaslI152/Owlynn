/**
 * KnowledgeMap — IIFE module for the right-column knowledge panel.
 * Displays project-scoped learned facts from memory context and topics.
 *
 * Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7, 9.8
 */
window.KnowledgeMap = (() => {
  // ── State ──
  let entries = [];
  let expandedEntries = new Set();
  let containerEl = null;

  // ── Helpers ──
  function _escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  function _formatTime(ts) {
    if (!ts) return '';
    try {
      const d = new Date(typeof ts === 'number' ? ts * 1000 : ts);
      if (isNaN(d.getTime())) return '';
      const now = Date.now();
      const diff = now - d.getTime();
      if (diff < 60000) return 'just now';
      if (diff < 3600000) return Math.floor(diff / 60000) + 'm ago';
      if (diff < 86400000) return Math.floor(diff / 3600000) + 'h ago';
      return d.toLocaleDateString();
    } catch (_) { return ''; }
  }

  // ── Parse memory context string into entries ──
  function _parseMemoryContext(text) {
    if (!text || typeof text !== 'string') return [];
    const sections = [];
    const lines = text.split('\n');
    let current = null;

    for (const line of lines) {
      if (line.startsWith('## ')) {
        if (current) sections.push(current);
        current = { id: 'mem_' + sections.length, title: line.replace(/^##\s*/, '').trim(), content: '', timestamp: null, source: 'memory' };
      } else if (current) {
        current.content += (current.content ? '\n' : '') + line;
      }
    }
    if (current) sections.push(current);

    // Trim content
    sections.forEach(s => { s.content = s.content.trim(); });
    return sections.filter(s => s.content.length > 0);
  }

  // ── Parse topics into entries ──
  function _parseTopics(topics) {
    if (!Array.isArray(topics)) return [];
    return topics.map((t, i) => {
      const category = Array.isArray(t) ? t[0] : (t.category || 'Topic');
      const name = Array.isArray(t) ? t[1] : (t.name || String(t));
      return { id: 'topic_' + i, title: String(category), content: String(name), timestamp: null, source: 'topic' };
    });
  }

  // ── API ──
  async function _fetchEntries(projectId) {
    const pid = projectId || StateManager.activeProjectId || 'default';
    const results = [];

    try {
      const res = await fetch(API_BASE + '/api/memory-context');
      if (res.ok) {
        const data = await res.json();
        if (data.memory_context) {
          results.push(..._parseMemoryContext(data.memory_context));
        }
      }
    } catch (_) { /* skip */ }

    try {
      const res = await fetch(API_BASE + '/api/topics');
      if (res.ok) {
        const data = await res.json();
        if (data.topics) {
          results.push(..._parseTopics(data.topics));
        }
      }
    } catch (_) { /* skip */ }

    return results;
  }

  // ── Rendering ──
  function renderEntries(entryList) {
    if (!containerEl) return;
    containerEl.innerHTML = '';

    if (!entryList || entryList.length === 0) {
      containerEl.innerHTML = '<div class="knowledge-empty">No knowledge yet</div>';
      return;
    }

    entryList.forEach(entry => {
      const isExpanded = expandedEntries.has(entry.id);
      const el = document.createElement('div');
      el.className = 'knowledge-entry' + (isExpanded ? ' expanded' : '');
      el.dataset.entryId = entry.id;

      const timeStr = _formatTime(entry.timestamp);
      const preview = entry.content.length > 120 && !isExpanded
        ? entry.content.substring(0, 120) + '…'
        : entry.content;

      el.innerHTML =
        '<div class="knowledge-title">' + _escapeHtml(entry.title) + '</div>' +
        '<div class="knowledge-preview">' + _escapeHtml(preview) + '</div>' +
        (timeStr ? '<div class="knowledge-time">' + _escapeHtml(timeStr) + '</div>' : '') +
        '<div class="knowledge-actions">' +
          '<button class="knowledge-delete-btn" title="Delete">✕</button>' +
        '</div>';

      // Expand on click
      el.addEventListener('click', (e) => {
        if (e.target.closest('.knowledge-delete-btn')) return;
        expandEntry(entry.id);
      });

      // Delete button
      el.querySelector('.knowledge-delete-btn').addEventListener('click', (e) => {
        e.stopPropagation();
        deleteEntry(StateManager.activeProjectId || 'default', entry.title);
      });

      containerEl.appendChild(el);
    });
  }

  // ── Actions ──
  function expandEntry(entryId) {
    if (expandedEntries.has(entryId)) {
      expandedEntries.delete(entryId);
    } else {
      expandedEntries.add(entryId);
    }
    renderEntries(entries);
  }

  async function deleteEntry(projectId, entryName) {
    const pid = projectId || 'default';
    try {
      const res = await fetch(
        API_BASE + '/api/projects/' + encodeURIComponent(pid) + '/knowledge/' + encodeURIComponent(entryName),
        { method: 'DELETE' }
      );
      if (res.ok) {
        entries = entries.filter(e => e.title !== entryName);
        renderEntries(entries);
      }
    } catch (err) {
      // delete error silenced
    }
  }

  async function refresh(projectId) {
    expandedEntries.clear();
    entries = await _fetchEntries(projectId);
    renderEntries(entries);
  }

  function handleMemoryUpdate() {
    refresh(StateManager.activeProjectId);
  }

  // ── Init ──
  function init() {
    containerEl = document.getElementById('knowledgeEntries');
    if (!containerEl) {
      return;
    }

    // Subscribe to project changes
    StateManager.subscribe('KnowledgeMap', (changedKeys) => {
      if (changedKeys.includes('activeProjectId')) {
        refresh(StateManager.activeProjectId);
      }
    });

    // Initial load
    refresh(StateManager.activeProjectId);
  }

  // ── Public API ──
  return {
    init,
    refresh,
    renderEntries,
    expandEntry,
    deleteEntry,
    handleMemoryUpdate,
  };
})();
