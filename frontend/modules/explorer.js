/**
 * Explorer — IIFE module for the left sidebar project tree with chat sub-lists.
 *
 * Consolidates the inline DOMContentLoaded renderer from index.html and the
 * ProjectVault IIFE into a single module. Delegates backend calls to existing
 * global functions in script.js (editProject, deleteProject,
 * switchChat, handleCreateProject) and uses StateManager.switchProject() for
 * project switching.
 *
 * Fixes:
 * - Stale chat cache after rename/delete
 * - Dual project-switch path (now uses StateManager exclusively)
 * - Retry button scope issue
 * - Explorer not re-rendering after loadProjects()
 */
window.Explorer = (() => {
  'use strict';

  // ── State ──
  let expandedProjects = new Set();
  let chatCache = {};       // Map<projectId, chats[]>
  let containerEl = null;
  let projects = [];

  // ── Helpers ──
  function _escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  function _getBase() {
    return window.API_BASE || 'http://127.0.0.1:8000';
  }

  function _getActiveProjectId() {
    if (typeof StateManager !== 'undefined' && StateManager.activeProjectId) {
      return StateManager.activeProjectId;
    }
    if (typeof activeProjectId !== 'undefined' && activeProjectId) return activeProjectId;
    return null;
  }

  function _getCurrentSessionId() {
    if (typeof currentSessionId !== 'undefined') return currentSessionId;
    if (typeof StateManager !== 'undefined') return StateManager.currentSessionId;
    return null;
  }

  // ── Rendering ──

  function renderProjects(projectList) {
    if (!containerEl) {
      containerEl = document.getElementById('projectTree');
    }
    if (!containerEl) return;
    projects = projectList || projects;
    containerEl.innerHTML = '';

    if (!projects || projects.length === 0) {
      containerEl.innerHTML = '<div class="pv-empty">No projects</div>';
      return;
    }

    for (let i = 0; i < projects.length; i++) {
      const project = projects[i];
      const isActive = (project.id === _getActiveProjectId());
      const isExpanded = expandedProjects.has(project.id);
      const isDefault = (project.id === 'default');

      const node = document.createElement('div');
      node.className = 'pv-project-node';

      const header = document.createElement('div');
      header.className = 'pv-project-header' + (isActive ? ' active' : '');

      header.innerHTML =
        '<span class="pv-chevron">' + (isExpanded ? '▼' : '▶') + '</span>' +
        '<span class="pv-project-name">' + _escapeHtml(project.name || project.id) + '</span>' +
        (!isDefault
          ? '<button class="explorer-edit-btn" title="Rename">✎</button>' +
            '<button class="explorer-delete-btn" title="Delete">🗑</button>'
          : '');

      // Wire header click
      _wireHeaderClick(header, project, isDefault);

      node.appendChild(header);

      // Chat sub-list if expanded
      if (isExpanded) {
        const subtree = document.createElement('div');
        subtree.className = 'explorer-chat-subtree';
        if (chatCache[project.id]) {
          _renderChatSubList(project.id, chatCache[project.id], subtree);
        } else {
          subtree.innerHTML = '<div class="pv-loading">Loading chats…</div>';
          _expandProject(project.id, subtree);
        }
        node.appendChild(subtree);
      }

      containerEl.appendChild(node);
    }
  }

  function _wireHeaderClick(header, project, isDefault) {
    const chevron = header.querySelector('.pv-chevron');
    if (chevron) {
      chevron.addEventListener('click', function (e) {
        e.stopPropagation();
        if (expandedProjects.has(project.id)) {
          expandedProjects.delete(project.id);
        } else {
          expandedProjects.add(project.id);
        }
        renderProjects(projects);
      });
    }

    header.addEventListener('click', function (e) {
      if (e.target.closest('.explorer-edit-btn') || e.target.closest('.explorer-delete-btn')) return;
      if (e.target.closest('.pv-chevron')) return;

      if (!expandedProjects.has(project.id)) {
        expandedProjects.add(project.id);
      }

      if (typeof StateManager !== 'undefined' && project.id !== _getActiveProjectId()) {
        StateManager.switchProject(project.id);
      }
      if (typeof navigateView === 'function') navigateView('chat');
      renderProjects(projects);
    });

    if (!isDefault) {
      const editBtn = header.querySelector('.explorer-edit-btn');
      if (editBtn) {
        editBtn.addEventListener('click', function (e) {
          e.stopPropagation();
          if (typeof editProject === 'function') editProject(project.id, project.name);
        });
      }
      const delBtn = header.querySelector('.explorer-delete-btn');
      if (delBtn) {
        delBtn.addEventListener('click', function (e) {
          e.stopPropagation();
          if (typeof deleteProject === 'function') deleteProject(project.id, project.name);
        });
      }
    }
  }

  function _renderChatSubList(projectId, chats, subtreeEl) {
    subtreeEl.innerHTML = '';
    const sorted = (chats || []).slice().sort(function (a, b) {
      return (b.created_at || '').localeCompare(a.created_at || '');
    });

    for (let j = 0; j < sorted.length; j++) {
      const chat = sorted[j];
      const isActiveChat = (chat.id === _getCurrentSessionId());
      const item = document.createElement('div');
      item.className = 'explorer-chat-item' + (isActiveChat ? ' active' : '');
      item.innerHTML =
        '<span class="explorer-chat-icon">💬</span>' +
        '<span class="explorer-chat-name">' + _escapeHtml(chat.name || 'Untitled') + '</span>';
      item.addEventListener('click', function (e) {
        e.stopPropagation();
        if (typeof switchChat === 'function') switchChat(chat.id);
      });
      subtreeEl.appendChild(item);
    }

    // "New Chat" button
    const newChatBtn = document.createElement('div');
    newChatBtn.className = 'explorer-new-chat-btn';
    newChatBtn.innerHTML = '<span>+ New Chat</span>';
    newChatBtn.addEventListener('click', function (e) {
      e.stopPropagation();
      _createChat(projectId);
    });
    subtreeEl.appendChild(newChatBtn);
  }

  // ── API Actions ──

  async function _expandProject(projectId, subtreeEl) {
    try {
      const res = await fetch(_getBase() + '/api/projects/' + encodeURIComponent(projectId));
      if (!res.ok) throw new Error('Failed to load project (' + res.status + ')');
      const project = await res.json();
      if (project.status === 'error' || !project.id) throw new Error(project.message || 'Invalid project data');
      const chats = project.chats || [];
      chatCache[projectId] = chats;
      _renderChatSubList(projectId, chats, subtreeEl);
    } catch (err) {
      subtreeEl.innerHTML = '';
      const errorDiv = document.createElement('div');
      errorDiv.className = 'pv-error';
      errorDiv.textContent = 'Failed to load chats ';
      const retryBtn = document.createElement('button');
      retryBtn.textContent = 'Retry';
      retryBtn.addEventListener('click', function () {
        subtreeEl.innerHTML = '<div class="pv-loading">Loading chats…</div>';
        _expandProject(projectId, subtreeEl);
      });
      errorDiv.appendChild(retryBtn);
      subtreeEl.appendChild(errorDiv);
    }
  }

  async function _createChat(projectId) {
    try {
      const chatId = 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function (c) {
        const r = Math.random() * 16 | 0;
        return (c === 'x' ? r : (r & 0x3 | 0x8)).toString(16);
      });
      const res = await fetch(_getBase() + '/api/projects/' + encodeURIComponent(projectId) + '/chats', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: chatId, name: 'New Chat' })
      });
      if (!res.ok) throw new Error('Failed to create chat (' + res.status + ')');

      // Switch to the new chat
      if (typeof switchChat === 'function') switchChat(chatId);

      // Optimistic cache update: add the new chat immediately instead of clearing cache
      if (!chatCache[projectId]) chatCache[projectId] = [];
      chatCache[projectId].push({ id: chatId, name: 'New Chat', created_at: new Date().toISOString() });
      renderProjects(projects);

      // Background refresh to sync with backend (no cache invalidation first)
      _refreshProjectChats(projectId).then(function () {
        renderProjects(projects);
      }).catch(function () { /* optimistic entry remains — no data loss */ });
    } catch (err) {
      // create chat error silenced
    }
  }

  async function _refreshProjectChats(projectId) {
    try {
      const res = await fetch(_getBase() + '/api/projects/' + encodeURIComponent(projectId));
      if (res.ok) {
        const data = await res.json();
        if (data.id) {
          chatCache[projectId] = data.chats || [];
        }
      }
    } catch (_) { /* silent */ }
  }

  // ── Cache Management ──

  function invalidateCache(projectId) {
    if (projectId) {
      delete chatCache[projectId];
    } else {
      chatCache = {};
    }
  }

  function updateProjects(newProjects) {
    if (!newProjects || !Array.isArray(newProjects)) return;
    // Never replace a populated tree with empty data
    if (newProjects.length === 0 && projects.length > 0) return;
    projects = newProjects;
    // Ensure containerEl is set (fallback if init() hasn't run yet)
    if (!containerEl) {
      containerEl = document.getElementById('projectTree');
    }
    // Pre-populate chat cache from projects that include chats
    for (let k = 0; k < projects.length; k++) {
      if (projects[k].chats) {
        chatCache[projects[k].id] = projects[k].chats;
      }
    }
    renderProjects(projects);
  }

  // ── Error Handling ──

  function handleError(error) {
    if (!containerEl) return;
    containerEl.innerHTML =
      '<div class="pv-error">' + _escapeHtml(error.message || 'Failed to load projects') + '</div>';
  }

  // ── Init ──

  async function init() {
    containerEl = document.getElementById('projectTree');
    if (!containerEl) {
      return;
    }

    // Wire New Project button
    const newProjectBtn = document.getElementById('newProjectBtn');
    if (newProjectBtn) {
      // Remove any existing listeners by cloning
      const fresh = newProjectBtn.cloneNode(true);
      newProjectBtn.parentNode.replaceChild(fresh, newProjectBtn);
      fresh.addEventListener('click', function (e) {
        e.preventDefault();
        e.stopPropagation();
        if (typeof handleCreateProject === 'function') handleCreateProject();
      });
    }

    // Fetch projects from backend
    try {
      var base = _getBase();
      var res = await fetch(base + '/api/projects');
      if (!res.ok) throw new Error('HTTP ' + res.status);
      var data = await res.json();
      projects = Array.isArray(data) ? data : [];
      try {
        if (typeof assignCachedProjects === 'function') {
          assignCachedProjects(projects);
        } else {
          cachedProjects = projects;
        }
      } catch (_) {}
      for (var k = 0; k < projects.length; k++) {
        if (projects[k].chats) {
          chatCache[projects[k].id] = projects[k].chats;
        }
      }
      renderProjects(projects);
    } catch (e) {
      // init fetch error silenced
      // Show error with retry instead of staying stuck on "Loading..."
      if (containerEl) {
        containerEl.innerHTML = '';
        var errorDiv = document.createElement('div');
        errorDiv.className = 'pv-error';
        errorDiv.style.cssText = 'padding:8px;font-size:12px;color:#f66;';
        errorDiv.textContent = 'Failed to load projects. ';
        var retryBtn = document.createElement('button');
        retryBtn.textContent = 'Retry';
        retryBtn.style.cssText = 'margin-left:4px;cursor:pointer;color:#b08d3e;background:none;border:1px solid #b08d3e;border-radius:4px;padding:2px 8px;font-size:11px;';
        retryBtn.addEventListener('click', function () {
          containerEl.innerHTML = '<div style="padding:8px;font-size:12px;color:#888;">Loading projects...</div>';
          init();
        });
        errorDiv.appendChild(retryBtn);
        containerEl.appendChild(errorDiv);
      }
    }
  }

  // ── Public API ──
  return {
    init: init,
    renderProjects: renderProjects,
    updateProjects: updateProjects,
    invalidateCache: invalidateCache,
    handleError: handleError,
  };
})();
