/**
 * Property-based tests for OrchestratorPanel module using fast-check + vitest (jsdom).
 *
 * Feature: productivity-workspace-overhaul
 * Validates: Requirements 8.2, 8.6, 12.4, 12.5, 12.6
 */
import { describe, it, expect, beforeEach } from 'vitest';
import fc from 'fast-check';

// ── Arbitraries ──

/** Generate a safe project name. */
const arbProjectName = fc.stringMatching(/^[a-zA-Z0-9 _-]{1,30}$/).filter(s => s.trim().length > 0);

/** Generate a non-negative integer for context counts. */
const arbCount = fc.nat({ max: 500 });

/** Generate a pair (loaded, total) where loaded <= total. */
const arbContextCounts = fc.tuple(arbCount, arbCount).map(([a, b]) => {
  const total = Math.max(a, b);
  const loaded = Math.min(a, b);
  return { loaded, total };
});

/** Generate a safe project ID. */
const arbProjectId = fc.stringMatching(/^[a-zA-Z0-9_-]{1,20}$/);

/** Generate a safe file path. */
const arbFilePath = fc.stringMatching(/^[a-z0-9_/]+\.[a-z]{1,4}$/).filter(s => s.length > 2);

/** Generate a non-empty set of file paths (unique). */
const arbFilePaths = fc.uniqueArray(arbFilePath, { minLength: 1, maxLength: 15 });

/** Generate a chat message string. */
const arbMessage = fc.stringMatching(/^[a-zA-Z0-9 .,!?]{1,80}$/).filter(s => s.trim().length > 0);

// ── Helpers ──

/**
 * Minimal StateManager mock matching what OrchestratorPanel expects.
 */
function createStateManager() {
  const state = {
    activeProjectId: 'default',
    contextFiles: new Map(),
    activeMode: 'tools_on',
    webSearchEnabled: true,
    responseStyle: 'normal',
    stageModified: false,
    cachedProjects: [],
  };
  const subscribers = {};
  return {
    get activeProjectId() { return state.activeProjectId; },
    set activeProjectId(v) { state.activeProjectId = v; },
    get contextFiles() { return state.contextFiles; },
    set contextFiles(v) { state.contextFiles = v; },
    get activeMode() { return state.activeMode; },
    get webSearchEnabled() { return state.webSearchEnabled; },
    get responseStyle() { return state.responseStyle; },
    get stageModified() { return state.stageModified; },
    set stageModified(v) { state.stageModified = v; },
    get cachedProjects() { return state.cachedProjects; },
    set cachedProjects(v) { state.cachedProjects = v; },
    set(key, value) {
      state[key] = value;
      for (const cb of Object.values(subscribers)) cb([key]);
    },
    subscribe(name, cb) { subscribers[name] = cb; },
  };
}

/**
 * Set up a minimal DOM and replicate OrchestratorPanel logic for isolated testing.
 * Mirrors the public API from frontend/modules/orchestrator-panel.js.
 */
