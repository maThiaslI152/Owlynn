/**
 * OrchestratorPanel — IIFE module for the center column orchestrator.
 * Manages tab switching (Chat/Stage), project header, unread/unsaved dots,
 * and extends the WS payload with context_files.
 *
 * Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 12.1, 12.2, 12.3, 12.4, 12.5, 12.6
 */
window.OrchestratorPanel = (() => {
  // ── State ──
  let activeTab = 'chat'; // 'chat' | 'stage'
  let chatUnread = false;
  let stageUnsaved = false;

  // ── DOM refs (cached on init) ──
  let chatViewEl = null;
  let stageViewEl = null;
  let projectNameEl = null;
  let contextCountEl = null;
  let tabEls = {};   // { chat: HTMLElement, stage: HTMLElement }
  let chatDotEl = null;
  let stageDotEl = null;

  // ── Tab switching ──
  function setActiveTab(tab) {
    if (tab !== 'chat' && tab !== 'stage') return;
    activeTab = tab;

    // Show/hide views
    if (chatViewEl) chatViewEl.classList.toggle('hidden', tab !== 'chat');
    if (stageViewEl) stageViewEl.classList.toggle('hidden', tab !== 'stage');

    // Also ensure the bottomBar stays visible regardless of tab
    var bottomBar = document.getElementById('bottomBar');
    if (bottomBar) bottomBar.classList.toggle('hidden', tab === 'stage');

    // Update tab active class
    Object.entries(tabEls).forEach(([key, el]) => {
      if (el) el.classList.toggle('active', key === tab);
    });

    // Clear unread dot when switching to chat
    if (tab === 'chat' && chatUnread) {
      setChatUnread(false);
    }
  }

  // ── Header updates ──
  function updateHeader(projectName, contextCount, totalFiles) {
    if (projectNameEl && projectName != null) {
      projectNameEl.textContent = 'Project: ' + projectName;
    }
    if (contextCountEl && contextCount != null && totalFiles != null) {
      contextCountEl.textContent = 'Context: ' + contextCount + '/' + totalFiles + ' Files';
    }
  }

  // ── Notification dots ──
  function setChatUnread(hasUnread) {
    chatUnread = hasUnread;
    if (chatDotEl) chatDotEl.classList.toggle('visible', hasUnread);
  }

  function setStageUnsaved(hasChanges) {
    stageUnsaved = hasChanges;
    if (stageDotEl) stageDotEl.classList.toggle('visible', hasChanges);
  }

  // ── WS payload builder ──
  function buildWsPayload(message, files) {
    const pid = StateManager.activeProjectId || 'default';
    const contextFilesList = [];

    // Gather active context files from ProjectVault or StateManager
    if (window.ProjectVault && typeof ProjectVault.getContextFiles === 'function') {
      const paths = ProjectVault.getContextFiles(pid);
      if (paths && paths.length) contextFilesList.push(...paths);
    } else {
      // Fallback: read from StateManager.contextFiles map
      const ctxMap = StateManager.contextFiles;
      if (ctxMap && ctxMap.has(pid)) {
        ctxMap.get(pid).forEach(p => contextFilesList.push(p));
      }
    }

    return {
      message: message,
      files: files || [],
      mode: StateManager.activeMode,
      web_search_enabled: StateManager.webSearchEnabled,
      response_style: StateManager.responseStyle,
      project_id: pid,
      context_files: contextFilesList,
    };
  }

  // ── Header sync helper ──
  function _syncHeader() {
    const pid = StateManager.activeProjectId || 'default';
    const projects = StateManager.cachedProjects || [];
    const proj = projects.find(p => p.id === pid);
    const name = proj ? proj.name : 'General Workspace';

    // Count context files vs total files
    const ctxMap = StateManager.contextFiles;
    const ctxCount = (ctxMap && ctxMap.has(pid)) ? ctxMap.get(pid).size : 0;

    // Total files: try ProjectVault's internal data or fall back to 0
    let totalFiles = 0;
    if (window.ProjectVault && typeof ProjectVault.getContextFiles === 'function') {
      // We can't easily get total from ProjectVault, so use a rough approach
      // Check if project files are cached in the vault
    }
    // Use the project's files array length if available
    if (proj && proj.files) {
      totalFiles = proj.files.length;
    }

    updateHeader(name, ctxCount, totalFiles);
  }

  // ── Init ──
  function init() {
    // Cache DOM refs
    chatViewEl = document.getElementById('chatView');
    stageViewEl = document.getElementById('stageView');
    projectNameEl = document.getElementById('projectName');
    contextCountEl = document.getElementById('contextCount');

    const tabNav = document.getElementById('tabNav');
    if (tabNav) {
      tabNav.querySelectorAll('.tab').forEach(tab => {
        const key = tab.dataset.tab;
        tabEls[key] = tab;

        // Inject dot element if not present
        if (!tab.querySelector('.tab-dot')) {
          const dot = document.createElement('span');
          dot.className = 'tab-dot';
          tab.appendChild(dot);
        }

        // Click handler
        tab.addEventListener('click', () => setActiveTab(key));
      });

      chatDotEl = tabEls.chat ? tabEls.chat.querySelector('.tab-dot') : null;
      stageDotEl = tabEls.stage ? tabEls.stage.querySelector('.tab-dot') : null;
    }

    // Subscribe to state changes
    StateManager.subscribe('OrchestratorPanel', (changedKeys) => {
      if (changedKeys.includes('activeProjectId') || changedKeys.includes('cachedProjects')) {
        _syncHeader();
      }
      if (changedKeys.includes('contextFiles')) {
        _syncHeader();
      }
      if (changedKeys.includes('stageModified')) {
        setStageUnsaved(!!StateManager.stageModified);
      }
    });

    // Initial header sync
    _syncHeader();
  }

  // ── Public API ──
  return {
    init,
    setActiveTab,
    updateHeader,
    setChatUnread,
    setStageUnsaved,
    buildWsPayload,
  };
})();
