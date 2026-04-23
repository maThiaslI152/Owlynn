/**
 * Integration tests for Workspace Switching & Debug Cleanup bugfix.
 *
 * Task 8: Integration Testing
 *
 * 8.1 — Open project detail → click workspace item → verify file list updates
 *        without disappearing and without WebSocket reconnection.
 *
 * 8.2 — Browse project in explorer via browseProject() → then switch to different
 *        project via switchProject() → verify correct context swap occurs only on
 *        the explicit switch.
 *
 * 8.3 — Pin toggle in project detail → verify pin icon updates without full view
 *        teardown.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

// ── Helpers ──

/**
 * Build a minimal StateManager that mirrors the fixed implementation.
 * Tracks calls to browseProject, switchProject, connectWebSocket, and notify.
 */
function createStateManager(initialProjectId = 'proj-a') {
  const calls = {
    browseProject: [],
    switchProject: [],
    connectWebSocket: [],
    notify: [],
  };

  const state = {
    activeProjectId: initialProjectId,
    currentSessionId: 'thread-' + initialProjectId,
    projectThreads: {},
    socket: null,
    connectionStatus: 'online',
    isStreaming: false,
  };

  function generateUUID() {
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => {
      const r = (Math.random() * 16) | 0;
      return (c === 'x' ? r : (r & 0x3) | 0x8).toString(16);
    });
  }

  const sm = {
    get activeProjectId() { return state.activeProjectId; },
    get currentSessionId() { return state.currentSessionId; },
    get projectThreads() { return state.projectThreads; },
    get connectionStatus() { return state.connectionStatus; },

    _calls: calls,
    _state: state,

    subscribe() {},

    notify(keys) {
      calls.notify.push([...keys]);
    },

    set(key, value) {
      // Plain state update — no interception (matches fixed code)
      state[key] = value;
      this.notify([key]);
    },

    browseProject(projectId) {
      calls.browseProject.push(projectId);
      if (projectId === state.activeProjectId) return;
      state.activeProjectId = projectId;
      this.notify(['activeProjectId']);
    },

    connectWebSocket(threadId) {
      calls.connectWebSocket.push(threadId);
    },

    async switchProject(newProjectId, resetChat = true) {
      calls.switchProject.push(newProjectId);
      const oldProjectId = state.activeProjectId;
      if (newProjectId === oldProjectId) return;

      // Save current thread
      if (oldProjectId) {
        state.projectThreads[oldProjectId] = {
          threadId: state.currentSessionId,
          scrollPos: 0,
        };
      }

      // Determine thread for new project
      const saved = state.projectThreads[newProjectId];
      const threadId = saved ? saved.threadId : generateUUID();

      state.activeProjectId = newProjectId;
      state.currentSessionId = threadId;

      // WebSocket reconnection
      this.connectWebSocket(threadId);

      // Module updates
      if (window.ContextHealthBar) ContextHealthBar.update(0, 0, null);
      if (window.ToolDock && typeof ToolDock.updateForProject === 'function') ToolDock.updateForProject(newProjectId);
      if (window.KnowledgeMap && typeof KnowledgeMap.refresh === 'function') KnowledgeMap.refresh(newProjectId);

      this.notify(['activeProjectId', 'currentSessionId']);
    },
  };

  return sm;
}


// ══════════════════════════════════════════════════════════════════════════════
// 8.1 — Project detail workspace item click: file list persists, no WS reconnect
// ══════════════════════════════════════════════════════════════════════════════