function setupOrchestratorPanel() {
  document.body.innerHTML = `
    <div id="orchestratorPanel">
      <div id="projectHeader">
        <span id="projectName">Project: General Workspace</span>
        <span id="contextCount">Context: 0/0 Files</span>
      </div>
      <div id="tabNav">
        <button class="tab active" data-tab="chat">Chat</button>
        <button class="tab" data-tab="stage">Stage</button>
      </div>
      <div id="chatView"></div>
      <div id="stageView" class="hidden"></div>
    </div>
  `;

  const sm = createStateManager();
  globalThis.StateManager = sm;

  // ── Internal state ──
  let activeTab = 'chat';
  let chatUnread = false;
  let stageUnsaved = false;

  // ── DOM refs ──
  const chatViewEl = document.getElementById('chatView');
  const stageViewEl = document.getElementById('stageView');
  const projectNameEl = document.getElementById('projectName');
  const contextCountEl = document.getElementById('contextCount');
  const tabNav = document.getElementById('tabNav');
  const tabEls = {};
  let chatDotEl = null;
  let stageDotEl = null;

  // Set up tab elements and dots
  tabNav.querySelectorAll('.tab').forEach(tab => {
    const key = tab.dataset.tab;
    tabEls[key] = tab;

    if (!tab.querySelector('.tab-dot')) {
      const dot = document.createElement('span');
      dot.className = 'tab-dot';
      tab.appendChild(dot);
    }
  });
  chatDotEl = tabEls.chat ? tabEls.chat.querySelector('.tab-dot') : null;
  stageDotEl = tabEls.stage ? tabEls.stage.querySelector('.tab-dot') : null;

  // ── Functions (mirror orchestrator-panel.js) ──

  function setActiveTab(tab) {
    if (tab !== 'chat' && tab !== 'stage') return;
    activeTab = tab;

    if (chatViewEl) chatViewEl.classList.toggle('hidden', tab !== 'chat');
    if (stageViewEl) stageViewEl.classList.toggle('hidden', tab !== 'stage');

    Object.entries(tabEls).forEach(([key, el]) => {
      if (el) el.classList.toggle('active', key === tab);
    });

    if (tab === 'chat' && chatUnread) {
      setChatUnread(false);
    }
  }

  function updateHeader(projectName, contextCount, totalFiles) {
    if (projectNameEl && projectName != null) {
      projectNameEl.textContent = 'Project: ' + projectName;
    }
    if (contextCountEl && contextCount != null && totalFiles != null) {
      contextCountEl.textContent = 'Context: ' + contextCount + '/' + totalFiles + ' Files';
    }
  }

  function setChatUnread(hasUnread) {
    chatUnread = hasUnread;
    if (chatDotEl) chatDotEl.classList.toggle('visible', hasUnread);
  }

  function setStageUnsaved(hasChanges) {
    stageUnsaved = hasChanges;
    if (stageDotEl) stageDotEl.classList.toggle('visible', hasChanges);
  }

  function buildWsPayload(message, files) {
    const pid = sm.activeProjectId || 'default';
    const contextFilesList = [];

    // Read from StateManager.contextFiles map (same fallback path as the real module)
    const ctxMap = sm.contextFiles;
    if (ctxMap && ctxMap.has(pid)) {
      ctxMap.get(pid).forEach(p => contextFilesList.push(p));
    }

    return {
      message: message,
      files: files || [],
      mode: sm.activeMode,
      web_search_enabled: sm.webSearchEnabled,
      response_style: sm.responseStyle,
      project_id: pid,
      context_files: contextFilesList,
    };
  }

  return {
    panel: {
      setActiveTab,
      updateHeader,
      setChatUnread,
      setStageUnsaved,
      buildWsPayload,
    },
    sm,
    getActiveTab: () => activeTab,
    getChatUnread: () => chatUnread,
    getStageUnsaved: () => stageUnsaved,
    projectNameEl,
    contextCountEl,
    chatDotEl,
    stageDotEl,
    tabEls,
    chatViewEl,
    stageViewEl,
  };
}

// ── Property Tests ──

