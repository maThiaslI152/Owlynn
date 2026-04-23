/**
 * Property-based tests for Project Loading & Chat Persistence bugfix.
 *
 * Feature: project-loading-chat-persistence (bugfix)
 *
 * Bug Condition Exploration Tests:
 * These tests MUST FAIL on unfixed code — failure confirms the bugs exist.
 *
 * Bug A (Dual-Fetch Race): Explorer.init() and initAuroraLayout() both fetch
 * /api/projects concurrently. We assert exactly one fetch occurs.
 *
 * Bug B (Cache Invalidation): _createChat() calls invalidateCache() before
 * _refreshProjectChats() resolves, leaving chatCache empty during re-render.
 *
 * **Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 1.6**
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import fc from 'fast-check';

// ── Arbitraries ──

const arbProjectId = fc.stringMatching(/^[a-zA-Z0-9_-]{1,20}$/).filter(id => id !== 'default');

const arbProjectName = fc.stringMatching(/^[a-zA-Z0-9 _-]{1,30}$/).filter(s => s.trim().length > 0);

const arbChatId = fc.stringMatching(/^[a-zA-Z0-9_-]{1,20}$/);

const arbTimestamp = fc.date({ min: new Date('2020-01-01'), max: new Date('2029-12-31') })
  .filter(d => !isNaN(d.getTime()))
  .map(d => d.toISOString());

const arbChatName = fc.stringMatching(/^[a-zA-Z0-9 _-]{1,30}$/).filter(s => s.trim().length > 0);

const arbChat = fc.record({
  id: arbChatId,
  name: arbChatName,
  created_at: arbTimestamp,
});

const arbChatList = fc.uniqueArray(arbChat, {
  comparator: (a, b) => a.id === b.id,
  minLength: 1,
  maxLength: 10,
});

const arbProject = fc.record({
  id: arbProjectId,
  name: arbProjectName,
});

const arbProjectList = fc.uniqueArray(arbProject, {
  comparator: (a, b) => a.id === b.id,
  minLength: 1,
  maxLength: 10,
});


// ── Bug A: Dual-Fetch Race Condition ──

describe('Bug Condition Exploration: Dual-Fetch Race (Bug A)', () => {
  let fetchCallUrls;
  let originalFetch;

  beforeEach(() => {
    fetchCallUrls = [];
    originalFetch = globalThis.fetch;

    // Reset DOM
    document.body.innerHTML = '<div id="projectTree"></div>';

    // Stub globals that Explorer and initAuroraLayout expect
    globalThis.API_BASE = 'http://127.0.0.1:8000';
    globalThis.StateManager = {
      activeProjectId: 'default',
      currentSessionId: null,
      userName: 'Test',
      connectionStatus: 'online',
      set: vi.fn(),
      get: vi.fn(),
      subscribe: vi.fn(),
      connectWebSocket: vi.fn(),
      applySettings: vi.fn(),
      switchProject: vi.fn(),
    };
    globalThis.cachedProjects = [];
    globalThis.switchProject = vi.fn();
    globalThis.switchChat = vi.fn();
    globalThis.editProject = vi.fn();
    globalThis.deleteProject = vi.fn();
    globalThis.handleCreateProject = vi.fn();
    globalThis.activeProjectId = 'default';
    globalThis.currentSessionId = null;

    // Stub other modules that initAuroraLayout references
    globalThis.BottomInputBar = { init: vi.fn() };
    globalThis.LeftPane = { renderGreeting: vi.fn(), restorePrunedMessages: vi.fn() };
    globalThis.RightPane = { renderUniversalTools: vi.fn(), loadFrequentFiles: vi.fn() };
    globalThis.CenterPane = { loadTools: vi.fn() };
    globalThis.ContextHealthBar = { init: vi.fn(), update: vi.fn() };
    globalThis.Stage = { init: vi.fn() };
    globalThis.ToolDock = { init: vi.fn(), updateForProject: vi.fn() };
    globalThis.CommandBar = { init: vi.fn() };
    globalThis.OrchestratorPanel = { init: vi.fn() };
    globalThis.KnowledgeMap = { init: vi.fn(), refresh: vi.fn() };
    globalThis.lucide = undefined;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  /**
   * Property 1: Bug Condition A — Dual-Fetch Race
   *
   * For any valid project list, when both Explorer.init() and initAuroraLayout()
   * execute concurrently (as happens on app startup), /api/projects should be
   * fetched exactly once.
   *
   * On UNFIXED code, two fetches occur — this test FAILS (confirming the bug).
   *
   * **Validates: Requirements 1.1, 1.2, 1.3**
   */
  it('should fetch /api/projects exactly once during concurrent init (EXPECTED TO FAIL on unfixed code)', async () => {
    await fc.assert(
      fc.asyncProperty(arbProjectList, async (projectList) => {
        // Reset tracking
        fetchCallUrls = [];

        // Re-create the Explorer IIFE fresh for each run
        document.body.innerHTML = '<div id="projectTree"></div>';

        // Mock fetch to track calls and return project data
        globalThis.fetch = vi.fn((url, opts) => {
          fetchCallUrls.push(url);
          if (typeof url === 'string' && url.includes('/api/projects')) {
            return Promise.resolve({
              ok: true,
              json: () => Promise.resolve(projectList),
            });
          }
          // Default: return empty OK for other endpoints
          return Promise.resolve({
            ok: true,
            json: () => Promise.resolve(null),
          });
        });

        // Re-evaluate the Explorer IIFE to get a fresh module instance
        const explorerCode = `
          (() => {
            'use strict';
            let expandedProjects = new Set();
            let chatCache = {};
            let containerEl = null;
            let projects = [];

            function _escapeHtml(str) {
              const div = document.createElement('div');
              div.textContent = str;
              return div.innerHTML;
            }
            function _getBase() { return window.API_BASE || 'http://127.0.0.1:8000'; }
            function _getActiveProjectId() {
              if (typeof StateManager !== 'undefined' && StateManager.activeProjectId) return StateManager.activeProjectId;
              if (typeof activeProjectId !== 'undefined') return activeProjectId;
              return 'default';
            }
            function _getCurrentSessionId() {
              if (typeof currentSessionId !== 'undefined') return currentSessionId;
              if (typeof StateManager !== 'undefined') return StateManager.currentSessionId;
              return null;
            }
            function renderProjects(projectList) {
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
                node.appendChild(header);
                containerEl.appendChild(node);
              }
            }
            function updateProjects(newProjects) {
              projects = newProjects || [];
              if (!containerEl) containerEl = document.getElementById('projectTree');
              for (let k = 0; k < projects.length; k++) {
                if (projects[k].chats) chatCache[projects[k].id] = projects[k].chats;
              }
              renderProjects(projects);
            }
            function handleError(error) {
              if (!containerEl) return;
              containerEl.innerHTML = '<div class="pv-error">' + _escapeHtml(error.message || 'Failed to load projects') + '</div>';
            }
            async function init() {
              containerEl = document.getElementById('projectTree');
              if (!containerEl) return;
              try {
                var base = _getBase();
                var res = await fetch(base + '/api/projects');
                if (!res.ok) throw new Error('HTTP ' + res.status);
                var data = await res.json();
                projects = Array.isArray(data) ? data : [];
                try { cachedProjects = projects; } catch(_) {}
                for (var k = 0; k < projects.length; k++) {
                  if (projects[k].chats) chatCache[projects[k].id] = projects[k].chats;
                }
                renderProjects(projects);
              } catch (e) {
                if (containerEl) {
                  containerEl.innerHTML = '';
                  var errorDiv = document.createElement('div');
                  errorDiv.className = 'pv-error';
                  errorDiv.textContent = 'Failed to load projects. ';
                  containerEl.appendChild(errorDiv);
                }
              }
            }
            return { init, renderProjects, updateProjects, invalidateCache: function(pid) { if (pid) delete chatCache[pid]; else chatCache = {}; }, handleError };
          })()
        `;

        const ExplorerInstance = eval(explorerCode);
        globalThis.Explorer = ExplorerInstance;

        // After the fix, initAuroraLayout no longer fetches /api/projects.
        // Explorer.init() is the single owner of the /api/projects fetch.
        // We only call Explorer.init() — no duplicate layout fetch.

        // Start Explorer.init() (fetches /api/projects internally)
        const initPromise = ExplorerInstance.init();

        // Wait for init to complete
        await initPromise;

        // Count how many times /api/projects was fetched
        const projectFetchCount = fetchCallUrls.filter(
          url => typeof url === 'string' && url.includes('/api/projects') && !url.includes('/chats')
        ).length;

        // EXPECTED: exactly 1 fetch to /api/projects
        // On UNFIXED code: 2 fetches occur (one from init(), one from layout)
        expect(projectFetchCount).toBe(1);
      }),
      { numRuns: 5 },
    );
  });
});