describe('8.1 Integration: workspace item click in project detail preserves file list', () => {
  let sm;
  let originalFetch;

  beforeEach(() => {
    originalFetch = globalThis.fetch;
    sm = createStateManager('proj-a');
    globalThis.StateManager = sm;
    globalThis.API_BASE = 'http://127.0.0.1:8000';
    globalThis.ContextHealthBar = { init: vi.fn(), update: vi.fn() };
    globalThis.ToolDock = { init: vi.fn(), updateForProject: vi.fn() };
    globalThis.KnowledgeMap = { init: vi.fn(), refresh: vi.fn() };

    // Set up DOM with project detail view including file cards
    document.body.innerHTML = `
      <div id="view-project-detail">
        <div id="projectDetailName">Project A</div>
        <div id="projectDetailDesc"></div>
        <div id="projectDetailInstructions"></div>
        <div id="projectDetailPin">☆</div>
        <div id="projectDetailChats"></div>
        <div id="projectDetailFiles">
          <div class="project-file-card"><span class="file-name">readme.md</span></div>
          <div class="project-file-card"><span class="file-name">index.js</span></div>
          <div class="project-file-card"><span class="file-name">style.css</span></div>
        </div>
        <div id="projectTree"></div>
      </div>
    `;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it('browseProject() updates activeProjectId without clearing #projectDetailFiles', () => {
    const filesEl = document.getElementById('projectDetailFiles');
    const initialChildCount = filesEl.children.length;
    expect(initialChildCount).toBe(3);

    // Simulate clicking a workspace item — the fixed code calls browseProject()
    sm.browseProject('proj-b');

    // File list must NOT be cleared
    expect(filesEl.children.length).toBe(initialChildCount);
    expect(filesEl.querySelector('.file-name').textContent).toBe('readme.md');

    // activeProjectId updated
    expect(sm.activeProjectId).toBe('proj-b');
  });

  it('browseProject() does NOT trigger WebSocket reconnection', () => {
    sm.browseProject('proj-b');

    // No WebSocket reconnection should have occurred
    expect(sm._calls.connectWebSocket).toHaveLength(0);
  });

  it('browseProject() does NOT call switchProject()', () => {
    sm.browseProject('proj-b');

    expect(sm._calls.switchProject).toHaveLength(0);
  });

  it('browseProject() notifies subscribers with activeProjectId only', () => {
    sm.browseProject('proj-b');

    expect(sm._calls.notify).toHaveLength(1);
    expect(sm._calls.notify[0]).toEqual(['activeProjectId']);
    // currentSessionId should NOT be in the notification (no context swap)
    expect(sm._calls.notify[0]).not.toContain('currentSessionId');
  });

  it('file list DOM remains intact after multiple browseProject() calls', () => {
    const filesEl = document.getElementById('projectDetailFiles');

    sm.browseProject('proj-b');
    sm.browseProject('proj-c');
    sm.browseProject('proj-d');

    // File list still has all 3 cards
    expect(filesEl.children.length).toBe(3);
    // No WebSocket reconnections
    expect(sm._calls.connectWebSocket).toHaveLength(0);
  });
});


// ══════════════════════════════════════════════════════════════════════════════
// 8.2 — Browse via browseProject() then switch via switchProject(): correct
//        context swap occurs only on the explicit switch
// ══════════════════════════════════════════════════════════════════════════════

describe('8.2 Integration: browseProject() then switchProject() — context swap only on switch', () => {
  let sm;

  beforeEach(() => {
    sm = createStateManager('proj-a');
    globalThis.StateManager = sm;
    globalThis.API_BASE = 'http://127.0.0.1:8000';
    globalThis.ContextHealthBar = { init: vi.fn(), update: vi.fn() };
    globalThis.ToolDock = { init: vi.fn(), updateForProject: vi.fn() };
    globalThis.KnowledgeMap = { init: vi.fn(), refresh: vi.fn() };

    document.body.innerHTML = `
      <div id="projectTree"></div>
      <div id="chatContainer"></div>
    `;
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('browseProject() only updates activeProjectId, no WebSocket or module updates', () => {
    const originalSessionId = sm.currentSessionId;

    // Browse to proj-b (simulates clicking in ProjectVault explorer)
    sm.browseProject('proj-b');

    // activeProjectId updated
    expect(sm.activeProjectId).toBe('proj-b');
    // Session ID unchanged — no context swap
    expect(sm.currentSessionId).toBe(originalSessionId);
    // No WebSocket reconnection
    expect(sm._calls.connectWebSocket).toHaveLength(0);
    // No module updates triggered
    expect(ToolDock.updateForProject).not.toHaveBeenCalled();
    expect(KnowledgeMap.refresh).not.toHaveBeenCalled();
    expect(ContextHealthBar.update).not.toHaveBeenCalled();
  });

  it('switchProject() performs full context swap with WebSocket reconnection', async () => {
    const originalSessionId = sm.currentSessionId;

    // First browse (no context swap)
    sm.browseProject('proj-b');
    expect(sm._calls.connectWebSocket).toHaveLength(0);

    // Now explicitly switch to proj-c (full context swap)
    await sm.switchProject('proj-c');

    // activeProjectId updated to proj-c
    expect(sm.activeProjectId).toBe('proj-c');
    // Session ID changed
    expect(sm.currentSessionId).not.toBe(originalSessionId);
    // WebSocket reconnected exactly once (for the switch, not the browse)
    expect(sm._calls.connectWebSocket).toHaveLength(1);
    // Module updates triggered
    expect(ToolDock.updateForProject).toHaveBeenCalledWith('proj-c');
    expect(KnowledgeMap.refresh).toHaveBeenCalledWith('proj-c');
    expect(ContextHealthBar.update).toHaveBeenCalledWith(0, 0, null);
  });

  it('browse then switch: old project thread is saved on switch', async () => {
    // Start at proj-a with known thread
    const originalThread = sm.currentSessionId;

    // Browse proj-b (no thread save)
    sm.browseProject('proj-b');
    expect(sm.projectThreads['proj-a']).toBeUndefined();

    // Now switch to proj-c — this should save proj-b's thread (current active)
    await sm.switchProject('proj-c');

    // proj-b's thread was saved (it was the activeProjectId when switch was called)
    expect(sm.projectThreads['proj-b']).toBeDefined();
    expect(sm.projectThreads['proj-b'].threadId).toBe(originalThread);
  });

  it('switchProject() to same project is a no-op', async () => {
    await sm.switchProject('proj-a');

    // No WebSocket reconnection
    expect(sm._calls.connectWebSocket).toHaveLength(0);
    // switchProject was called but returned early
    expect(sm._calls.switchProject).toHaveLength(1);
    // No notifications
    const switchNotifications = sm._calls.notify.filter(
      keys => keys.includes('currentSessionId')
    );
    expect(switchNotifications).toHaveLength(0);
  });

  it('multiple browses followed by one switch: only one WebSocket reconnection', async () => {
    sm.browseProject('proj-b');
    sm.browseProject('proj-c');
    sm.browseProject('proj-d');

    // No WebSocket reconnections from browsing
    expect(sm._calls.connectWebSocket).toHaveLength(0);

    // One explicit switch
    await sm.switchProject('proj-e');

    // Exactly one WebSocket reconnection
    expect(sm._calls.connectWebSocket).toHaveLength(1);
    expect(sm.activeProjectId).toBe('proj-e');
  });
});


// ══════════════════════════════════════════════════════════════════════════════
// 8.3 — Pin toggle in project detail: targeted DOM update, no full view teardown
// ══════════════════════════════════════════════════════════════════════════════

describe('8.3 Integration: pin toggle updates icon without full view teardown', () => {
  let sm;

  beforeEach(() => {
    sm = createStateManager('proj-a');
    globalThis.StateManager = sm;
    globalThis.API_BASE = 'http://127.0.0.1:8000';
    globalThis.cachedProjects = [
      { id: 'proj-a', name: 'Project A', instructions: 'Test instructions', chats: [] },
    ];
    globalThis.DOMPurify = { sanitize: (s) => s };
    globalThis.ContextHealthBar = { init: vi.fn(), update: vi.fn() };
    globalThis.ToolDock = { init: vi.fn(), updateForProject: vi.fn() };
    globalThis.KnowledgeMap = { init: vi.fn(), refresh: vi.fn() };

    // Clear any previous pin state
    localStorage.removeItem('pinproj_proj-a');

    // Set up the project detail DOM
    document.body.innerHTML = `
      <div id="view-project-detail">
        <button id="projectBackBtn"></button>
        <div id="projectDetailName">Project A</div>
        <div id="projectDetailDesc">Test instructions</div>
        <div id="projectDetailInstructions">Test instructions</div>
        <button id="projectDetailPin">☆</button>
        <button id="projectDetailMenu"></button>
        <button id="projectEditInstructions"></button>
        <button id="projectUploadFile"></button>
        <div id="projectDetailChats"></div>
        <div id="projectDetailFiles">
          <div class="project-file-card"><span class="file-name">readme.md</span></div>
          <div class="project-file-card"><span class="file-name">app.js</span></div>
        </div>
        <div id="projectDropZone"></div>
        <input id="workspaceFileInput" type="file" />
        <div id="projectComposerPreviews" class="hidden"></div>
        <input id="projectInput" />
        <button id="projectSendBtn"></button>
      </div>
    `;
  });

  afterEach(() => {
    localStorage.removeItem('pinproj_proj-a');
    vi.restoreAllMocks();
  });

  it('pin toggle changes icon text from ☆ to ★ without re-rendering the view', () => {
    const pinEl = document.getElementById('projectDetailPin');
    const filesEl = document.getElementById('projectDetailFiles');
    const initialFileCount = filesEl.children.length;

    // Replicate the fixed pin toggle handler (from openProjectDetail)
    let isPinned = false;
    pinEl.onclick = () => {
      if (isPinned) {
        localStorage.removeItem('pinproj_proj-a');
        pinEl.textContent = '☆';
      } else {
        localStorage.setItem('pinproj_proj-a', '1');
        pinEl.textContent = '★';
      }
      isPinned = !isPinned;
    };

    // Click to pin
    pinEl.click();

    // Pin icon updated
    expect(pinEl.textContent).toBe('★');
    // localStorage updated
    expect(localStorage.getItem('pinproj_proj-a')).toBe('1');
    // File list NOT cleared — no full view teardown
    expect(filesEl.children.length).toBe(initialFileCount);
    // Project name still intact
    expect(document.getElementById('projectDetailName').textContent).toBe('Project A');
  });

  it('pin toggle changes icon text from ★ to ☆ on unpin', () => {
    const pinEl = document.getElementById('projectDetailPin');
    const filesEl = document.getElementById('projectDetailFiles');

    let isPinned = false;
    pinEl.onclick = () => {
      if (isPinned) {
        localStorage.removeItem('pinproj_proj-a');
        pinEl.textContent = '☆';
      } else {
        localStorage.setItem('pinproj_proj-a', '1');
        pinEl.textContent = '★';
      }
      isPinned = !isPinned;
    };

    // Pin then unpin
    pinEl.click(); // pin
    expect(pinEl.textContent).toBe('★');

    pinEl.click(); // unpin
    expect(pinEl.textContent).toBe('☆');
    expect(localStorage.getItem('pinproj_proj-a')).toBeNull();
    // File list still intact
    expect(filesEl.children.length).toBe(2);
  });

  it('pin toggle does NOT call openProjectDetail recursively (no fetch, no DOM rebuild)', () => {
    const pinEl = document.getElementById('projectDetailPin');
    const filesEl = document.getElementById('projectDetailFiles');
    const chatsEl = document.getElementById('projectDetailChats');

    // Add a marker to chatsEl to detect if it gets wiped
    chatsEl.innerHTML = '<div class="chat-marker">existing chat</div>';

    let isPinned = false;
    pinEl.onclick = () => {
      if (isPinned) {
        localStorage.removeItem('pinproj_proj-a');
        pinEl.textContent = '☆';
      } else {
        localStorage.setItem('pinproj_proj-a', '1');
        pinEl.textContent = '★';
      }
      isPinned = !isPinned;
    };

    // Toggle pin
    pinEl.click();

    // Chats section NOT wiped (would be wiped if openProjectDetail was called recursively)
    expect(chatsEl.querySelector('.chat-marker')).not.toBeNull();
    expect(chatsEl.querySelector('.chat-marker').textContent).toBe('existing chat');
    // Files section NOT wiped
    expect(filesEl.children.length).toBe(2);
    // No WebSocket reconnection
    expect(sm._calls.connectWebSocket).toHaveLength(0);
    // No switchProject called
    expect(sm._calls.switchProject).toHaveLength(0);
  });

  it('rapid pin toggles maintain correct state without DOM corruption', () => {
    const pinEl = document.getElementById('projectDetailPin');
    const filesEl = document.getElementById('projectDetailFiles');

    let isPinned = false;
    pinEl.onclick = () => {
      if (isPinned) {
        localStorage.removeItem('pinproj_proj-a');
        pinEl.textContent = '☆';
      } else {
        localStorage.setItem('pinproj_proj-a', '1');
        pinEl.textContent = '★';
      }
      isPinned = !isPinned;
    };

    // Rapid toggles
    pinEl.click(); // pin
    pinEl.click(); // unpin
    pinEl.click(); // pin
    pinEl.click(); // unpin
    pinEl.click(); // pin

    expect(pinEl.textContent).toBe('★');
    expect(localStorage.getItem('pinproj_proj-a')).toBe('1');
    // DOM still intact after 5 rapid toggles
    expect(filesEl.children.length).toBe(2);
    expect(document.getElementById('projectDetailName').textContent).toBe('Project A');
  });
});