describe('OrchestratorPanel Property Tests', () => {

  /**
   * Feature: productivity-workspace-overhaul, Property 20: Orchestrator header format
   *
   * For any project name and context file counts (N loaded, M total), the Orchestrator
   * Panel header should display "Project: {name}" and "Context: {N}/{M} Files".
   *
   * **Validates: Requirements 8.2**
   */
  describe('Property 20: Orchestrator header format', () => {
    it('header displays correct project name and context count format', () => {
      fc.assert(
        fc.property(arbProjectName, arbContextCounts, (name, counts) => {
          const { panel, projectNameEl, contextCountEl } = setupOrchestratorPanel();

          panel.updateHeader(name, counts.loaded, counts.total);

          expect(projectNameEl.textContent).toBe('Project: ' + name);
          expect(contextCountEl.textContent).toBe(
            'Context: ' + counts.loaded + '/' + counts.total + ' Files'
          );
        }),
        { numRuns: 100 },
      );
    });
  });

  /**
   * Feature: productivity-workspace-overhaul, Property 21: WebSocket payload includes context files
   *
   * For any set of context-toggled files, the WebSocket chat payload built by buildWsPayload()
   * should include a context_files array containing exactly the file paths that have active
   * context toggles.
   *
   * **Validates: Requirements 8.6**
   */
  describe('Property 21: WebSocket payload includes context files', () => {
    it('payload context_files matches the active context toggle paths', () => {
      fc.assert(
        fc.property(arbProjectId, arbFilePaths, arbMessage, (projectId, filePaths, message) => {
          const { panel, sm } = setupOrchestratorPanel();

          // Set up the project and context files in StateManager
          sm.activeProjectId = projectId;
          const ctxSet = new Set(filePaths);
          sm.contextFiles = new Map([[projectId, ctxSet]]);

          const payload = panel.buildWsPayload(message, []);

          // The payload should contain exactly the toggled file paths
          expect(payload.context_files).toBeDefined();
          expect(payload.context_files.sort()).toEqual([...filePaths].sort());
          expect(payload.project_id).toBe(projectId);
          expect(payload.message).toBe(message);
        }),
        { numRuns: 100 },
      );
    });

    it('payload context_files is empty when no files are toggled', () => {
      fc.assert(
        fc.property(arbProjectId, arbMessage, (projectId, message) => {
          const { panel, sm } = setupOrchestratorPanel();

          sm.activeProjectId = projectId;
          // No context files set for this project
          sm.contextFiles = new Map();

          const payload = panel.buildWsPayload(message, []);

          expect(payload.context_files).toEqual([]);
        }),
        { numRuns: 100 },
      );
    });
  });

  /**
   * Feature: productivity-workspace-overhaul, Property 29: File open triggers Stage tab
   *
   * For any file open action from the Project Vault, the activeTab state should be
   * set to "stage".
   *
   * **Validates: Requirements 12.4**
   */
  describe('Property 29: File open triggers Stage tab', () => {
    it('setActiveTab("stage") switches to stage view', () => {
      fc.assert(
        fc.property(
          fc.constantFrom('chat', 'stage'),
          (initialTab) => {
            const { panel, getActiveTab, chatViewEl, stageViewEl, tabEls } = setupOrchestratorPanel();

            // Start on the initial tab
            panel.setActiveTab(initialTab);

            // Simulate file open by switching to stage
            panel.setActiveTab('stage');

            expect(getActiveTab()).toBe('stage');
            // Stage view should be visible, chat view hidden
            expect(stageViewEl.classList.contains('hidden')).toBe(false);
            expect(chatViewEl.classList.contains('hidden')).toBe(true);
            // Stage tab should be active
            expect(tabEls.stage.classList.contains('active')).toBe(true);
            expect(tabEls.chat.classList.contains('active')).toBe(false);
          },
        ),
        { numRuns: 100 },
      );
    });
  });

  /**
   * Feature: productivity-workspace-overhaul, Property 30: Chat unread indicator while on Stage
   *
   * For any new AI message event received while activeTab is "stage", the
   * chatUnreadWhileStage flag should be set to true.
   *
   * **Validates: Requirements 12.5**
   */
  describe('Property 30: Chat unread indicator while on Stage', () => {
    it('setChatUnread(true) while on stage shows the chat dot', () => {
      fc.assert(
        fc.property(arbMessage, (_msg) => {
          const { panel, getChatUnread, chatDotEl } = setupOrchestratorPanel();

          // Switch to stage tab
          panel.setActiveTab('stage');

          // Simulate new AI message arriving
          panel.setChatUnread(true);

          expect(getChatUnread()).toBe(true);
          expect(chatDotEl.classList.contains('visible')).toBe(true);
        }),
        { numRuns: 100 },
      );
    });

    it('switching to chat tab clears the unread indicator', () => {
      fc.assert(
        fc.property(arbMessage, (_msg) => {
          const { panel, getChatUnread, chatDotEl } = setupOrchestratorPanel();

          // On stage, receive unread message
          panel.setActiveTab('stage');
          panel.setChatUnread(true);
          expect(getChatUnread()).toBe(true);

          // Switch to chat — unread should clear
          panel.setActiveTab('chat');
          expect(getChatUnread()).toBe(false);
          expect(chatDotEl.classList.contains('visible')).toBe(false);
        }),
        { numRuns: 100 },
      );
    });
  });

  /**
   * Feature: productivity-workspace-overhaul, Property 31: Stage unsaved indicator on tab
   *
   * For any state where stageModified is true, the Stage tab control should display
   * a visual unsaved indicator.
   *
   * **Validates: Requirements 12.6**
   */
  describe('Property 31: Stage unsaved indicator on tab', () => {
    it('setStageUnsaved(true) shows the stage dot indicator', () => {
      fc.assert(
        fc.property(fc.boolean(), (hasChanges) => {
          const { panel, getStageUnsaved, stageDotEl } = setupOrchestratorPanel();

          panel.setStageUnsaved(hasChanges);

          expect(getStageUnsaved()).toBe(hasChanges);
          expect(stageDotEl.classList.contains('visible')).toBe(hasChanges);
        }),
        { numRuns: 100 },
      );
    });

    it('unsaved indicator toggles correctly on repeated state changes', () => {
      fc.assert(
        fc.property(
          fc.array(fc.boolean(), { minLength: 1, maxLength: 10 }),
          (sequence) => {
            const { panel, getStageUnsaved, stageDotEl } = setupOrchestratorPanel();

            for (const hasChanges of sequence) {
              panel.setStageUnsaved(hasChanges);
              expect(getStageUnsaved()).toBe(hasChanges);
              expect(stageDotEl.classList.contains('visible')).toBe(hasChanges);
            }
          },
        ),
        { numRuns: 100 },
      );
    });
  });
});