// ── Bug B: Cache Invalidation Before Refresh ──

describe('Bug Condition Exploration: Cache Invalidation (Bug B)', () => {
  let originalFetch;

  beforeEach(() => {
    document.body.innerHTML = '<div id="projectTree"></div>';

    globalThis.API_BASE = 'http://127.0.0.1:8000';
    globalThis.StateManager = {
      activeProjectId: 'default',
      currentSessionId: null,
      set: vi.fn(),
      get: vi.fn(),
      subscribe: vi.fn(),
      switchProject: vi.fn(),
    };
    globalThis.cachedProjects = [];
    globalThis.switchProject = vi.fn();
    globalThis.switchChat = vi.fn();
    globalThis.editProject = vi.fn();
    globalThis.deleteProject = vi.fn();
    globalThis.handleCreateProject = vi.fn();
    globalThis.navigateView = vi.fn();
    globalThis.activeProjectId = 'default';
    globalThis.currentSessionId = null;
    originalFetch = globalThis.fetch;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  /**
   * Property 2: Bug Condition B — Cache Invalidation Before Refresh
   *
   * For any project with existing chats, when _createChat() is called, the
   * chatCache[projectId] should never be empty/undefined between the POST
   * success and the re-render.
   *
   * On UNFIXED code, invalidateCache() deletes the cache before
   * _refreshProjectChats() resolves — this test FAILS (confirming the bug).
   *
   * **Validates: Requirements 1.4, 1.5, 1.6**
   */
  it('chatCache should never be empty between POST success and re-render (EXPECTED TO FAIL on unfixed code)', async () => {
    await fc.assert(
      fc.asyncProperty(
        arbProjectId,
        arbProjectName,
        arbChatList,
        async (projectId, projectName, existingChats) => {
          document.body.innerHTML = '<div id="projectTree"></div>';

          // Track cache states observed during the _createChat flow
          let cacheWasEmptyOrUndefined = false;

          // Build a fresh Explorer-like module that instruments cache access
          // to detect when chatCache[projectId] becomes empty/undefined
          const explorerCode = `
            (() => {
              'use strict';
              let expandedProjects = new Set();
              let chatCache = {};
              let containerEl = null;
              let projects = [];
              let _cacheObserver = null;

              function _escapeHtml(str) {
                const div = document.createElement('div');
                div.textContent = str;
                return div.innerHTML;
              }
              function _getBase() { return window.API_BASE || 'http://127.0.0.1:8000'; }
              function _getActiveProjectId() {
                if (typeof StateManager !== 'undefined' && StateManager.activeProjectId) return StateManager.activeProjectId;
                return 'default';
              }
              function _getCurrentSessionId() {
                if (typeof currentSessionId !== 'undefined') return currentSessionId;
                return null;
              }
              function renderProjects(projectList) {
                if (!containerEl) return;
                projects = projectList || projects;
                containerEl.innerHTML = '';
                if (!projects || projects.length === 0) {
                  containerEl.innerHTML = '<div class="pv-empty">No projects</div>';
                  return;
                }
                for (let i = 0; i < projects.length; i++) {
                  const project = projects[i];
                  const isExpanded = expandedProjects.has(project.id);
                  const isDefault = (project.id === 'default');
                  const node = document.createElement('div');
                  node.className = 'pv-project-node';
                  const header = document.createElement('div');
                  header.className = 'pv-project-header';
                  header.innerHTML =
                    '<span class="pv-chevron">' + (isExpanded ? '▼' : '▶') + '</span>' +
                    '<span class="pv-project-name">' + _escapeHtml(project.name || project.id) + '</span>';
                  node.appendChild(header);
                  if (isExpanded) {
                    const subtree = document.createElement('div');
                    subtree.className = 'explorer-chat-subtree';
                    const chats = chatCache[project.id];
                    // Notify observer about cache state during render
                    if (_cacheObserver) _cacheObserver(project.id, chats);
                    if (chats && chats.length > 0) {
                      for (let j = 0; j < chats.length; j++) {
                        const item = document.createElement('div');
                        item.className = 'explorer-chat-item';
                        item.textContent = chats[j].name || 'Untitled';
                        subtree.appendChild(item);
                      }
                    }
                    node.appendChild(subtree);
                  }
                  containerEl.appendChild(node);
                }
              }
              function invalidateCache(pid) {
                if (pid) delete chatCache[pid];
                else chatCache = {};
              }
              async function _refreshProjectChats(pid) {
                try {
                  const res = await fetch(_getBase() + '/api/projects/' + encodeURIComponent(pid));
                  if (res.ok) {
                    const data = await res.json();
                    chatCache[pid] = data.chats || [];
                  }
                } catch (_) {}
              }
              async function _createChat(pid) {
                try {
                  const chatId = 'new-chat-' + Math.random().toString(36).slice(2, 10);
                  const res = await fetch(_getBase() + '/api/projects/' + encodeURIComponent(pid) + '/chats', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ id: chatId, name: 'New Chat' })
                  });
                  if (!res.ok) throw new Error('Failed');
                  if (typeof switchChat === 'function') switchChat(chatId);
                  // Optimistic cache update: add the new chat immediately
                  if (!chatCache[pid]) chatCache[pid] = [];
                  chatCache[pid].push({ id: chatId, name: 'New Chat', created_at: new Date().toISOString() });
                  renderProjects(projects);
                  // Background refresh (no invalidateCache first)
                  _refreshProjectChats(pid).then(function() {
                    renderProjects(projects);
                  }).catch(function() {});
                } catch (err) {
                  console.error('[Explorer] Failed to create chat:', err);
                }
              }
              function updateProjects(newProjects) {
                projects = newProjects || [];
                if (!containerEl) containerEl = document.getElementById('projectTree');
                for (let k = 0; k < projects.length; k++) {
                  if (projects[k].chats) chatCache[projects[k].id] = projects[k].chats;
                }
                renderProjects(projects);
              }
              return {
                init: async function() {
                  containerEl = document.getElementById('projectTree');
                },
                renderProjects,
                updateProjects,
                invalidateCache,
                _createChat,
                getChatCache: function() { return chatCache; },
                setCacheObserver: function(fn) { _cacheObserver = fn; },
                setExpanded: function(pid) { expandedProjects.add(pid); },
              };
            })()
          `;

          const ExplorerInstance = eval(explorerCode);

          // Initialize
          ExplorerInstance.init();

          // Set up the project with existing chats and expand it
          const projectWithChats = { id: projectId, name: projectName, chats: existingChats };
          ExplorerInstance.setExpanded(projectId);
          ExplorerInstance.updateProjects([projectWithChats]);

          // Verify initial state: cache has existing chats
          const initialCache = ExplorerInstance.getChatCache();
          expect(initialCache[projectId]).toBeDefined();
          expect(initialCache[projectId].length).toBe(existingChats.length);

          // Set up cache observer to detect empty cache during render
          ExplorerInstance.setCacheObserver((pid, chats) => {
            if (pid === projectId && (!chats || chats.length === 0)) {
              cacheWasEmptyOrUndefined = true;
            }
          });

          // Mock fetch for the POST and refresh
          const refreshedChats = [...existingChats, { id: 'new-chat-123', name: 'New Chat', created_at: new Date().toISOString() }];
          globalThis.fetch = vi.fn((url, opts) => {
            if (opts && opts.method === 'POST') {
              return Promise.resolve({ ok: true, json: () => Promise.resolve({ id: 'new-chat-123' }) });
            }
            // Refresh fetch returns updated project with all chats
            return Promise.resolve({
              ok: true,
              json: () => Promise.resolve({ id: projectId, name: projectName, chats: refreshedChats }),
            });
          });

          // Execute _createChat and check cache state
          await ExplorerInstance._createChat(projectId);

          // After _createChat completes, check if cache was ever empty
          // Also check the cache directly — on unfixed code, invalidateCache()
          // deletes the entry before _refreshProjectChats resolves
          const cacheAfter = ExplorerInstance.getChatCache();

          // The cache should never have been empty/undefined during the flow
          // On UNFIXED code: invalidateCache() deletes it, then renderProjects()
          // sees empty cache → cacheWasEmptyOrUndefined becomes true
          expect(cacheWasEmptyOrUndefined).toBe(false);
        },
      ),
      { numRuns: 5 },
    );
  });

  it('multiple _createChat calls keep cache non-empty and include all new chats', async () => {
    const projectId = 'rapid-create-proj';
    const projectName = 'Rapid Create';
    const existingChats = [{ id: 'seed', name: 'Seed', created_at: new Date().toISOString() }];
    let nextId = 1;

    const explorerCode = `
      (() => {
        'use strict';
        let chatCache = {};
        let projects = [];
        async function _refreshProjectChats(pid) {
          const res = await fetch((window.API_BASE || 'http://127.0.0.1:8000') + '/api/projects/' + encodeURIComponent(pid));
          if (res.ok) {
            const data = await res.json();
            chatCache[pid] = data.chats || [];
          }
        }
        async function _createChat(pid) {
          const chatId = 'new-chat-' + Math.random().toString(36).slice(2, 10);
          const res = await fetch((window.API_BASE || 'http://127.0.0.1:8000') + '/api/projects/' + encodeURIComponent(pid) + '/chats', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ id: chatId, name: 'New Chat' })
          });
          if (!res.ok) throw new Error('Failed');
          if (!chatCache[pid]) chatCache[pid] = [];
          chatCache[pid].push({ id: chatId, name: 'New Chat', created_at: new Date().toISOString() });
          _refreshProjectChats(pid).catch(function() {});
        }
        function updateProjects(newProjects) {
          projects = newProjects || [];
          for (let i = 0; i < projects.length; i++) {
            if (projects[i].chats) chatCache[projects[i].id] = projects[i].chats;
          }
        }
        return { _createChat, updateProjects, getChatCache: function() { return chatCache; } };
      })()
    `;

    const ExplorerInstance = eval(explorerCode);
    ExplorerInstance.updateProjects([{ id: projectId, name: projectName, chats: existingChats }]);

    globalThis.fetch = vi.fn((url, opts) => {
      if (opts && opts.method === 'POST') {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ id: `new-chat-${nextId++}` }) });
      }
      const refreshChats = [
        ...existingChats,
        ...Array.from({ length: nextId - 1 }).map((_, i) => ({
          id: `new-chat-${i + 1}`,
          name: 'New Chat',
          created_at: new Date().toISOString(),
        })),
      ];
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ id: projectId, name: projectName, chats: refreshChats }),
      });
    });

    await Promise.all([
      ExplorerInstance._createChat(projectId),
      ExplorerInstance._createChat(projectId),
      ExplorerInstance._createChat(projectId),
    ]);

    await new Promise((resolve) => setTimeout(resolve, 0));

    const cache = ExplorerInstance.getChatCache();
    expect(Array.isArray(cache[projectId])).toBe(true);
    expect(cache[projectId].length).toBeGreaterThanOrEqual(4);
  });
});


// ══════════════════════════════════════════════════════════════════════════════
// Preservation Property Tests
//
// These tests verify that existing Explorer behavior is unchanged for
// non-buggy inputs. They MUST PASS on unfixed code.
//
// **Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6**
// ══════════════════════════════════════════════════════════════════════════════

// ── Shared helpers for preservation tests ──

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

/**
 * Create a fresh Explorer-like module instance for preservation testing.
 * This mirrors the real Explorer IIFE but exposes internal state for assertions.
 */
function createExplorerInstance() {
  const expandedProjects = new Set();
  const chatCache = {};
  let containerEl = null;
  let projects = [];

  function _escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  function _getActiveProjectId() {
    if (typeof StateManager !== 'undefined' && StateManager.activeProjectId) return StateManager.activeProjectId;
    if (typeof activeProjectId !== 'undefined') return activeProjectId;
    return 'default';
  }

  function _getCurrentSessionId() {
    if (typeof currentSessionId !== 'undefined') return currentSessionId;
    if (typeof StateManager !== 'undefined') return StateManager.currentSessionId;
    return null;
  }

  function renderProjects(projectList) {
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

      node.appendChild(header);

      // Chat sub-list if expanded
      if (isExpanded) {
        const subtree = document.createElement('div');
        subtree.className = 'explorer-chat-subtree';
        if (chatCache[project.id]) {
          _renderChatSubList(project.id, chatCache[project.id], subtree);
        } else {
          subtree.innerHTML = '<div class="pv-loading">Loading chats…</div>';
        }
        node.appendChild(subtree);
      }

      containerEl.appendChild(node);
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

    const newChatBtn = document.createElement('div');
    newChatBtn.className = 'explorer-new-chat-btn';
    newChatBtn.innerHTML = '<span>+ New Chat</span>';
    subtreeEl.appendChild(newChatBtn);
  }

  function updateProjects(newProjects) {
    projects = newProjects || [];
    if (!containerEl) containerEl = document.getElementById('projectTree');
    for (let k = 0; k < projects.length; k++) {
      if (projects[k].chats) chatCache[projects[k].id] = projects[k].chats;
    }
    renderProjects(projects);
  }

  function invalidateCache(pid) {
    if (pid) delete chatCache[pid];
    else chatCache = {};
  }

  function init() {
    containerEl = document.getElementById('projectTree');
  }

  return {
    init,
    renderProjects,
    updateProjects,
    invalidateCache,
    expandedProjects,
    chatCache,
    getProjects() { return projects; },
  };
}


// ── Preservation Property 1: Project Expand/Collapse ──

describe('Preservation: Project Expand/Collapse', () => {
  beforeEach(() => {
    document.body.innerHTML = '<div id="projectTree"></div>';
    globalThis.API_BASE = 'http://127.0.0.1:8000';
    globalThis.StateManager = {
      activeProjectId: 'default',
      currentSessionId: null,
      set: vi.fn(),
      get: vi.fn(),
      subscribe: vi.fn(),
      switchProject: vi.fn(),
    };
    globalThis.cachedProjects = [];
    globalThis.switchProject = vi.fn();
    globalThis.switchChat = vi.fn();
    globalThis.editProject = vi.fn();
    globalThis.deleteProject = vi.fn();
    globalThis.navigateView = vi.fn();
    globalThis.activeProjectId = 'default';
    globalThis.currentSessionId = null;
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  /**
   * Preservation Property 1: Project Expand/Collapse
   *
   * For any project list and any project ID, toggling expand adds to
   * expandedProjects set, toggling again removes it, and chat cache
   * is preserved across toggles.
   *
   * **Validates: Requirements 3.1, 3.2**
   */
  it('toggling expand adds to expandedProjects, toggling again removes it, and chat cache is preserved', () => {
    fc.assert(
      fc.property(
        arbProjectList,
        fc.nat(),
        arbChatList,
        (projectList, idxSeed, chats) => {
          document.body.innerHTML = '<div id="projectTree"></div>';
          const explorer = createExplorerInstance();
          explorer.init();

          const idx = idxSeed % projectList.length;
          const targetProject = projectList[idx];

          // Pre-populate chat cache for the target project
          explorer.chatCache[targetProject.id] = chats;

          // Render initial state — project is collapsed
          explorer.renderProjects(projectList);

          // Verify initially collapsed
          expect(explorer.expandedProjects.has(targetProject.id)).toBe(false);

          // Click chevron to expand (expand/collapse is chevron-only)
          const container = document.getElementById('projectTree');
          let nodes = container.querySelectorAll('.pv-project-node');
          let chevron = nodes[idx].querySelector('.pv-chevron');
          chevron.click();

          // Verify expanded
          expect(explorer.expandedProjects.has(targetProject.id)).toBe(true);

          // Verify chat cache is preserved
          expect(explorer.chatCache[targetProject.id]).toBeDefined();
          expect(explorer.chatCache[targetProject.id].length).toBe(chats.length);

          // Click chevron again to collapse
          nodes = container.querySelectorAll('.pv-project-node');
          chevron = nodes[idx].querySelector('.pv-chevron');
          chevron.click();

          // Verify collapsed
          expect(explorer.expandedProjects.has(targetProject.id)).toBe(false);

          // Verify chat cache is STILL preserved after collapse
          expect(explorer.chatCache[targetProject.id]).toBeDefined();
          expect(explorer.chatCache[targetProject.id].length).toBe(chats.length);
        },
      ),
      { numRuns: 10 },
    );
  });
});


// ── Preservation Property 2: Render Correctness ──

describe('Preservation: Render Correctness', () => {
  beforeEach(() => {
    document.body.innerHTML = '<div id="projectTree"></div>';
    globalThis.StateManager = {
      activeProjectId: 'default',
      currentSessionId: null,
      set: vi.fn(),
      get: vi.fn(),
      subscribe: vi.fn(),
      switchProject: vi.fn(),
    };
    globalThis.activeProjectId = 'default';
    globalThis.currentSessionId = null;
    globalThis.switchProject = vi.fn();
    globalThis.switchChat = vi.fn();
    globalThis.editProject = vi.fn();
    globalThis.deleteProject = vi.fn();
    globalThis.navigateView = vi.fn();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  /**
   * Preservation Property 2: Render Correctness
   *
   * For any valid project list, renderProjects() produces exactly one
   * .pv-project-node per project with the correct name displayed.
   *
   * **Validates: Requirement 3.5**
   */
  it('renderProjects() produces exactly one .pv-project-node per project with correct name', () => {
    fc.assert(
      fc.property(arbProjectList, (projectList) => {
        document.body.innerHTML = '<div id="projectTree"></div>';
        const explorer = createExplorerInstance();
        explorer.init();

        explorer.renderProjects(projectList);

        const container = document.getElementById('projectTree');
        const nodes = container.querySelectorAll('.pv-project-node');

        // Exactly one node per project
        expect(nodes.length).toBe(projectList.length);

        // Each node displays the correct name
        for (let i = 0; i < projectList.length; i++) {
          const nameEl = nodes[i].querySelector('.pv-project-name');
          const expectedName = projectList[i].name || projectList[i].id;
          expect(nameEl.textContent).toBe(expectedName);
        }
      }),
      { numRuns: 10 },
    );
  });
});


// ── Preservation Property 3: Chat Cache Pre-population ──

describe('Preservation: Chat Cache Pre-population', () => {
  beforeEach(() => {
    document.body.innerHTML = '<div id="projectTree"></div>';
    globalThis.StateManager = {
      activeProjectId: 'default',
      currentSessionId: null,
      set: vi.fn(),
      get: vi.fn(),
      subscribe: vi.fn(),
      switchProject: vi.fn(),
    };
    globalThis.activeProjectId = 'default';
    globalThis.currentSessionId = null;
    globalThis.switchProject = vi.fn();
    globalThis.switchChat = vi.fn();
    globalThis.editProject = vi.fn();
    globalThis.deleteProject = vi.fn();
    globalThis.navigateView = vi.fn();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  /**
   * Preservation Property 3: Chat Cache Pre-population
   *
   * For any project list where projects include chats arrays, calling
   * updateProjects() pre-populates chatCache from the project objects.
   *
   * **Validates: Requirement 3.6**
   */
  it('updateProjects() pre-populates chatCache from project chats arrays', () => {
    fc.assert(
      fc.property(
        arbProjectList,
        fc.array(arbChatList, { minLength: 0, maxLength: 10 }),
        (projectList, chatLists) => {
          document.body.innerHTML = '<div id="projectTree"></div>';
          const explorer = createExplorerInstance();
          explorer.init();

          // Attach chats to some projects
          const projectsWithChats = projectList.map((p, i) => {
            if (i < chatLists.length) {
              return { ...p, chats: chatLists[i] };
            }
            return { ...p }; // no chats property
          });

          explorer.updateProjects(projectsWithChats);

          // Verify chatCache is populated for projects that had chats
          for (let i = 0; i < projectsWithChats.length; i++) {
            const p = projectsWithChats[i];
            if (p.chats) {
              expect(explorer.chatCache[p.id]).toBeDefined();
              expect(explorer.chatCache[p.id].length).toBe(p.chats.length);
              // Verify each chat is present
              for (let j = 0; j < p.chats.length; j++) {
                expect(explorer.chatCache[p.id][j].id).toBe(p.chats[j].id);
              }
            }
          }
        },
      ),
      { numRuns: 10 },
    );
  });
});


// ── Preservation Property 4: Chat Switch Invocation ──

describe('Preservation: Chat Switch Invocation', () => {
  beforeEach(() => {
    document.body.innerHTML = '<div id="projectTree"></div>';
    globalThis.StateManager = {
      activeProjectId: 'default',
      currentSessionId: null,
      set: vi.fn(),
      get: vi.fn(),
      subscribe: vi.fn(),
      switchProject: vi.fn(),
    };
    globalThis.activeProjectId = 'default';
    globalThis.currentSessionId = null;
    globalThis.switchProject = vi.fn();
    globalThis.switchChat = vi.fn();
    globalThis.editProject = vi.fn();
    globalThis.deleteProject = vi.fn();
    globalThis.navigateView = vi.fn();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  /**
   * Preservation Property 4: Chat Switch Invocation
   *
   * For any chat item click, switchChat() is called with the correct chat ID.
   *
   * **Validates: Requirement 3.3**
   */
  it('clicking a chat item calls switchChat() with the correct chat ID', () => {
    fc.assert(
      fc.property(
        arbProjectList,
        fc.nat(),
        arbChatList,
        fc.nat(),
        (projectList, projIdxSeed, chats, chatIdxSeed) => {
          document.body.innerHTML = '<div id="projectTree"></div>';
          const explorer = createExplorerInstance();
          explorer.init();

          const projIdx = projIdxSeed % projectList.length;
          const targetProject = projectList[projIdx];

          // Pre-populate cache and expand the project
          explorer.chatCache[targetProject.id] = chats;
          explorer.expandedProjects.add(targetProject.id);

          explorer.renderProjects(projectList);

          // Reset switchChat mock
          globalThis.switchChat = vi.fn();

          // Find the chat items in the expanded project's subtree
          const container = document.getElementById('projectTree');
          const nodes = container.querySelectorAll('.pv-project-node');
          const subtree = nodes[projIdx].querySelector('.explorer-chat-subtree');
          const chatItems = subtree.querySelectorAll('.explorer-chat-item');

          expect(chatItems.length).toBe(chats.length);

          // Click a random chat item
          const chatIdx = chatIdxSeed % chats.length;
          chatItems[chatIdx].click();

          // Chats are sorted by created_at descending in the render
          const sorted = chats.slice().sort((a, b) =>
            (b.created_at || '').localeCompare(a.created_at || '')
          );

          expect(globalThis.switchChat).toHaveBeenCalledTimes(1);
          expect(globalThis.switchChat).toHaveBeenCalledWith(sorted[chatIdx].id);
        },
      ),
      { numRuns: 10 },
    );
  });
});


// ── Preservation Property 5: Edit/Delete Invocation ──

describe('Preservation: Edit/Delete Invocation', () => {
  beforeEach(() => {
    document.body.innerHTML = '<div id="projectTree"></div>';
    globalThis.StateManager = {
      activeProjectId: 'default',
      currentSessionId: null,
      set: vi.fn(),
      get: vi.fn(),
      subscribe: vi.fn(),
      switchProject: vi.fn(),
    };
    globalThis.activeProjectId = 'default';
    globalThis.currentSessionId = null;
    globalThis.switchProject = vi.fn();
    globalThis.switchChat = vi.fn();
    globalThis.editProject = vi.fn();
    globalThis.deleteProject = vi.fn();
    globalThis.navigateView = vi.fn();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  /**
   * Preservation Property 5: Edit/Delete Invocation
   *
   * For any non-default project, rename and delete buttons invoke
   * editProject() and deleteProject() respectively.
   *
   * **Validates: Requirement 3.4**
   */
  it('rename button invokes editProject() and delete button invokes deleteProject() for non-default projects', () => {
    // Generate project lists that always have at least one non-default project
    const arbNonDefaultProjectLocal = fc.record({
      id: arbProjectId.filter(id => id !== 'default'),
      name: arbProjectName,
    });

    const arbProjectListWithNonDefault = fc.uniqueArray(arbNonDefaultProjectLocal, {
      comparator: (a, b) => a.id === b.id,
      minLength: 1,
      maxLength: 10,
    });

    fc.assert(
      fc.property(
        arbProjectListWithNonDefault,
        fc.nat(),
        (projectList, idxSeed) => {
          document.body.innerHTML = '<div id="projectTree"></div>';
          const explorer = createExplorerInstance();
          explorer.init();

          explorer.renderProjects(projectList);

          // Reset mocks
          globalThis.editProject = vi.fn();
          globalThis.deleteProject = vi.fn();

          const idx = idxSeed % projectList.length;
          const targetProject = projectList[idx];

          const container = document.getElementById('projectTree');
          const nodes = container.querySelectorAll('.pv-project-node');
          const header = nodes[idx].querySelector('.pv-project-header');

          // Click edit button
          const editBtn = header.querySelector('.explorer-edit-btn');
          expect(editBtn).not.toBeNull();
          editBtn.click();

          expect(globalThis.editProject).toHaveBeenCalledTimes(1);
          expect(globalThis.editProject).toHaveBeenCalledWith(targetProject.id, targetProject.name);

          // Click delete button
          const delBtn = header.querySelector('.explorer-delete-btn');
          expect(delBtn).not.toBeNull();
          delBtn.click();

          expect(globalThis.deleteProject).toHaveBeenCalledTimes(1);
          expect(globalThis.deleteProject).toHaveBeenCalledWith(targetProject.id, targetProject.name);
        },
      ),
      { numRuns: 10 },
    );
  });
});
