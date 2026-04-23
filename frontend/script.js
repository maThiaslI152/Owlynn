// ─── StateManager Module ───────────────────────────────────────────────────
// Centralized state management for the Owlynn frontend.
// Implements a subscribe/notify pattern so UI components react to state changes.
//
// Core responsibilities:
//   - WebSocket lifecycle (connect, reconnect with exponential backoff, message dispatch)
//   - Project switching (save/restore thread IDs, scroll positions, module updates)
//   - Settings sync (apply profile from /api/unified-settings)
//   - Message sending (builds WS payload with mode, style, project context)
//
// All UI modules (LeftPane, Explorer, OrchestratorPanel, KnowledgeMap, Stage)
// subscribe to StateManager and react to specific changed keys.
const StateManager = (() => {
  // ── Subscribers ──
  const _subscribers = [];

  // ── WebSocket reconnection state ──
  let _reconnectAttempt = 0;
  let _reconnectTimer = null;

  // ── UUID Generator ──
  function generateUUID() {
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function (c) {
      const r = (Math.random() * 16) | 0;
      const v = c === 'x' ? r : (r & 0x3) | 0x8;
      return v.toString(16);
    });
  }

  // ── State Object ──
  const state = {
    currentSessionId: generateUUID(),
    currentView: 'home',
    activeProjectId: null,
    hasSentMessage: false,
    activeMode: 'tools_on',
    webSearchEnabled: true,
    responseStyle: 'normal',
    currentModelUsed: 'unknown',
    socket: null,
    isStreaming: false,
    connectionStatus: 'offline',
    userName: 'User',
    avatarInitial: 'U',
    contentPreview: {
      isOpen: false,
      layoutMode: 'closed',
      currentArtifact: null,
      isEditMode: false,
      editedContent: null,
      hasUnsavedChanges: false,
    },
    cachedProjects: [],
    cachedChats: [],
    contextFiles: new Map(),
    projectThreads: {},  // Map<projectId, { threadId, scrollPos }>
  };

  return {
    // ── Direct state access ──
    get currentSessionId() { return state.currentSessionId; },
    get currentView() { return state.currentView; },
    get activeProjectId() { return state.activeProjectId; },
    get hasSentMessage() { return state.hasSentMessage; },
    get activeMode() { return state.activeMode; },
    get webSearchEnabled() { return state.webSearchEnabled; },
    get responseStyle() { return state.responseStyle; },
    get currentModelUsed() { return state.currentModelUsed; },
    get socket() { return state.socket; },
    get isStreaming() { return state.isStreaming; },
    get connectionStatus() { return state.connectionStatus; },
    get userName() { return state.userName; },
    get avatarInitial() { return state.avatarInitial; },
    get contentPreview() { return state.contentPreview; },
    get cachedProjects() { return state.cachedProjects; },
    get cachedChats() { return state.cachedChats; },
    get contextFiles() { return state.contextFiles; },
    get projectThreads() { return state.projectThreads; },

    /**
     * Subscribe to state changes.
     * @param {string} componentName - Identifier for the subscriber (for debugging).
     * @param {function} callback - Called with an array of changed key names.
     */
    subscribe(componentName, callback) {
      _subscribers.push({ componentName, callback });
    },

    /**
     * Notify all subscribers about changed keys.
     * @param {string[]} changedKeys - State keys that changed.
     */
    notify(changedKeys) {
      for (const sub of _subscribers) {
        try {
          sub.callback(changedKeys);
        } catch (_err) {
          // Subscriber errors are intentionally silenced to prevent one broken
          // module from cascading failures to other subscribers.
        }
      }
    },

    /**
     * Update a single state property and notify subscribers.
     * Plain state update — no interception or side-effects.
     * @param {string} key - The state key to update.
     * @param {*} value - The new value.
     */
    set(key, value) {
      if (!(key in state)) {
        return;
      }
      state[key] = value;
      this.notify([key]);
    },

    /**
     * Browse a project for UI highlighting without performing a full context swap.
     * Updates activeProjectId and notifies subscribers so the UI can highlight
     * the selected project, but does NOT reconnect WebSocket, load chat history,
     * or trigger module updates (ToolDock, KnowledgeMap, etc.).
     * @param {string} projectId - The project ID to browse.
     */
    browseProject(projectId) {
      if (projectId === state.activeProjectId) return;
      state.activeProjectId = projectId;
      this.notify(['activeProjectId']);
    },

    /**
     * Navigate to a new view and notify subscribers.
     * @param {string} viewName - One of: 'home','chat','projects','project-detail','customize','chats'.
     * @param {object} [context={}] - Optional context (e.g. { projectId, threadId }).
     */
    navigate(viewName, context = {}) {
      state.currentView = viewName;
      if (context.projectId !== undefined && context.projectId !== state.activeProjectId) {
        // Delegate to switchProject for full context swap
        this.switchProject(context.projectId);
        this.notify(['currentView']);
      } else {
        this.notify(['currentView', 'activeProjectId']);
      }
    },

    /**
     * Generate a UUID v4 string.
     * @returns {string}
     */
    generateUUID,

    /**
     * Apply settings from /api/unified-settings response.
     * @param {object} settings - The settings object from the API.
     */
    applySettings(settings) {
      if (!settings) return;
      const changed = [];
      if (settings.name != null) {
        state.userName = settings.name;
        state.avatarInitial = settings.name ? settings.name[0].toUpperCase() : 'U';
        changed.push('userName', 'avatarInitial');
      }
      if (settings.response_style != null) {
        state.responseStyle = settings.response_style;
        changed.push('responseStyle');
      }
      if (changed.length > 0) {
        this.notify(changed);
      }
    },

    /**
     * Connect a WebSocket to the backend for the given thread.
     * Closes any existing socket before opening a new one.
     * @param {string} threadId - The chat thread ID to connect to.
     */
    connectWebSocket(threadId) {
      const isTauri = Boolean(window.__TAURI__ || location.protocol === 'tauri:');
      const wsBase = isTauri ? 'ws://127.0.0.1:8000' : 'ws://' + location.host;

      // Close existing socket if open
      if (state.socket && (state.socket.readyState === WebSocket.OPEN || state.socket.readyState === WebSocket.CONNECTING)) {
        state.socket.close();
      }
      // Clear any pending reconnect timer
      if (_reconnectTimer) {
        clearTimeout(_reconnectTimer);
        _reconnectTimer = null;
      }

      const ws = new WebSocket(`${wsBase}/ws/chat/${threadId}`);

      ws.onopen = () => {
        state.connectionStatus = 'online';
        // Only reset backoff after connection is stable for 5 seconds
        // This prevents rapid reconnect loops when server immediately closes
        ws._stableTimer = setTimeout(() => {
          _reconnectAttempt = 0;
        }, 5000);
        this.notify(['connectionStatus']);
      };

      ws.onclose = (event) => {
        if (ws._stableTimer) clearTimeout(ws._stableTimer);
        // Don't auto-reconnect if close was intentional (code 1000) or
        // if this socket was replaced by a newer one
        if (event.code === 1000 || state.socket !== ws) return;
        state.connectionStatus = 'connecting';
        this.notify(['connectionStatus']);
        this._reconnect(threadId);
      };

      ws.onerror = () => {
        if (ws._stableTimer) clearTimeout(ws._stableTimer);
        state.connectionStatus = 'offline';
        this.notify(['connectionStatus']);
      };

      ws.onmessage = (event) => {
        this.handleWebSocketMessage(event);
      };

      state.socket = ws;
      this.notify(['socket']);
    },

    /**
     * Private reconnection with exponential backoff.
     * @param {string} threadId - The thread ID to reconnect to.
     */
    _reconnect(threadId) {
      const delay = Math.min(Math.pow(2, _reconnectAttempt) * 1000, 30000);
      _reconnectAttempt++;
      _reconnectTimer = setTimeout(() => {
        this.connectWebSocket(threadId);
      }, delay);
    },

    /**
     * Handle an incoming WebSocket message.
     * Placeholder — will be fully implemented in task 11.1.
     * @param {MessageEvent} event - The WebSocket message event.
     */
    handleWebSocketMessage(event) {
      try {
        const data = JSON.parse(event.data);
        switch (data.type) {
          case 'status':
            if (data.content === 'reasoning') {
              state.isStreaming = true;
              state._lastRouterInfoKey = null;
              state._lastModelBadgeRendered = null;
              this.notify(['isStreaming']);
              LeftPane.showThinkingIndicator();
            } else if (data.content === 'idle') {
              state.isStreaming = false;
              this.notify(['isStreaming']);
              LeftPane.clearThinkingIndicator();
              LeftPane.finalizeAiMessage();
              LeftPane.pruneMessages();
            }
            break;
          case 'chunk':
            LeftPane.appendChunk(data.content);
            // Notify OrchestratorPanel of unread chat while on Stage
            if (window.OrchestratorPanel && typeof OrchestratorPanel.setChatUnread === 'function') {
              OrchestratorPanel.setChatUnread(true);
            }
            if (data.metadata && data.metadata.budget_remaining != null) {
              const el = document.getElementById('sessionTokenUsage');
              if (el) {
                const pct = Math.round(data.metadata.budget_remaining * 100);
                const cls = pct > 50 ? 'budget-normal' : pct > 20 ? 'budget-warning' : 'budget-critical';
                el.className = `token-budget-indicator ${cls}`;
                el.textContent = `${pct}% budget`;
              }
            }
            break;
          case 'message':
            {
            const msgPayload = data.message || data;
            // Tool-originated messages are represented via tool_execution cards.
            if (msgPayload && msgPayload.type === 'tool') break;
            // Skip if this AI message was already rendered via chunk streaming
            if (msgPayload.type === 'ai' && LeftPane.mode === 'chat' && LeftPane.messages.length > 0) {
              const lastMsg = LeftPane.messages[LeftPane.messages.length - 1];
              if (lastMsg && lastMsg.role === 'ai') break; // Already rendered via chunks
            }
            LeftPane.renderMessage(msgPayload);
            break;
            }
          case 'error':
            LeftPane.renderError(data.content || data.message || 'Unknown error');
            break;
          case 'tool_execution':
            LeftPane.renderToolCard(data.tool_name, data.status, data.input, data.output, data.error, data.tool_call_id);
            if (data.status === 'success' && data.output && typeof ContentPreviewPanel !== 'undefined') {
              const artifact = ContentPreviewPanel.detectArtifactFromToolOutput(data.tool_name, data.tool_call_id, data.output);
              if (artifact) LeftPane.renderPreviewTrigger && LeftPane.renderPreviewTrigger(artifact);
            }
            break;
          case 'file_status':
            RightPane.updateFileStatus(data.name, data.status);
            break;
          case 'model_info':
            // Only render model badge once per message (skip if already shown)
            if (!state._lastModelBadgeRendered || state._lastModelBadgeRendered !== data.model) {
              LeftPane.renderModelBadge(data.model, data.token_usage);
              state._lastModelBadgeRendered = data.model;
            }
            state.currentModelUsed = data.model || 'unknown';
            if (data.swapping) LeftPane.showSwapIndicator(data.model);
            else LeftPane.hideSwapIndicator();
            if (data.fallback_chain) LeftPane.renderFallbackChain(data.fallback_chain);
            // Update ContextHealthBar with model context window size
            if (window.ContextHealthBar && data.context_window) {
              ContextHealthBar.update(null, null, data.context_window);
            }
            break;
          case 'router_info':
            // Only render router info once per route (deduplicate repeated events)
            {
              const routeKey = `${data.metadata?.route}-${Math.round((data.metadata?.confidence || 0) * 100)}`;
              if (!state._lastRouterInfoKey || state._lastRouterInfoKey !== routeKey) {
                LeftPane.renderRouterInfo(data.metadata);
                state._lastRouterInfoKey = routeKey;
              }
            }
            break;
          case 'token_budget_update': {
            const el = document.getElementById('sessionTokenUsage');
            if (el) {
              el.className = 'token-budget-indicator budget-normal';
              el.textContent = `${data.total_tokens || ''} tokens used`;
            }
            // Update ContextHealthBar with active token count
            if (window.ContextHealthBar) {
              ContextHealthBar.update(data.active_tokens || data.total_tokens || 0, null, null);
            }
            break;
          }
          case 'cloud_budget_warning': {
            const banner = document.createElement('div');
            banner.className = `cloud-budget-warning level-${data.level || 'info'}`;
            banner.textContent = data.message || 'Cloud budget warning';
            const shell = document.getElementById('auroraShell');
            if (shell) shell.insertBefore(banner, shell.children[1]);
            setTimeout(() => banner.remove(), 8000);
            break;
          }
          case 'memory_updated': {
            const notif = document.createElement('div');
            notif.className = 'aurora-notification';
            notif.textContent = '🧠 Memory updated';
            document.body.appendChild(notif);
            setTimeout(() => notif.remove(), 3000);
            // Refresh KnowledgeMap on memory update
            if (window.KnowledgeMap && typeof KnowledgeMap.handleMemoryUpdate === 'function') {
              KnowledgeMap.handleMemoryUpdate();
            }
            break;
          }
          case 'context_summarized': {
            // Update ContextHealthBar with summarized token count
            if (window.ContextHealthBar) {
              ContextHealthBar.update(data.active_tokens || null, data.summarized_tokens || data.tokens_freed || 0, null);
            }
            // Render "Context compressed" badge in chat stream
            if (typeof LeftPane !== 'undefined' && LeftPane._getMessagesArea) {
              const area = document.getElementById('messagesArea');
              if (area) {
                const badge = document.createElement('div');
                badge.className = 'context-compressed-badge';
                badge.textContent = 'Context compressed. Key takeaways saved.';
                badge.style.cssText = 'cursor:pointer;padding:6px 12px;margin:8px auto;background:var(--surface-2,#2a2a3e);border-radius:8px;font-size:0.8rem;color:var(--text-muted,#aaa);text-align:center;max-width:320px;';
                // Store takeaways for expansion
                const takeaways = data.takeaways || [];
                badge.addEventListener('click', () => {
                  let panel = badge.nextElementSibling;
                  if (panel && panel.classList.contains('takeaways-panel')) {
                    panel.remove();
                    return;
                  }
                  panel = document.createElement('div');
                  panel.className = 'takeaways-panel';
                  panel.style.cssText = 'padding:8px 12px;margin:4px auto 8px;background:var(--surface-1,#1e1e2e);border-radius:8px;font-size:0.78rem;color:var(--text-secondary,#ccc);max-width:320px;';
                  if (takeaways.length === 0) {
                    panel.textContent = 'No takeaways available.';
                  } else {
                    const ul = document.createElement('ul');
                    ul.style.cssText = 'margin:0;padding-left:16px;';
                    takeaways.forEach(t => {
                      const li = document.createElement('li');
                      li.textContent = t;
                      li.style.marginBottom = '4px';
                      ul.appendChild(li);
                    });
                    panel.appendChild(ul);
                  }
                  badge.insertAdjacentElement('afterend', panel);
                });
                area.appendChild(badge);
              }
            }
            break;
          }
          default:
            // Handle interrupt messages (security approval, HITL clarification, ask_user)
            if (data.type === 'interrupt' && data.interrupts) {
              handleSecurityInterrupt(data.interrupts);
            }
            break;
        }
      } catch (err) {
        // WS message parse error silenced
      }
    },

    /**
     * Switch to a different project context (unified switching path).
     * Saves current project's thread ID and scroll position, restores or creates
     * state for the new project, reconnects WebSocket, loads chat history,
     * fetches project data, updates UI, and triggers module updates.
     * @param {string} newProjectId - The project ID to switch to.
     * @param {boolean} [resetChat=true] - Whether to reset chat and load history.
     */
    async switchProject(newProjectId, resetChat = true) {
      const oldProjectId = state.activeProjectId;
      if (newProjectId === oldProjectId) return;

      // 1. Save current project's thread ID and scroll position
      if (oldProjectId) {
        const chatContainer = document.getElementById('chatContainer');
        const scrollPos = chatContainer ? chatContainer.scrollTop : 0;
        state.projectThreads[oldProjectId] = {
          threadId: state.currentSessionId,
          scrollPos: scrollPos,
        };
      }

      // 2. Update global state variables for backward compatibility
      setWorkspaceProject(newProjectId, true);
      if (typeof currentSubPath !== 'undefined') currentSubPath = '';
      // Ensure currentView is 'chat' before checking workspace visibility
      if (typeof currentView !== 'undefined') currentView = 'chat';
      if (typeof setWorkspaceVisibility === 'function') setWorkspaceVisibility();
      if (typeof loadWorkspaceFiles === 'function') loadWorkspaceFiles();

      // 3. Determine thread ID for the new project
      const saved = state.projectThreads[newProjectId];
      const threadId = saved ? saved.threadId : generateUUID();

      // 4. Update StateManager state
      state.activeProjectId = newProjectId;
      state.currentSessionId = threadId;
      if (typeof chatProjectIdForThread !== 'undefined') setChatProjectContext(newProjectId);

      // 5. Connect WebSocket with project-scoped thread
      this.connectWebSocket(threadId);

      // 6. Reset Context Health Bar for new project's conversation state
      if (window.ContextHealthBar) {
        ContextHealthBar.update(0, 0, null);
      }

      // 7. Trigger module updates
      if (window.ToolDock && typeof ToolDock.updateForProject === 'function') {
        ToolDock.updateForProject(newProjectId);
      }
      if (window.KnowledgeMap && typeof KnowledgeMap.refresh === 'function') {
        KnowledgeMap.refresh(newProjectId);
      }

      // 8. Notify subscribers of the changes
      this.notify(['activeProjectId', 'currentSessionId']);

      // 9. Restore scroll position if returning to a previous project
      if (saved && saved.scrollPos != null) {
        requestAnimationFrame(() => {
          const chatContainer = document.getElementById('chatContainer');
          if (chatContainer) chatContainer.scrollTop = saved.scrollPos;
        });
      }

      // 10. Fetch project data and update UI
      try {
        const res = await fetch(`${API_BASE}/api/projects/${newProjectId}`);
        const project = await res.json();

        // Guard against error responses (e.g. project not found)
        if (project.status === 'error' || !project.id) {
          // Keep existing sidebar state on transient project load failures.
          if (typeof renderProjects === 'function' && Array.isArray(cachedProjects)) {
            renderProjects(cachedProjects);
          }
          if (typeof renderWelcomeRecents === 'function') renderWelcomeRecents();
          return;
        }

        if (typeof currentChatName !== 'undefined') currentChatName = '';
        if (typeof renderProjectInspector === 'function') renderProjectInspector(project);

        const projectKnowledgeSection = document.querySelector('#projectKnowledgeSection');
        if (projectKnowledgeSection) {
          projectKnowledgeSection.classList.toggle('hidden', !project.files || project.files.length === 0);
        }
        if (typeof renderProjectFiles === 'function') renderProjectFiles(project.files || []);

        const projectChatsSection = document.getElementById('projectChatsSection');
        if (projectChatsSection) {
          projectChatsSection.classList.toggle('hidden', !project.chats || project.chats.length === 0);
        }
        if (typeof renderProjectChats === 'function') renderProjectChats(project.chats || []);

        // Re-render from local cache for active-state highlight without forcing
        // another projects fetch that can transiently blank the explorer tree.
        if (typeof renderProjects === 'function' && Array.isArray(cachedProjects)) {
          renderProjects(cachedProjects);
        }
        if (typeof renderWelcomeRecents === 'function') renderWelcomeRecents();

        // 11. Load chat history if resetChat is true
        if (resetChat) {
          if (typeof isReasoning !== 'undefined') isReasoning = false;
          if (typeof resetTransientExecutionUI === 'function') resetTransientExecutionUI();
          if (typeof finalizeActiveMessage === 'function') finalizeActiveMessage();

          const savedSessionId = localStorage.getItem(`project_session_${newProjectId}`);
          if (savedSessionId) {
            if (typeof chatProjectIdForThread !== 'undefined') setChatProjectContext(newProjectId);
            if (typeof currentSessionId !== 'undefined') currentSessionId = savedSessionId;
            state.currentSessionId = savedSessionId;
            if (typeof loadChatHistory === 'function') await loadChatHistory(savedSessionId);
            const selectedChat = (project.chats || []).find((c) => c.id === savedSessionId);
            if (typeof currentChatName !== 'undefined') currentChatName = selectedChat?.name || '';
            if (typeof chatRegisteredInBackend !== 'undefined') chatRegisteredInBackend = Boolean(selectedChat);

            // Reconnect WebSocket to the saved session
            this.connectWebSocket(savedSessionId);
          } else {
            // No saved session — start a fresh chat for this project
            const freshSessionId = generateUUID();
            if (typeof currentSessionId !== 'undefined') currentSessionId = freshSessionId;
            state.currentSessionId = freshSessionId;
            if (typeof chatProjectIdForThread !== 'undefined') setChatProjectContext(newProjectId);
            if (typeof currentChatName !== 'undefined') currentChatName = '';
            if (typeof chatRegisteredInBackend !== 'undefined') chatRegisteredInBackend = false;
            localStorage.setItem(`project_session_${newProjectId}`, freshSessionId);
            const _messagesArea = document.getElementById('messagesArea');
            if (_messagesArea) _messagesArea.innerHTML = '';
            if (typeof hasSentMessageInCurrentSession !== 'undefined') hasSentMessageInCurrentSession = false;

            // Reconnect WebSocket to the fresh session
            this.connectWebSocket(freshSessionId);
          }
        }
      } catch (_e) {
        // Silently handle fetch failures during project switch
      }
    },

    /**
     * Send a chat message over the WebSocket.
     * @param {string} text - The message text.
     * @param {Array} [files=[]] - Optional file attachments.
     */
    sendMessage(text, files = []) {
      let payload;
      if (window.OrchestratorPanel && typeof OrchestratorPanel.buildWsPayload === 'function') {
        payload = OrchestratorPanel.buildWsPayload(text, files);
      } else {
        payload = {
          message: text,
          files: files,
          mode: state.activeMode,
          web_search_enabled: state.webSearchEnabled,
          response_style: state.responseStyle,
          project_id: state.activeProjectId || 'default',
        };
      }
      if (state.socket && state.socket.readyState === WebSocket.OPEN) {
        state.socket.send(JSON.stringify(payload));
      }
      state.hasSentMessage = true;
      this.notify(['hasSentMessage']);
    },
  };
})();

// ─── LeftPane Component ────────────────────────────────────────────────────
// Primary interaction area — greeting on idle, streaming chat during conversation.
// Manages two modes:
//   - 'greeting': Shows time-based greeting (Good morning/afternoon/evening)
//   - 'chat': Streaming message area with AI chunks, tool cards, model badges
//
// Key methods:
//   renderUserMessage(text, files) — Adds a user message bubble
//   appendChunk(content) — Streams AI response token-by-token via RAF batching
//   finalizeAiMessage() — Closes the streaming bubble, adds action buttons
//   renderToolCard(...) — Shows tool execution status (success/error)
//   renderModelBadge(model, usage) — Shows which model handled the request
//   renderRouterInfo(metadata) — Shows routing decision transparency
const LeftPane = (() => {
  let _mode = 'greeting'; // 'greeting' | 'chat'
  let _messages = [];
  let _chunkBuffer = '';
  let _rafPending = false;
  let _activeAiMsgEl = null;

  function _getGreetingView() { return document.getElementById('greetingView'); }
  function _getChatView() { return document.getElementById('chatView'); }
  function _getMessagesArea() { return document.getElementById('messagesArea'); }
  function _getChatContainer() { return document.getElementById('chatContainer'); }

  function _timeGreeting() {
    const h = new Date().getHours();
    if (h < 12) return 'Good morning';
    if (h < 18) return 'Good afternoon';
    return 'Good evening';
  }

  function _sanitizeHTML(md) {
    if (typeof marked !== 'undefined' && typeof DOMPurify !== 'undefined') {
      return DOMPurify.sanitize(marked.parse(md || ''));
    }
    return (md || '').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  function _scrollToBottom(force) {
    const c = _getChatContainer();
    if (!c) return;
    if (force || c.scrollHeight - c.scrollTop - c.clientHeight < 120) {
      c.scrollTop = c.scrollHeight;
    }
  }

  return {
    get mode() { return _mode; },
    get messages() { return _messages; },

    renderGreeting(userName) {
      _mode = 'greeting';
      const gv = _getGreetingView();
      const cv = _getChatView();
      if (gv) {
        gv.classList.remove('hidden');
        const gt = document.getElementById('greetingText');
        if (gt) gt.textContent = `${_timeGreeting()}, ${userName || 'User'}.`;
      }
      // Hide the chat container but keep chatView visible (tab system manages chatView)
      const cc = document.getElementById('chatContainer');
      if (cc) cc.classList.add('hidden');
    },

    transitionToChat() {
      _mode = 'chat';
      const gv = _getGreetingView();
      const cc = document.getElementById('chatContainer');
      if (gv) gv.classList.add('hidden');
      if (cc) {
        cc.classList.remove('hidden');
        cc.style.display = '';
      }
    },

    renderUserMessage(text, files) {
      if (_mode === 'greeting') this.transitionToChat();
      const area = _getMessagesArea();
      if (!area) return;

      const row = document.createElement('div');
      row.className = 'msg-row';
      row.innerHTML = `
        <div class="msg-avatar user"><i data-lucide="user" style="width:16px;height:16px;"></i></div>
        <div class="msg-body">
          <div class="message-content">${_sanitizeHTML(text)}</div>
          ${files && files.length ? `<div style="font-size:0.75rem;color:var(--text-muted);margin-top:0.25rem;">${files.map(f => f.name).join(', ')}</div>` : ''}
        </div>`;
      area.appendChild(row);
      _messages.push({ role: 'user', content: text });
      if (window.lucide) lucide.createIcons({ root: row });
      _scrollToBottom(true);
    },

    appendChunk(content) {
      if (_mode === 'greeting') this.transitionToChat();
      _chunkBuffer += content;

      if (!_rafPending) {
        _rafPending = true;
        requestAnimationFrame(() => {
          _rafPending = false;
          if (!_activeAiMsgEl) {
            const area = _getMessagesArea();
            if (!area) return;
            const row = document.createElement('div');
            row.className = 'msg-row';
            row.innerHTML = `
              <div class="msg-avatar ai">🦉</div>
              <div class="msg-body">
                <div class="message-content ai-streaming"></div>
              </div>`;
            area.appendChild(row);
            _activeAiMsgEl = row.querySelector('.ai-streaming');
          }
          if (_activeAiMsgEl) {
            _activeAiMsgEl.innerHTML = _sanitizeHTML(_chunkBuffer);
          }
          _scrollToBottom(false);
        });
      }
    },

    finalizeAiMessage() {
      if (_activeAiMsgEl) {
        _activeAiMsgEl.classList.remove('ai-streaming');
        _messages.push({ role: 'ai', content: _chunkBuffer });
        // Add action buttons
        const body = _activeAiMsgEl.closest('.msg-body');
        if (body) {
          const actions = document.createElement('div');
          actions.className = 'message-actions';
          actions.innerHTML = `
            <button class="msg-action-btn" onclick="navigator.clipboard.writeText(this.closest('.msg-body').querySelector('.message-content').innerText)">Copy</button>`;
          body.appendChild(actions);
        }
      }
      _activeAiMsgEl = null;
      _chunkBuffer = '';
      _scrollToBottom(true);
    },

    showThinkingIndicator() {
      if (_mode === 'greeting') this.transitionToChat();
      const area = _getMessagesArea();
      if (!area) return;
      // Remove existing thinking indicator
      const existing = area.querySelector('.thinking-row');
      if (existing) existing.remove();

      const row = document.createElement('div');
      row.className = 'msg-row thinking-row';
      row.innerHTML = `
        <div class="msg-avatar ai">🦉</div>
        <div class="msg-body">
          <div class="thinking-pill"><span class="thinking-dot"></span> Thinking…</div>
        </div>`;
      area.appendChild(row);
      _scrollToBottom(true);
    },

    clearThinkingIndicator() {
      const area = _getMessagesArea();
      if (!area) return;
      const t = area.querySelector('.thinking-row');
      if (t) t.remove();
    },

    renderError(content) {
      if (_mode === 'greeting') this.transitionToChat();
      const area = _getMessagesArea();
      if (!area) return;
      const row = document.createElement('div');
      row.className = 'msg-row';
      row.innerHTML = `
        <div class="msg-avatar error">⚠</div>
        <div class="msg-body">
          <div class="error-card"><strong>Error</strong>${_sanitizeHTML(content)}</div>
        </div>`;
      area.appendChild(row);
      _scrollToBottom(true);
    },

    renderMessage(msg) {
      if (_mode === 'greeting') this.transitionToChat();
      const area = _getMessagesArea();
      if (!area) return;
      const isAi = msg.type === 'ai' || msg.role === 'ai';
      const row = document.createElement('div');
      row.className = 'msg-row';
      row.innerHTML = `
        <div class="msg-avatar ${isAi ? 'ai' : 'user'}">${isAi ? '🦉' : '<i data-lucide="user" style="width:16px;height:16px;"></i>'}</div>
        <div class="msg-body">
          <div class="message-content">${_sanitizeHTML(msg.content || msg.message || '')}</div>
        </div>`;
      area.appendChild(row);
      if (window.lucide) lucide.createIcons({ root: row });
      _scrollToBottom(true);
    },

    scrollToBottom(force) { _scrollToBottom(force); },

    // Virtual scrolling: when messages exceed 100, hide off-screen ones
    pruneMessages() {
      const area = _getMessagesArea();
      if (!area) return;
      const rows = area.querySelectorAll('.msg-row');
      if (rows.length <= 100) return;
      // Hide oldest messages beyond viewport
      const container = _getChatContainer();
      if (!container) return;
      const viewTop = container.scrollTop;
      rows.forEach((row, i) => {
        if (i < rows.length - 100) {
          row.style.display = 'none';
          row.dataset.pruned = 'true';
        }
      });
    },

    restorePrunedMessages() {
      const area = _getMessagesArea();
      if (!area) return;
      area.querySelectorAll('[data-pruned="true"]').forEach(row => {
        row.style.display = '';
        delete row.dataset.pruned;
      });
    },

    clearMessages() {
      const area = _getMessagesArea();
      if (area) area.innerHTML = '';
      _messages = [];
      _chunkBuffer = '';
      _activeAiMsgEl = null;
    },

    renderToolCard(toolName, status, input, output, error, toolCallId) {
      if (_mode === 'greeting') this.transitionToChat();
      const area = _getMessagesArea();
      if (!area) return;
      const id = toolCallId || toolName;
      let card = area.querySelector(`[data-tool-id="${id}"]`);
      if (!card) {
        // Try to insert into the current agent message group instead of creating a new row
        const lastWrapper = area.lastElementChild;
        let targetBody = null;
        if (lastWrapper && lastWrapper.dataset.sender === 'agent') {
          targetBody = lastWrapper.querySelector('.message-content') || lastWrapper.querySelector('.msg-body');
        }
        if (!targetBody) {
          // Create a new agent group
          const row = document.createElement('div');
          row.className = 'flex gap-4 group-msg mb-6';
          row.dataset.sender = 'agent';
          row.innerHTML = `
            <div class="w-8 h-8 rounded shrink-0 bg-anthropic flex items-center justify-center text-white mt-1">
              <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 8V4H8"/><rect x="4" y="8" width="16" height="12" rx="2"/><path d="M2 14h2"/><path d="M20 14h2"/><path d="M15 13v2"/><path d="M9 13v2"/></svg>
            </div>
            <div class="flex-1 message-content text-base text-textdark leading-relaxed space-y-2"></div>`;
          area.appendChild(row);
          targetBody = row.querySelector('.message-content');
        }
        card = document.createElement('div');
        card.setAttribute('data-tool-id', id);
        card.innerHTML = `
          <div class="tool-card">
            <div class="tool-card-header"><span>${toolName}</span> <span class="tool-status running">Running…</span></div>
            <div class="tool-io-container"></div>
          </div>`;
        targetBody.appendChild(card);
        _scrollToBottom(false);
      }
      const statusEl = card.querySelector('.tool-status');
      const ioContainer = card.querySelector('.tool-io-container');
      if (statusEl) {
        statusEl.className = `tool-status ${status}`;
        statusEl.textContent = status === 'running' ? 'Running…' : status === 'success' ? 'Success' : 'Error';
      }
      if (ioContainer) {
        ioContainer.innerHTML = '';
        if (input) ioContainer.innerHTML += `<div class="tool-io input"><pre>${typeof input === 'string' ? input : JSON.stringify(input, null, 2)}</pre></div>`;
        if (output) ioContainer.innerHTML += `<div class="tool-io output"><pre>${typeof output === 'string' ? output : JSON.stringify(output, null, 2)}</pre></div>`;
        if (error) ioContainer.innerHTML += `<div class="tool-io err"><pre>${error}</pre></div>`;
      }
    },

    renderModelBadge(model, tokenUsage) {
      const area = _getMessagesArea();
      if (!area) return;
      let colorClass = 'model-badge-cloud';
      const m = (model || '').toLowerCase();
      if (m.includes('small') || m.includes('local')) colorClass = 'model-badge-small';
      else if (m.includes('medium') || m.includes('mid')) colorClass = 'model-badge-medium';
      else if (m.includes('fallback')) colorClass = 'model-badge-fallback';
      else if (m.includes('large') || m.includes('cloud')) colorClass = 'model-badge-cloud';

      const badge = document.createElement('div');
      badge.className = `model-badge ${colorClass}`;
      badge.innerHTML = `<span>⚡</span> ${model}`;
      if (tokenUsage) {
        badge.innerHTML += ` <span class="cloud-token-indicator">${tokenUsage.total || ''} tokens</span>`;
      }
      // Insert into current agent message group instead of standalone
      const lastWrapper = area.lastElementChild;
      if (lastWrapper && lastWrapper.dataset.sender === 'agent') {
        const content = lastWrapper.querySelector('.message-content') || lastWrapper.querySelector('.msg-body');
        if (content) { content.appendChild(badge); return; }
      }
      area.appendChild(badge);
    },

    renderRouterInfo(metadata) {
      if (!metadata) return;
      const area = _getMessagesArea();
      if (!area) return;
      const panel = document.createElement('details');
      panel.className = 'router-info-panel';
      panel.innerHTML = `
        <summary>🧭 Route: ${metadata.route || 'unknown'} (${Math.round((metadata.confidence || 0) * 100)}%)</summary>
        <div class="router-info-body">
          ${metadata.reasoning ? `<span><strong>Reasoning:</strong> ${metadata.reasoning}</span>` : ''}
          ${metadata.key_features ? `<span><strong>Features:</strong> ${metadata.key_features.join(', ')}</span>` : ''}
        </div>`;
      // Insert into current agent message group or create one
      const lastWrapper = area.lastElementChild;
      if (lastWrapper && lastWrapper.dataset.sender === 'agent') {
        const content = lastWrapper.querySelector('.message-content') || lastWrapper.querySelector('.msg-body');
        if (content) { content.insertBefore(panel, content.firstChild); return; }
      }
      // Create a new agent group for the router info
      const row = document.createElement('div');
      row.className = 'flex gap-4 group-msg mb-6';
      row.dataset.sender = 'agent';
      row.innerHTML = `
        <div class="w-8 h-8 rounded shrink-0 bg-anthropic flex items-center justify-center text-white mt-1">
          <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 8V4H8"/><rect x="4" y="8" width="16" height="12" rx="2"/><path d="M2 14h2"/><path d="M20 14h2"/><path d="M15 13v2"/><path d="M9 13v2"/></svg>
        </div>
        <div class="flex-1 message-content text-base text-textdark leading-relaxed space-y-2"></div>`;
      row.querySelector('.message-content').appendChild(panel);
      area.appendChild(row);
    },

    showSwapIndicator(model) {
      let el = document.getElementById('swapIndicator');
      if (!el) {
        el = document.createElement('div');
        el.id = 'swapIndicator';
        el.className = 'swap-indicator';
        const area = _getMessagesArea();
        if (area) area.appendChild(el);
      }
      el.textContent = `⏳ Swapping to ${model}…`;
      el.classList.remove('hidden');
    },

    hideSwapIndicator() {
      const el = document.getElementById('swapIndicator');
      if (el) el.classList.add('hidden');
    },

    renderFallbackChain(chain) {
      if (!chain || chain.length <= 1) return;
      const area = _getMessagesArea();
      if (!area) return;
      const el = document.createElement('div');
      el.className = 'fallback-chain-display';
      el.innerHTML = chain.map((step, i) => {
        const cls = step.status === 'success' ? 'success' : 'failed';
        return `<span class="chain-step ${cls}">${step.model}</span>${i < chain.length - 1 ? '<span class="chain-arrow">→</span>' : ''}`;
      }).join('');
      area.appendChild(el);
    },

    renderAskUserCard(question, choices) {
      if (_mode === 'greeting') this.transitionToChat();
      const area = _getMessagesArea();
      if (!area) return;
      const row = document.createElement('div');
      row.className = 'msg-row';
      let choicesHtml = '';
      if (choices && choices.length) {
        choicesHtml = `<div style="display:flex;flex-wrap:wrap;gap:0.5rem;margin-top:0.5rem;">${choices.map(c => `<button class="ask-choice-btn btn-outline" data-choice="${c}">${c}</button>`).join('')}</div>`;
      } else {
        choicesHtml = `<div class="ask-input-row"><input type="text" placeholder="Type your response…"><button class="btn-accent">Send</button></div>`;
      }
      row.innerHTML = `
        <div class="msg-avatar ai">❓</div>
        <div class="msg-body">
          <div class="ask-user-card">
            <div class="ask-header">🤔 Clarification needed</div>
            <p style="font-size:0.9rem;">${question}</p>
            ${choicesHtml}
          </div>
        </div>`;
      area.appendChild(row);
      _scrollToBottom(true);
      return row;
    },

    renderSecurityApproval(toolName, args) {
      const modal = document.getElementById('securityApprovalModal');
      const text = document.getElementById('securityApprovalText');
      const argsEl = document.getElementById('securityApprovalArgs');
      if (modal && text && argsEl) {
        text.textContent = `The AI wants to execute: ${toolName}`;
        argsEl.textContent = JSON.stringify(args, null, 2);
        modal.classList.remove('hidden');
      }
    },
  };
})();

// ─── Backend URL Detection ─────────────────────────────────────────────────
// When running inside Tauri, location.host points to tauri://localhost (not the backend).
// Detect this and fall back to the known backend address.
const _isTauri = Boolean(window.__TAURI__ || location.protocol === 'tauri:' || !location.host || location.host === 'localhost');
const API_BASE = _isTauri ? 'http://127.0.0.1:8000' : '';
window.API_BASE = API_BASE;
const WS_BASE = _isTauri ? 'ws://127.0.0.1:8000' : `ws://${location.host}`;

// ─── Notification Helper ───────────────────────────────────────────────────
function _showNotification(message) {
  const notif = document.createElement('div');
  notif.className = 'aurora-notification';
  notif.textContent = message;
  document.body.appendChild(notif);
  setTimeout(() => notif.remove(), 3000);
}

// ─── CenterPane Component ──────────────────────────────────────────────────
const CenterPane = (() => {
  let _tools = [];
  const TOOL_ICON_MAP = {
    'project_manager': 'folder-kanban', 'calendar': 'calendar', 'email_client': 'mail',
    'finder': 'search', 'code_editor': 'code', 'web_browser': 'globe',
    'note_taker': 'notebook-pen', 'pdf_reader': 'file-text', 'python_executor': 'terminal',
    'security_proxy': 'shield', 'nmap': 'radar', 'memory': 'brain',
  };

  function _getGrid() { return document.getElementById('toolGrid'); }

  return {
    get tools() { return _tools; },

    loadTools(tools) {
      _tools = (tools || []).map(t => ({
        id: t.name || t.id, name: t.display_name || t.name || t.id,
        icon: TOOL_ICON_MAP[t.name] || 'wrench', description: t.description || '',
        category: t.category || 'core', enabled: true,
      }));
      this.renderToolGrid(_tools);
    },

    renderToolGrid(tools) {
      const grid = _getGrid();
      if (!grid) return;
      grid.innerHTML = '';
      (tools || _tools).forEach(t => {
        const card = document.createElement('div');
        card.className = `aurora-tool-card${t.enabled ? ' active' : ''}`;
        card.dataset.toolId = t.id;
        card.innerHTML = `<i data-lucide="${t.icon}" class="tool-icon"></i><span class="tool-name">${t.name}</span>`;
        card.onclick = () => this.activateTool(t.id);
        grid.appendChild(card);
      });
      // Add More card
      const addMore = document.createElement('div');
      addMore.className = 'aurora-tool-card';
      addMore.innerHTML = `<i data-lucide="plus" class="tool-icon"></i><span class="tool-name">Add More</span>`;
      grid.appendChild(addMore);
      if (window.lucide) lucide.createIcons({ root: grid });
    },

    activateTool(toolId) {
      const t = _tools.find(x => x.id === toolId);
      if (!t) return;
      t.enabled = !t.enabled;
      this.renderToolGrid(_tools);
      _showNotification(`${t.name} ${t.enabled ? 'enabled' : 'disabled'}`);
    },

    renderEmpty() {
      const grid = _getGrid();
      if (grid) grid.innerHTML = '<div style="padding:1rem;color:var(--text-muted);font-size:0.82rem;">No tools for this view</div>';
    },
  };
})();

// ─── RightPane Component ───────────────────────────────────────────────────
const RightPane = (() => {
  let _files = [];
  let _debounceTimer = null;
  const UNIVERSAL_ACTIONS = [
    { id: 'find', label: 'Find', icon: 'search' },
    { id: 'organize', label: 'Organize', icon: 'layout-grid' },
    { id: 'automate', label: 'Automate', icon: 'settings' },
    { id: 'plan', label: 'Plan', icon: 'calendar' },
    { id: 'connect', label: 'Connect', icon: 'link' },
    { id: 'research', label: 'Research', icon: 'book-open' },
  ];

  function _getFileList() { return document.getElementById('fileList'); }
  function _getUniversalTools() { return document.getElementById('universalTools'); }

  function _relativeTime(ts) {
    if (!ts) return '';
    const diff = Date.now() - (typeof ts === 'number' ? ts * 1000 : new Date(ts).getTime());
    const mins = Math.floor(diff / 60000);
    if (mins < 1) return 'just now';
    if (mins < 60) return `${mins}m ago`;
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return `${hrs}h ago`;
    return `${Math.floor(hrs / 24)}d ago`;
  }

  return {
    get frequentFiles() { return _files; },

    loadFrequentFiles(files) {
      _files = (files || []).map(f => ({
        name: f.name || f.filename, modified: f.modified || f.last_modified,
        status: f.status || 'idle', type: f.type || 'file', size: f.size || 0,
      }));
      this.renderFileList(_files);
    },

    renderFileList(files) {
      const list = _getFileList();
      if (!list) return;
      list.innerHTML = '';
      (files || _files).forEach(f => {
        const item = document.createElement('div');
        item.className = 'aurora-file-item';
        item.style.cursor = 'pointer';
        item.innerHTML = `
          <i data-lucide="file" class="file-icon"></i>
          <span class="file-name">${f.name}</span>
          <span class="file-time">${_relativeTime(f.modified)}</span>
          <span class="file-status ${f.status}"></span>`;
        item.addEventListener('click', () => {
          if (typeof viewWorkspaceFile === 'function') {
            viewWorkspaceFile(f.name);
          }
        });
        list.appendChild(item);
      });
      if (window.lucide) lucide.createIcons({ root: list });
    },

    renderUniversalTools() {
      const grid = _getUniversalTools();
      if (!grid) return;
      grid.innerHTML = '';
      UNIVERSAL_ACTIONS.forEach(a => {
        const btn = document.createElement('button');
        btn.className = 'aurora-action';
        btn.innerHTML = `<i data-lucide="${a.icon}" class="action-icon"></i>${a.label}`;
        btn.addEventListener('click', () => {
          if (typeof BottomInputBar !== 'undefined') {
            BottomInputBar.setDraft('/' + a.id);
            const input = document.getElementById('messageInput');
            if (input) input.focus();
          }
        });
        grid.appendChild(btn);
      });
      if (window.lucide) lucide.createIcons({ root: grid });
    },

    updateFileStatus(filename, status) {
      if (_debounceTimer) clearTimeout(_debounceTimer);
      _debounceTimer = setTimeout(() => {
        const f = _files.find(x => x.name === filename);
        if (f) { f.status = status; this.renderFileList(_files); }
      }, 100);
    },

    renderEmpty() {
      const list = _getFileList();
      if (list) list.innerHTML = '<div style="padding:0.5rem;color:var(--text-muted);font-size:0.82rem;">No files</div>';
      const grid = _getUniversalTools();
      if (grid) grid.innerHTML = '';
    },
  };
})();

// ─── BottomInputBar Component ──────────────────────────────────────────────
const BottomInputBar = (() => {
  let _pendingFiles = [];

  function _getInput() { return document.getElementById('messageInput'); }
  function _getAttachPreviews() { return document.getElementById('attachmentPreviews'); }

  return {
    get pendingFiles() { return _pendingFiles; },

    init() {
      const input = _getInput();
      const sendBtn = document.getElementById('sendBtn');
      const attachBtn = document.getElementById('attachFileBtn');
      const fileInput = document.getElementById('fileInput');
      const settingsBtn = document.getElementById('settingsBtn');

      if (input) {
        input.addEventListener('input', () => {
          input.style.height = 'auto';
          input.style.height = Math.min(input.scrollHeight, 200) + 'px';
        });
        input.addEventListener('keydown', (e) => {
          if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); this.submit(); }
        });
      }
      if (sendBtn) sendBtn.addEventListener('click', () => this.submit());
      if (attachBtn && fileInput) {
        attachBtn.addEventListener('click', () => fileInput.click());
        fileInput.addEventListener('change', (e) => {
          Array.from(e.target.files).forEach(f => this.addFile(f));
          fileInput.value = '';
        });
      }
      if (settingsBtn) {
        settingsBtn.addEventListener('click', () => {
          const modal = document.getElementById('settingsModal');
          if (modal) {
            modal.classList.remove('hidden');
            if (typeof renderSettingsUI === 'function') renderSettingsUI();
          }
        });
      }

      // Wire Mic button
      const micBtn = document.getElementById('micBtn');
      if (micBtn) {
        micBtn.addEventListener('click', () => {
          const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
          if (SpeechRecognition) {
            const recognition = new SpeechRecognition();
            recognition.lang = 'en-US';
            recognition.interimResults = false;
            recognition.onresult = (event) => {
              const transcript = event.results[0][0].transcript;
              const inp = _getInput();
              if (inp) { inp.value += transcript; inp.dispatchEvent(new Event('input')); }
            };
            recognition.onerror = () => {
              _showNotification('Voice input failed. Please try again.');
            };
            recognition.start();
          } else {
            _showNotification('Voice input is not supported in this browser.');
          }
        });
      }
    },

    getDraft() { const i = _getInput(); return i ? i.value : ''; },
    setDraft(text) { const i = _getInput(); if (i) { i.value = text; i.style.height = 'auto'; } },

    addFile(file) {
      const reader = new FileReader();
      reader.onload = () => {
        _pendingFiles.push({ name: file.name, type: file.type, data: reader.result.split(',')[1] });
        this._renderAttachments();
      };
      reader.readAsDataURL(file);
    },

    removeFile(index) {
      _pendingFiles.splice(index, 1);
      this._renderAttachments();
    },

    _renderAttachments() {
      const el = _getAttachPreviews();
      if (!el) return;
      if (_pendingFiles.length === 0) { el.classList.add('hidden'); el.innerHTML = ''; return; }
      el.classList.remove('hidden');
      el.innerHTML = _pendingFiles.map((f, i) =>
        `<span class="tag">${f.name} <button onclick="BottomInputBar.removeFile(${i})" style="margin-left:0.3rem;cursor:pointer;">×</button></span>`
      ).join('');
    },

    submit() {
      const text = this.getDraft().trim();
      if (!text && _pendingFiles.length === 0) return;

      const files = _pendingFiles.map(f => ({ name: f.name, type: f.type, data: f.data }));

      // Render user message in LeftPane
      LeftPane.renderUserMessage(text, files);

      // Send via StateManager
      StateManager.sendMessage(text, files);

      // Clear
      this.setDraft('');
      _pendingFiles = [];
      this._renderAttachments();
    },

    buildPayload() {
      return {
        message: this.getDraft(),
        files: _pendingFiles.map(f => ({ name: f.name, type: f.type, data: f.data })),
        mode: StateManager.activeMode,
        web_search_enabled: StateManager.webSearchEnabled,
        response_style: StateManager.responseStyle,
        project_id: StateManager.activeProjectId || 'default',
      };
    },
  };
})();

// ─── buildChatWsPayload (standalone function for backward compat) ──────────
function buildChatWsPayload(messageText, filesPayload) {
  return {
    message: messageText,
    files: filesPayload || [],
    mode: StateManager.activeMode,
    web_search_enabled: StateManager.webSearchEnabled,
    response_style: StateManager.responseStyle,
    project_id: StateManager.activeProjectId || 'default',
  };
}

// ─── View Router ───────────────────────────────────────────────────────────
function navigateView(viewName, context = {}) {
  // Sync global currentView so setWorkspaceVisibility reads the correct value
  currentView = viewName;
  StateManager.navigate(viewName, context);

  switch (viewName) {
    case 'home':
      LeftPane.renderGreeting(StateManager.userName);
      CenterPane.renderToolGrid(CenterPane.tools);
      RightPane.renderFileList(RightPane.frequentFiles);
      RightPane.renderUniversalTools();
      break;
    case 'chat':
      if (context.threadId) {
        StateManager.connectWebSocket(context.threadId);
      }
      LeftPane.transitionToChat();
      CenterPane.renderToolGrid(CenterPane.tools);
      RightPane.renderFileList(RightPane.frequentFiles);
      break;
    case 'projects':
      LeftPane.clearMessages();
      LeftPane.renderGreeting(StateManager.userName);
      CenterPane.renderEmpty();
      RightPane.renderEmpty();
      break;
    case 'project-detail':
      CenterPane.renderToolGrid(CenterPane.tools);
      break;
    case 'customize':
      CenterPane.renderEmpty();
      RightPane.renderEmpty();
      break;
    case 'chats':
      CenterPane.renderEmpty();
      RightPane.renderEmpty();
      break;
  }
}

// ─── ContentPreviewPanel Component ─────────────────────────────────────────
const ContentPreviewPanel = (() => {
  const ARTIFACT_TYPE_MAP = {
    'docx': { type: 'docx', editable: true }, 'pdf': { type: 'pdf', editable: false },
    'html': { type: 'html', editable: true }, 'svg': { type: 'svg', editable: false },
    'csv': { type: 'csv', editable: false }, 'png': { type: 'image', editable: false },
    'jpg': { type: 'image', editable: false }, 'jpeg': { type: 'image', editable: false },
    'gif': { type: 'image', editable: false }, 'webp': { type: 'image', editable: false },
    'md': { type: 'markdown', editable: true }, 'json': { type: 'code', editable: true },
    'py': { type: 'code', editable: true }, 'js': { type: 'code', editable: true },
    'ts': { type: 'code', editable: true }, 'txt': { type: 'code', editable: true },
  };

  function _getPanel() { return document.getElementById('contentPreviewPanel'); }
  function _getToolbar() { return document.getElementById('previewToolbar'); }
  function _getContent() { return document.getElementById('previewContent'); }

  return {
    detectArtifactFromToolOutput(toolName, toolCallId, output) {
      if (typeof output !== 'string') return null;
      const match = output.match(/(?:saved|created|generated|wrote)\s+(?:to\s+)?["']?([^\s"']+\.(\w+))["']?/i);
      if (!match) return null;
      const ext = match[2].toLowerCase();
      const info = ARTIFACT_TYPE_MAP[ext];
      if (!info) return null;
      return {
        id: `artifact-${toolCallId || Date.now()}`, name: match[1].split('/').pop(),
        type: info.type, mimeType: '', content: null, editable: info.editable,
        sourceToolName: toolName, sourceToolCallId: toolCallId,
      };
    },

    openPreview(artifact) {
      StateManager.set('contentPreview', {
        isOpen: true, layoutMode: 'split', currentArtifact: artifact,
        isEditMode: false, editedContent: null, hasUnsavedChanges: false,
      });
      const rp = document.getElementById('rightPane');
      const panel = _getPanel();
      if (rp) rp.classList.add('hidden');
      if (panel) panel.classList.remove('hidden');
      this.renderToolbar(artifact);
      this.renderContent(artifact);
    },

    closePreview() {
      const cp = StateManager.contentPreview;
      if (cp.hasUnsavedChanges && !confirm('You have unsaved changes. Discard?')) return;
      // Revoke blob URLs
      const content = _getContent();
      if (content) content.querySelectorAll('iframe, img').forEach(el => {
        if (el.src && el.src.startsWith('blob:')) URL.revokeObjectURL(el.src);
      });
      StateManager.set('contentPreview', {
        isOpen: false, layoutMode: 'closed', currentArtifact: null,
        isEditMode: false, editedContent: null, hasUnsavedChanges: false,
      });
      const rp = document.getElementById('rightPane');
      const panel = _getPanel();
      if (panel) panel.classList.add('hidden');
      if (rp) rp.classList.remove('hidden');
    },

    renderToolbar(artifact) {
      const toolbar = _getToolbar();
      if (!toolbar) return;
      toolbar.innerHTML = `
        <button onclick="ContentPreviewPanel.closePreview()">Close Preview</button>
        <button onclick="ContentPreviewPanel.downloadArtifact()">Download</button>
        ${artifact && artifact.editable ? '<button onclick="ContentPreviewPanel.toggleEditMode()">Edit</button>' : ''}
        <div style="flex:1;"></div>
        <span style="font-size:0.75rem;color:var(--text-muted);">${artifact ? artifact.name : ''}</span>`;
    },

    renderContent(artifact) {
      const container = _getContent();
      if (!container || !artifact) return;
      container.innerHTML = '';
      try {
        switch (artifact.type) {
          case 'docx':
            if (artifact.content && typeof mammoth !== 'undefined') {
              mammoth.convertToHtml({ arrayBuffer: artifact.content }).then(result => {
                const div = document.createElement('div');
                div.innerHTML = DOMPurify.sanitize(result.value);
                if (artifact.editable) div.contentEditable = 'true';
                container.appendChild(div);
              });
            } else { container.innerHTML = '<p style="color:var(--text-muted);">DOCX preview requires file content</p>'; }
            break;
          case 'pdf':
            if (artifact.content) {
              const iframe = document.createElement('iframe');
              iframe.src = URL.createObjectURL(new Blob([artifact.content], { type: 'application/pdf' }));
              iframe.style.cssText = 'width:100%;height:100%;border:none';
              container.appendChild(iframe);
            }
            break;
          case 'html':
            const sandbox = document.createElement('iframe');
            sandbox.sandbox = 'allow-scripts';
            sandbox.srcdoc = typeof artifact.content === 'string' ? artifact.content : '';
            sandbox.style.cssText = 'width:100%;height:100%;border:none';
            container.appendChild(sandbox);
            break;
          case 'code': case 'markdown':
            const pre = document.createElement('pre');
            const code = document.createElement('code');
            code.textContent = artifact.content || '';
            pre.appendChild(code);
            container.appendChild(pre);
            break;
          case 'image':
            const img = document.createElement('img');
            img.src = typeof artifact.content === 'string' ? artifact.content : URL.createObjectURL(new Blob([artifact.content]));
            img.style.cssText = 'max-width:100%;height:auto';
            img.alt = artifact.name;
            container.appendChild(img);
            break;
          case 'csv':
            container.innerHTML = '<p style="color:var(--text-muted);">CSV table preview</p>';
            break;
          default:
            container.innerHTML = `<p style="color:var(--text-muted);">Unsupported type: ${artifact.type}</p>`;
        }
      } catch (err) {
        container.innerHTML = `<div class="error-card"><strong>Preview Error</strong><p>${err.message}</p><button class="btn-outline" onclick="ContentPreviewPanel.downloadArtifact()">Download Instead</button></div>`;
      }
    },

    toggleEditMode() {
      const cp = StateManager.contentPreview;
      if (!cp.currentArtifact || !cp.currentArtifact.editable) return;
      cp.isEditMode = !cp.isEditMode;
      StateManager.set('contentPreview', cp);
      const container = _getContent();
      if (!container || !cp.currentArtifact) return;

      if (cp.isEditMode) {
        // Switch to edit mode
        const content = cp.currentArtifact.content || '';
        container.innerHTML = '';
        if (cp.currentArtifact.type === 'docx') {
          const div = document.createElement('div');
          div.contentEditable = 'true';
          div.className = 'message-content';
          div.style.cssText = 'min-height:200px;padding:1rem;border:1px solid var(--border);border-radius:var(--radius);';
          div.innerHTML = DOMPurify.sanitize(content);
          div.addEventListener('input', () => {
            cp.editedContent = div.innerHTML;
            cp.hasUnsavedChanges = true;
          });
          container.appendChild(div);
        } else {
          const textarea = document.createElement('textarea');
          textarea.value = typeof content === 'string' ? content : '';
          textarea.spellcheck = cp.currentArtifact.type !== 'code';
          textarea.style.cssText = 'width:100%;height:100%;min-height:300px;font-family:var(--mono);font-size:0.85rem;background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:var(--radius);padding:1rem;resize:none;';
          textarea.addEventListener('input', () => {
            cp.editedContent = textarea.value;
            cp.hasUnsavedChanges = true;
          });
          container.appendChild(textarea);
        }
        // Add save/discard controls
        const controls = document.createElement('div');
        controls.style.cssText = 'display:flex;gap:0.5rem;padding:0.5rem 0;';
        controls.innerHTML = `
          <button class="btn-accent" onclick="ContentPreviewPanel.saveEdits()">Save</button>
          <button class="btn-outline" onclick="ContentPreviewPanel.discardEdits()">Discard</button>`;
        container.appendChild(controls);
        this.renderToolbar(cp.currentArtifact);
      } else {
        this.renderContent(cp.currentArtifact);
        this.renderToolbar(cp.currentArtifact);
      }
    },

    saveEdits() {
      const cp = StateManager.contentPreview;
      if (cp.editedContent != null && cp.currentArtifact) {
        cp.currentArtifact.content = cp.editedContent;
        cp.hasUnsavedChanges = false;
        cp.isEditMode = false;
        StateManager.set('contentPreview', cp);
        this.renderContent(cp.currentArtifact);
        this.renderToolbar(cp.currentArtifact);
      }
    },

    discardEdits() {
      const cp = StateManager.contentPreview;
      cp.editedContent = null;
      cp.hasUnsavedChanges = false;
      cp.isEditMode = false;
      StateManager.set('contentPreview', cp);
      this.renderContent(cp.currentArtifact);
      this.renderToolbar(cp.currentArtifact);
    },

    downloadArtifact() {
      const cp = StateManager.contentPreview;
      if (!cp.currentArtifact) return;
      const a = document.createElement('a');
      a.download = cp.currentArtifact.name;
      if (cp.currentArtifact.content) {
        const blob = new Blob([cp.editedContent || cp.currentArtifact.content]);
        a.href = URL.createObjectURL(blob);
      }
      a.click();
    },
  };
})();

// ─── renderSettingsUI ──────────────────────────────────────────────────────
function renderSettingsUI() {
  const body = document.getElementById('settingsBody');
  if (!body) return;
  // Only render once — if tabs already exist, skip
  if (body.querySelector('.settings-tabs')) return;

  body.innerHTML = `
    <div class="settings-tabs" style="display:flex;gap:0;border-bottom:1px solid var(--border);margin-bottom:1rem;">
      <button class="settings-tab active" data-tab="profile" style="padding:0.5rem 1rem;font-size:0.8rem;font-weight:600;background:none;border:none;color:var(--text-muted);cursor:pointer;border-bottom:2px solid transparent;">Profile</button>
      <button class="settings-tab" data-tab="persona" style="padding:0.5rem 1rem;font-size:0.8rem;font-weight:600;background:none;border:none;color:var(--text-muted);cursor:pointer;border-bottom:2px solid transparent;">Persona</button>
      <button class="settings-tab" data-tab="system" style="padding:0.5rem 1rem;font-size:0.8rem;font-weight:600;background:none;border:none;color:var(--text-muted);cursor:pointer;border-bottom:2px solid transparent;">System</button>
      <button class="settings-tab" data-tab="advanced" style="padding:0.5rem 1rem;font-size:0.8rem;font-weight:600;background:none;border:none;color:var(--text-muted);cursor:pointer;border-bottom:2px solid transparent;">Advanced</button>
    </div>
    <div class="settings-tab-content active" data-tab="profile" style="display:flex;flex-direction:column;gap:0.75rem;">
      <div class="form-field"><label style="font-size:0.75rem;color:var(--text-muted);">Name</label><input type="text" id="profileName" placeholder="Your name" style="width:100%;padding:0.45rem 0.6rem;border-radius:0.4rem;border:1px solid var(--border);background:var(--surface);color:var(--text);font-size:0.85rem;margin-top:0.2rem;"></div>
      <div class="form-field"><label style="font-size:0.75rem;color:var(--text-muted);">Language</label><input type="text" id="profileLang" placeholder="en" style="width:100%;padding:0.45rem 0.6rem;border-radius:0.4rem;border:1px solid var(--border);background:var(--surface);color:var(--text);font-size:0.85rem;margin-top:0.2rem;"></div>
      <div class="form-field"><label style="font-size:0.75rem;color:var(--text-muted);">Response Style</label><input type="text" id="profileStyle" placeholder="detailed" style="width:100%;padding:0.45rem 0.6rem;border-radius:0.4rem;border:1px solid var(--border);background:var(--surface);color:var(--text);font-size:0.85rem;margin-top:0.2rem;"></div>
      <div class="form-field"><label style="font-size:0.75rem;color:var(--text-muted);">LLM Base URL</label><input type="text" id="profileLlmUrl" placeholder="http://127.0.0.1:8080/v1" style="width:100%;padding:0.45rem 0.6rem;border-radius:0.4rem;border:1px solid var(--border);background:var(--surface);color:var(--text);font-size:0.85rem;margin-top:0.2rem;"></div>
      <div class="form-field"><label style="font-size:0.75rem;color:var(--text-muted);">Medium Model Key</label><input type="text" id="profileLlmModel" placeholder="lfm2-8b-a1b-absolute-heresy-mpoa-mlx" style="width:100%;padding:0.45rem 0.6rem;border-radius:0.4rem;border:1px solid var(--border);background:var(--surface);color:var(--text);font-size:0.85rem;margin-top:0.2rem;"></div>
      <button id="saveProfileBtn" class="btn-accent" style="align-self:flex-start;margin-top:0.5rem;">Save Profile</button>
    </div>
    <div class="settings-tab-content" data-tab="persona" style="display:none;flex-direction:column;gap:0.75rem;">
      <div class="form-field"><label style="font-size:0.75rem;color:var(--text-muted);">Persona Name</label><input type="text" id="personaName" placeholder="Owlynn" style="width:100%;padding:0.45rem 0.6rem;border-radius:0.4rem;border:1px solid var(--border);background:var(--surface);color:var(--text);font-size:0.85rem;margin-top:0.2rem;"></div>
      <div class="form-field"><label style="font-size:0.75rem;color:var(--text-muted);">Tone</label><input type="text" id="personaTone" placeholder="friendly" style="width:100%;padding:0.45rem 0.6rem;border-radius:0.4rem;border:1px solid var(--border);background:var(--surface);color:var(--text);font-size:0.85rem;margin-top:0.2rem;"></div>
      <button id="savePersonaBtn" class="btn-accent" style="align-self:flex-start;margin-top:0.5rem;">Save Persona</button>
    </div>
    <div class="settings-tab-content" data-tab="system" style="display:none;flex-direction:column;gap:0.75rem;">
      <div class="form-field"><label style="font-size:0.75rem;color:var(--text-muted);">System Prompt</label><textarea id="systemPromptInput" rows="6" style="width:100%;padding:0.45rem 0.6rem;border-radius:0.4rem;border:1px solid var(--border);background:var(--surface);color:var(--text);font-size:0.85rem;margin-top:0.2rem;resize:vertical;font-family:inherit;"></textarea></div>
      <div class="form-field"><label style="font-size:0.75rem;color:var(--text-muted);">Custom Instructions</label><textarea id="customInstructionsInput" rows="3" style="width:100%;padding:0.45rem 0.6rem;border-radius:0.4rem;border:1px solid var(--border);background:var(--surface);color:var(--text);font-size:0.85rem;margin-top:0.2rem;resize:vertical;font-family:inherit;"></textarea></div>
      <button id="saveSystemPromptBtn" class="btn-accent" style="align-self:flex-start;margin-top:0.5rem;">Save System Settings</button>
    </div>
    <div class="settings-tab-content" data-tab="advanced" style="display:none;flex-direction:column;gap:0.75rem;">
      <div class="form-field"><label style="font-size:0.75rem;color:var(--text-muted);">Temperature: <span id="temperatureValue">0.7</span></label><input type="range" id="temperatureSlider" min="0" max="2" step="0.1" value="0.7" style="width:100%;margin-top:0.2rem;"></div>
      <div class="form-field"><label style="font-size:0.75rem;color:var(--text-muted);">Top P: <span id="topPValue">0.90</span></label><input type="range" id="topPSlider" min="0" max="1" step="0.01" value="0.9" style="width:100%;margin-top:0.2rem;"></div>
      <div class="form-field"><label style="font-size:0.75rem;color:var(--text-muted);">Max Tokens: <span id="maxTokensValue">2048</span></label><input type="range" id="maxTokensSlider" min="256" max="8192" step="256" value="2048" style="width:100%;margin-top:0.2rem;"></div>
      <div class="form-field"><label style="font-size:0.75rem;color:var(--text-muted);">Top K: <span id="topKValue">40</span></label><input type="range" id="topKSlider" min="1" max="100" step="1" value="40" style="width:100%;margin-top:0.2rem;"></div>
      <div class="form-field" style="display:flex;align-items:center;gap:0.5rem;"><input type="checkbox" id="streamingToggle" checked><label style="font-size:0.8rem;color:var(--text);">Streaming</label></div>
      <div class="form-field" style="display:flex;align-items:center;gap:0.5rem;"><input type="checkbox" id="thinkingToggle"><label style="font-size:0.8rem;color:var(--text);">Show Thinking</label></div>
      <div class="form-field" style="display:flex;align-items:center;gap:0.5rem;"><input type="checkbox" id="toolVisibilityToggle" checked><label style="font-size:0.8rem;color:var(--text);">Show Tool Execution</label></div>
      <button id="saveAdvancedBtn" class="btn-accent" style="align-self:flex-start;margin-top:0.5rem;">Save Advanced</button>
    </div>
  `;

  // Wire tab switching
  body.querySelectorAll('.settings-tab').forEach(tab => {
    tab.addEventListener('click', () => {
      const tabName = tab.dataset.tab;
      body.querySelectorAll('.settings-tab').forEach(t => {
        t.classList.remove('active');
        t.style.borderBottomColor = 'transparent';
        t.style.color = 'var(--text-muted)';
      });
      tab.classList.add('active');
      tab.style.borderBottomColor = 'var(--accent)';
      tab.style.color = 'var(--text)';
      body.querySelectorAll('.settings-tab-content').forEach(c => {
        c.style.display = 'none';
        c.classList.remove('active');
      });
      const content = body.querySelector(`.settings-tab-content[data-tab="${tabName}"]`);
      if (content) { content.style.display = 'flex'; content.classList.add('active'); }
    });
  });
  // Activate first tab styling
  const firstTab = body.querySelector('.settings-tab.active');
  if (firstTab) { firstTab.style.borderBottomColor = 'var(--accent)'; firstTab.style.color = 'var(--text)'; }

  // Wire save buttons
  body.querySelector('#saveProfileBtn')?.addEventListener('click', async () => {
    const mediumDefault = body.querySelector('#profileLlmModel')?.value || '';
    const currentMediumModels = (window.__latestProfileSettings?.medium_models || {});
    const data = {
      name: body.querySelector('#profileName')?.value || '',
      preferred_language: body.querySelector('#profileLang')?.value || 'en',
      response_style: body.querySelector('#profileStyle')?.value || 'detailed',
      llm_base_url: body.querySelector('#profileLlmUrl')?.value || '',
      // Keep legacy key in sync, but runtime uses medium_models.default.
      llm_model_name: mediumDefault,
      medium_models: {
        default: mediumDefault || currentMediumModels.default || '',
        vision: currentMediumModels.vision || 'zai-org/glm-4.6v-flash',
        longctx: currentMediumModels.longctx || 'lfm2-8b-a1b',
      },
    };
    try {
      await saveProfileSettings(data);
      _showNotification('Profile saved');
    } catch (e) { _showNotification('Failed to save profile'); }
  });

  body.querySelector('#savePersonaBtn')?.addEventListener('click', async () => {
    const data = {
      name: body.querySelector('#personaName')?.value || '',
      tone: body.querySelector('#personaTone')?.value || '',
    };
    try {
      await fetch(API_BASE + '/api/persona', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data),
      });
      _showNotification('Persona saved');
    } catch (e) { _showNotification('Failed to save persona'); }
  });

  body.querySelector('#saveSystemPromptBtn')?.addEventListener('click', async () => {
    const data = {
      system_prompt: document.getElementById('systemPromptInput')?.value || '',
      custom_instructions: document.getElementById('customInstructionsInput')?.value || '',
    };
    try {
      await saveSystemSettings(data);
      _showNotification('System settings saved');
    } catch (e) { _showNotification('Failed to save system settings'); }
  });

  body.querySelector('#saveAdvancedBtn')?.addEventListener('click', async () => {
    const data = {
      temperature: parseFloat(document.getElementById('temperatureSlider')?.value || 0.7),
      top_p: parseFloat(document.getElementById('topPSlider')?.value || 0.9),
      max_tokens: parseInt(document.getElementById('maxTokensSlider')?.value || 2048),
      top_k: parseInt(document.getElementById('topKSlider')?.value || 40),
      streaming_enabled: document.getElementById('streamingToggle')?.checked ?? true,
      show_thinking: document.getElementById('thinkingToggle')?.checked ?? false,
      show_tool_execution: document.getElementById('toolVisibilityToggle')?.checked ?? true,
    };
    try {
      await saveAdvancedSettings(data);
      _showNotification('Advanced settings saved');
    } catch (e) { _showNotification('Failed to save advanced settings'); }
  });

  // Wire slider display updates
  body.querySelector('#temperatureSlider')?.addEventListener('input', (e) => {
    const v = document.getElementById('temperatureValue'); if (v) v.textContent = parseFloat(e.target.value).toFixed(1);
  });
  body.querySelector('#topPSlider')?.addEventListener('input', (e) => {
    const v = document.getElementById('topPValue'); if (v) v.textContent = parseFloat(e.target.value).toFixed(2);
  });
  body.querySelector('#maxTokensSlider')?.addEventListener('input', (e) => {
    const v = document.getElementById('maxTokensValue'); if (v) v.textContent = parseInt(e.target.value);
  });
  body.querySelector('#topKSlider')?.addEventListener('input', (e) => {
    const v = document.getElementById('topKValue'); if (v) v.textContent = parseInt(e.target.value);
  });

  // Populate from API
  fetch(API_BASE + '/api/unified-settings').then(r => r.ok ? r.json() : null).then(settings => {
    if (!settings) return;
    const el = (id) => document.getElementById(id);
    if (el('profileName')) el('profileName').value = settings.name || '';
    if (el('profileLang')) el('profileLang').value = settings.preferred_language || 'en';
    if (el('profileStyle')) el('profileStyle').value = settings.response_style || 'detailed';
    if (el('profileLlmUrl')) el('profileLlmUrl').value = settings.llm_base_url || '';
    if (el('profileLlmModel')) {
      const fromMap = settings.medium_models && settings.medium_models.default;
      el('profileLlmModel').value = fromMap || settings.llm_model_name || '';
    }
    if (el('temperatureSlider')) { el('temperatureSlider').value = settings.temperature || 0.7; if (el('temperatureValue')) el('temperatureValue').textContent = parseFloat(settings.temperature || 0.7).toFixed(1); }
    if (el('topPSlider')) { el('topPSlider').value = settings.top_p || 0.9; if (el('topPValue')) el('topPValue').textContent = parseFloat(settings.top_p || 0.9).toFixed(2); }
    if (el('maxTokensSlider')) { el('maxTokensSlider').value = settings.max_tokens || 2048; if (el('maxTokensValue')) el('maxTokensValue').textContent = parseInt(settings.max_tokens || 2048); }
    if (el('topKSlider')) { el('topKSlider').value = settings.top_k || 40; if (el('topKValue')) el('topKValue').textContent = parseInt(settings.top_k || 40); }
    if (el('streamingToggle')) el('streamingToggle').checked = settings.streaming_enabled !== false;
    if (el('thinkingToggle')) el('thinkingToggle').checked = settings.show_thinking || false;
    if (el('toolVisibilityToggle')) el('toolVisibilityToggle').checked = settings.show_tool_execution !== false;
  }).catch(() => {});

  fetch(API_BASE + '/api/persona').then(r => r.ok ? r.json() : null).then(persona => {
    if (!persona) return;
    const el = (id) => document.getElementById(id);
    if (el('personaName')) el('personaName').value = persona.name || '';
    if (el('personaTone')) el('personaTone').value = persona.tone || '';
  }).catch(() => {});

  fetch(API_BASE + '/api/system-settings').then(r => r.ok ? r.json() : null).then(sys => {
    if (!sys) return;
    const el = (id) => document.getElementById(id);
    if (el('systemPromptInput')) el('systemPromptInput').value = sys.system_prompt || '';
    if (el('customInstructionsInput')) el('customInstructionsInput').value = sys.custom_instructions || '';
  }).catch(() => {});
}

// ─── initAuroraLayout ──────────────────────────────────────────────────────
let _auroraInitialized = false;

function initAuroraLayout() {
  // Initialize BottomInputBar event listeners
  BottomInputBar.init();

  // Render initial state
  LeftPane.renderGreeting(StateManager.userName);
  RightPane.renderUniversalTools();

  // Load data in parallel
  // Note: /api/projects is NOT fetched here — Explorer.init() is the single owner of that fetch
  Promise.all([
    fetch(API_BASE + '/api/unified-settings').then(r => r.ok ? r.json() : null).catch(() => null),
    fetch(API_BASE + '/api/tools').then(r => r.ok ? r.json() : null).catch(() => null),
    fetch(API_BASE + '/api/files?project_id=default').then(r => r.ok ? r.json() : null).catch(() => null),
  ]).then(([settings, tools, files]) => {
    if (settings) {
      StateManager.applySettings(settings);
      LeftPane.renderGreeting(StateManager.userName);
    }
    if (tools) CenterPane.loadTools(Array.isArray(tools) ? tools : tools.tools || []);
    if (files) RightPane.loadFrequentFiles(Array.isArray(files) ? files : files.files || []);

    // Update status
    const dot = document.getElementById('statusDot');
    const txt = document.getElementById('statusText');
    if (dot) { dot.className = 'aurora-dot online'; }
    if (txt) txt.textContent = 'Online';
    StateManager.set('connectionStatus', 'online');
  }).catch(() => {
    // Backend offline — render with defaults, retry health check
    const dot = document.getElementById('statusDot');
    const txt = document.getElementById('statusText');
    if (dot) dot.className = 'aurora-dot offline';
    if (txt) txt.textContent = 'Backend offline';
    _retryHealthCheck();
  });

  // Connect WebSocket
  StateManager.connectWebSocket(StateManager.currentSessionId);

  // Subscribe to state changes for title bar updates
  StateManager.subscribe('TitleBar', (keys) => {
    if (keys.includes('connectionStatus')) {
      const dot = document.getElementById('statusDot');
      const txt = document.getElementById('statusText');
      if (dot) dot.className = `aurora-dot ${StateManager.connectionStatus}`;
      if (txt) {
        const labels = { online: 'Online', connecting: 'Connecting…', offline: 'Offline' };
        txt.textContent = labels[StateManager.connectionStatus] || 'Unknown';
      }
    }
    if (keys.includes('userName') || keys.includes('avatarInitial')) {
      LeftPane.renderGreeting(StateManager.userName);
    }
  });

  // Keyboard shortcuts
  document.addEventListener('keydown', (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
      e.preventDefault();
      const modal = document.getElementById('spotlightModal');
      if (modal) modal.classList.toggle('hidden');
    }
  });

  // ── Pane Resize Drag Logic ──
  _initPaneResize();

  // ── Scroll listener to restore pruned messages ──
  const _chatContainerEl = document.getElementById('chatContainer');
  if (_chatContainerEl) {
    let _scrollThrottleTimer = null;
    _chatContainerEl.addEventListener('scroll', () => {
      if (_scrollThrottleTimer) return;
      _scrollThrottleTimer = setTimeout(() => {
        _scrollThrottleTimer = null;
        if (_chatContainerEl.scrollTop < 150) {
          LeftPane.restorePrunedMessages();
        }
      }, 200);
    });
  }

  // Initialize Lucide icons
  if (window.lucide) lucide.createIcons();

  // ── Initialize new productivity workspace modules ──
  if (window.Explorer && typeof Explorer.init === 'function') Explorer.init();
  if (window.ContextHealthBar && typeof ContextHealthBar.init === 'function') ContextHealthBar.init();
  if (window.Stage && typeof Stage.init === 'function') Stage.init();
  if (window.ToolDock && typeof ToolDock.init === 'function') ToolDock.init();
  if (window.CommandBar && typeof CommandBar.init === 'function') CommandBar.init();
  if (window.OrchestratorPanel && typeof OrchestratorPanel.init === 'function') OrchestratorPanel.init();
  if (window.KnowledgeMap && typeof KnowledgeMap.init === 'function') KnowledgeMap.init();

  // ── Wire cross-module StateManager subscriptions ──
  StateManager.subscribe('AuroraModuleWiring', (changedKeys) => {
    if (changedKeys.includes('activeProjectId')) {
      const pid = StateManager.activeProjectId;
      if (window.ToolDock && typeof ToolDock.updateForProject === 'function') {
        ToolDock.updateForProject(pid);
      }
      if (window.KnowledgeMap && typeof KnowledgeMap.refresh === 'function') {
        KnowledgeMap.refresh(pid);
      }
      if (window.ContextHealthBar && typeof ContextHealthBar.update === 'function') {
        ContextHealthBar.update(0, 0, null);
      }
    }
  });

  // ── Collapse button handlers for left and right panels ──
  const collapseLeftBtn = document.getElementById('collapseLeftBtn');
  if (collapseLeftBtn) {
    collapseLeftBtn.addEventListener('click', () => {
      const explorer = document.getElementById('projectExplorer');
      if (explorer) explorer.classList.toggle('collapsed');
    });
  }
  const collapseRightBtn = document.getElementById('collapseRightBtn');
  if (collapseRightBtn) {
    collapseRightBtn.addEventListener('click', () => {
      const panel = document.getElementById('knowledgePanel');
      if (panel) panel.classList.toggle('collapsed');
    });
  }

  // Expand tab buttons (re-show collapsed panels)
  const expandLeftTab = document.getElementById('expandLeftTab');
  if (expandLeftTab) {
    expandLeftTab.addEventListener('click', () => {
      const explorer = document.getElementById('projectExplorer');
      if (explorer) explorer.classList.remove('collapsed');
    });
  }
  const expandRightTab = document.getElementById('expandRightTab');
  if (expandRightTab) {
    expandRightTab.addEventListener('click', () => {
      const panel = document.getElementById('knowledgePanel');
      if (panel) panel.classList.remove('collapsed');
    });
  }

  // New Project button — handled by Explorer module (no duplicate listener needed)

  _auroraInitialized = true;
}

function _initPaneResize() {
  const handles = document.querySelectorAll('.pane-resize-handle');
  handles.forEach(handle => {
    handle.addEventListener('mousedown', (e) => {
      e.preventDefault();
      const resizeId = handle.dataset.resize;
      handle.classList.add('active');
      const startX = e.clientX;

      let targetPane;
      let startWidth;
      let direction; // 1 = drag right grows, -1 = drag right shrinks

      if (resizeId === 'centerPane-left') {
        targetPane = document.getElementById('centerPane');
        startWidth = targetPane.offsetWidth;
        direction = -1; // dragging left edge right = shrink
      } else if (resizeId === 'centerPane-right') {
        targetPane = document.getElementById('centerPane');
        startWidth = targetPane.offsetWidth;
        direction = 1;
      } else if (resizeId === 'rightPane-left') {
        targetPane = document.getElementById('rightPane');
        startWidth = targetPane.offsetWidth;
        direction = -1;
      }

      if (!targetPane) return;

      const minW = parseInt(getComputedStyle(document.documentElement).getPropertyValue('--aurora-pane-min-side')) || 200;
      const maxW = parseInt(getComputedStyle(document.documentElement).getPropertyValue('--aurora-pane-max-side')) || 420;

      function onMouseMove(ev) {
        const delta = (ev.clientX - startX) * direction;
        const newWidth = Math.min(maxW, Math.max(minW, startWidth + delta));
        targetPane.style.width = newWidth + 'px';
      }

      function onMouseUp() {
        handle.classList.remove('active');
        document.removeEventListener('mousemove', onMouseMove);
        document.removeEventListener('mouseup', onMouseUp);
        document.body.style.cursor = '';
        document.body.style.userSelect = '';
      }

      document.body.style.cursor = 'col-resize';
      document.body.style.userSelect = 'none';
      document.addEventListener('mousemove', onMouseMove);
      document.addEventListener('mouseup', onMouseUp);
    });
  });
}

function _retryHealthCheck() {
  const interval = setInterval(() => {
    fetch(API_BASE + '/api/health').then(r => {
      if (r.ok) {
        clearInterval(interval);
        if (_auroraInitialized) {
          // Already initialized — only refresh data and reconnect WebSocket
          Promise.all([
            fetch(API_BASE + '/api/unified-settings').then(r => r.ok ? r.json() : null).catch(() => null),
            fetch(API_BASE + '/api/tools').then(r => r.ok ? r.json() : null).catch(() => null),
            fetch(API_BASE + '/api/files?project_id=default').then(r => r.ok ? r.json() : null).catch(() => null),
          ]).then(([settings, tools, files]) => {
            if (settings) {
              StateManager.applySettings(settings);
              LeftPane.renderGreeting(StateManager.userName);
            }
            if (tools) CenterPane.loadTools(Array.isArray(tools) ? tools : tools.tools || []);
            if (files) RightPane.loadFrequentFiles(Array.isArray(files) ? files : files.files || []);
            const dot = document.getElementById('statusDot');
            const txt = document.getElementById('statusText');
            if (dot) dot.className = 'aurora-dot online';
            if (txt) txt.textContent = 'Online';
            StateManager.set('connectionStatus', 'online');
          }).catch(() => {});
          // Reconnect WebSocket without full re-init
          StateManager.connectWebSocket(StateManager.currentSessionId);
          // Re-init Explorer only if it hasn't rendered yet (initial fetch failed while backend was offline)
          var _ptCheck = document.getElementById('projectTree');
          if (_ptCheck && !_ptCheck.querySelector('.pv-project-node')) {
            if (window.Explorer && typeof Explorer.init === 'function') Explorer.init();
          }
        } else {
          initAuroraLayout();
        }
      }
    }).catch(() => {});
  }, 5000);
}

// ─── Settings Save Handlers ────────────────────────────────────────────────
function saveProfileSettings(data) {
  return fetch(API_BASE + '/api/profile', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data),
  }).then(r => r.json()).then(result => {
    const profile = result && result.profile ? result.profile : result;
    if (profile && typeof profile === 'object') {
      window.__latestProfileSettings = profile;
      StateManager.applySettings(profile);
    } else {
      StateManager.applySettings(data);
    }
    return result;
  });
}

function saveAdvancedSettings(data) {
  return fetch(API_BASE + '/api/advanced-settings', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data),
  }).then(r => r.json());
}

function saveSystemSettings(data) {
  return fetch(API_BASE + '/api/system-settings', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data),
  }).then(r => r.json());
}

// State management
let currentSessionId = generateUUID();
// socket is managed by StateManager.socket — no global declaration needed
let isReasoning = false;
let pendingFiles = []; // { name, type, data (base64), preview? }
let currentSubPath = ''; // Tracks current folder level in workspace view
let hasSentMessageInCurrentSession = false; // Draft tracking for "New chat" UX
let chatRegisteredInBackend = false; // Whether this thread is registered in the project recents list
let chatProjectIdForThread = 'default'; // Project context used for agent calls + chat registration
let titleGenerationInFlight = false; // Prevent duplicate title generations
// websocketThreadId removed — StateManager tracks WebSocket thread binding
let activeMode = 'tools_on'; // 'tools_on' = local tools + optional web (see webSearchEnabled)
/** When false, backend omits web_search from the tool list (other tools stay on). */
let webSearchEnabled = true;
/** normal | learning | concise | explanatory | formal — sent to LLM system hints */
let responseStyle = 'normal';
let activeProjectId = null;
let currentChatName = '';
let activeAiMessage = null; 
let lastHumanMessage = ""; // For regenerate
let currentModelUsed = "unknown"; // Track which model is being used
let thinkingIndicatorEl = null;
let activeToolName = null;
const liveToolCards = new Map();
let currentView = 'welcome';
let cachedProjects = [];

/** Sync global project list with StateManager so subscribers (e.g. OrchestratorPanel) stay accurate. */
function assignCachedProjects(list) {
    // Guard against transient non-array payloads so sidebar projects do not disappear.
    if (!Array.isArray(list)) return;
    // Keep existing list on accidental empty refresh; the default project should always exist.
    if (list.length === 0 && cachedProjects.length > 0) return;
    cachedProjects = list;
    if (typeof StateManager !== 'undefined') {
        StateManager.set('cachedProjects', cachedProjects);
    }
}

// Helper function to render tool execution cards
function renderToolExecution(toolName, status = 'running', input = null, output = null, error = null) {
    const card = document.createElement('div');
    card.className = 'tool-execution-card';
    
    let statusBadge = '';
    if (status === 'running') {
        statusBadge = '<span class="tool-status-badge tool-status-running"><span class="w-2 h-2 rounded-full bg-yellow-600 animate-pulse"></span>Running...</span>';
    } else if (status === 'success') {
        statusBadge = '<span class="tool-status-badge tool-status-success"><span class="w-2 h-2 rounded-full bg-green-600"></span>Completed</span>';
    } else if (status === 'error') {
        statusBadge = '<span class="tool-status-badge tool-status-error"><span class="w-2 h-2 rounded-full bg-red-600"></span>Failed</span>';
    }
    
    let inputHtml = '';
    if (input) {
        inputHtml = `<div class="tool-input"><strong>Input:</strong><div class="mt-1 text-gray-700">${DOMPurify.sanitize(input)}</div></div>`;
    }
    
    let outputHtml = '';
    if (output) {
        const raw = String(output);
        const longOut = raw.length > 600;
        const safe = DOMPurify.sanitize(raw);
        if (longOut) {
            outputHtml = `<details class="tool-output-details mt-2 border-t border-bordercolor pt-2"><summary class="cursor-pointer text-xs font-semibold text-gray-600 hover:text-gray-900">Raw tool output (${raw.length} chars) — click to expand</summary><div class="tool-output mt-2 max-h-[min(50vh,420px)] overflow-y-auto text-gray-700 text-sm whitespace-pre-wrap break-words">${safe}</div></details>`;
        } else {
            outputHtml = `<div class="tool-output"><strong>Output:</strong><div class="mt-1 text-gray-700">${safe}</div></div>`;
        }
    }
    
    let errorHtml = '';
    if (error) {
        errorHtml = `<div class="tool-input tool-error"><strong>Error:</strong><div class="mt-1 text-red-700">${DOMPurify.sanitize(error)}</div></div>`;
    }
    
    card.innerHTML = `
        <div class="tool-header">
            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 1 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/></svg>
            <span>${DOMPurify.sanitize(String(toolName || 'tool'))}</span>
            ${statusBadge}
        </div>
        ${inputHtml}
        ${outputHtml}
        ${errorHtml}
    `;
    
    return card;
}

// Helper function to render error messages
function renderErrorMessage(title, message, details = null) {
    const div = document.createElement('div');
    div.className = 'error-message';
    
    let html = `<strong>⚠️ ${DOMPurify.sanitize(title)}</strong><p>${DOMPurify.sanitize(message)}</p>`;
    if (details) {
        html += `<div class="text-sm mt-2 opacity-90"><code>${DOMPurify.sanitize(details)}</code></div>`;
    }
    
    div.innerHTML = html;
    return div;
}

// Helper function for loading skeleton
function renderLoadingSkeleton() {
    const div = document.createElement('div');
    div.className = 'space-y-2';
    div.innerHTML = `
        <div class="skeleton-loader" style="width: 85%;"></div>
        <div class="skeleton-loader" style="width: 95%;"></div>
        <div class="skeleton-loader" style="width: 70%;"></div>
    `;
    return div;
}

function formatToolLabel(name) {
    if (!name) return "";
    return String(name).replace(/_/g, ' ');
}

function getModelBadgeClass(model) {
    if (!model) return 'model-badge-small';
    if (model.includes('fallback')) return 'model-badge-fallback';
    if (model.startsWith('large') || model.startsWith('cloud')) return 'model-badge-cloud';
    if (model.startsWith('medium')) return 'model-badge-medium';
    return 'model-badge-small';
}

function getModelBadgeIcon(model) {
    if (!model) return '';
    if (model.includes('fallback')) return '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>';
    if (model.startsWith('large') || model.startsWith('cloud')) return '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 10h-1.26A8 8 0 1 0 9 20h9a5 5 0 0 0 0-10z"/></svg>';
    return '';
}

function renderTokenUsage(tokenUsage) {
    if (!tokenUsage || (!tokenUsage.prompt_tokens && !tokenUsage.completion_tokens)) return '';
    return `<span class="cloud-token-indicator">↑${tokenUsage.prompt_tokens} ↓${tokenUsage.completion_tokens}</span>`;
}

function showSwapIndicator(model) {
    let el = document.getElementById('swapIndicator');
    if (!el) {
        el = document.createElement('div');
        el.id = 'swapIndicator';
        el.className = 'swap-indicator';
        document.getElementById('messagesArea')?.appendChild(el);
    }
    const label = model ? model.replace('medium-', '').replace('large-', '') : 'model';
    el.textContent = `Switching to ${label} model...`;
    el.classList.remove('hidden');
}

function hideSwapIndicator() {
    const el = document.getElementById('swapIndicator');
    if (el) el.classList.add('hidden');
}

function showThinkingIndicator() {
    if (thinkingIndicatorEl) return;
    const wrapper = document.createElement('div');
    wrapper.className = 'flex gap-4 group-msg mb-6';
    wrapper.dataset.sender = 'agent-thinking';

    const avatar = document.createElement('div');
    avatar.className = 'w-8 h-8 rounded shrink-0 bg-anthropic flex items-center justify-center text-white mt-1';
    avatar.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 8V4H8"/><rect x="4" y="8" width="16" height="12" rx="2"/><path d="M2 14h2"/><path d="M20 14h2"/><path d="M15 13v2"/><path d="M9 13v2"/></svg>';
    wrapper.appendChild(avatar);

    const content = document.createElement('div');
    content.className = 'flex-1 message-content text-base text-textdark';
    content.innerHTML = `
        <div class="thinking-pill">
            <span class="thinking-dot"></span>
            <span id="thinkingText">Owlynn is thinking...</span>
        </div>
    `;
    wrapper.appendChild(content);
    const _messagesArea = document.getElementById('messagesArea');
    if (_messagesArea) _messagesArea.appendChild(wrapper);
    thinkingIndicatorEl = wrapper;
    scrollToBottom(true);
}

function updateThinkingIndicatorText() {
    if (!thinkingIndicatorEl) return;
    const textEl = thinkingIndicatorEl.querySelector('#thinkingText');
    if (!textEl) return;
    textEl.textContent = activeToolName
        ? `Running tool: ${formatToolLabel(activeToolName)}`
        : 'Owlynn is thinking...';
}

function clearThinkingIndicator() {
    if (!thinkingIndicatorEl) return;
    thinkingIndicatorEl.remove();
    thinkingIndicatorEl = null;
}

// ─── Router Info Panel ─────────────────────────────────────────────────
function handleRouterInfo(metadata) {
    if (!metadata) return;
    const panel = document.createElement('details');
    panel.className = 'router-info-panel';

    const confidence = typeof metadata.confidence === 'number'
        ? (metadata.confidence * 100).toFixed(0) + '%'
        : '?';
    const summary = document.createElement('summary');
    summary.textContent = `Route: ${metadata.route || '?'} (confidence: ${confidence})`;
    panel.appendChild(summary);

    const body = document.createElement('div');
    body.className = 'router-info-body';

    const lines = [];
    if (metadata.reasoning) lines.push(`Reasoning: ${metadata.reasoning}`);
    if (metadata.classification_source) lines.push(`Source: ${metadata.classification_source}`);
    if (metadata.token_budget) lines.push(`Token budget: ${metadata.token_budget}`);

    if (metadata.swap_decision === 'swapped') {
        lines.push(`Model swap: ${metadata.swap_from || '?'} → ${metadata.swap_to || '?'}`);
    } else if (metadata.swap_decision === 'kept') {
        lines.push(`Swap avoided (kept ${metadata.swap_from || 'current'})`);
    } else if (metadata.swap_decision) {
        lines.push(`Swap: ${metadata.swap_decision}`);
    }

    const features = metadata.features || metadata.features_summary || {};
    const featureParts = [];
    if (features.task_category) featureParts.push(features.task_category);
    if (features.has_images) featureParts.push('images');
    if (features.web_intent) featureParts.push('web search');
    if (features.estimated_tokens) featureParts.push(`~${features.estimated_tokens} tokens`);
    if (featureParts.length) lines.push(`Key features: ${featureParts.join(', ')}`);

    lines.forEach(line => {
        const span = document.createElement('span');
        span.textContent = line;
        body.appendChild(span);
    });

    panel.appendChild(body);

    // Insert into current agent message group instead of standalone
    const _messagesArea = document.getElementById('messagesArea');
    if (_messagesArea) {
        const lastWrapper = _messagesArea.lastElementChild;
        if (lastWrapper && lastWrapper.dataset.sender === 'agent') {
            const content = lastWrapper.querySelector('.message-content') || lastWrapper.querySelector('.msg-body');
            if (content) { content.insertBefore(panel, content.firstChild); return; }
        }
        _messagesArea.appendChild(panel);
    }
}

// ─── Token Budget Indicator ────────────────────────────────────────────
function updateTokenBudgetIndicator(tokensUsed, budgetRemaining) {
    const el = document.getElementById('tokenBudgetIndicator');
    if (!el) return;
    el.classList.remove('hidden', 'budget-normal', 'budget-warning', 'budget-critical');
    const total = (tokensUsed || 0) + (budgetRemaining || 0);
    const percent = total > 0 ? (tokensUsed || 0) / total : 0;
    el.textContent = `${budgetRemaining}/${total} tokens`;
    if (percent > 0.80) {
        el.classList.add('budget-critical');
    } else if (percent > 0.50) {
        el.classList.add('budget-warning');
    } else {
        el.classList.add('budget-normal');
    }
}

function handleTokenBudgetUpdate(data) {
    const el = document.getElementById('tokenBudgetIndicator');
    if (!el) return;
    el.classList.remove('hidden', 'budget-normal', 'budget-warning', 'budget-critical');
    const remaining = data.remaining != null ? data.remaining : 0;
    const total = data.total != null ? data.total : 0;
    const percent = data.percent != null ? data.percent : 0;
    el.textContent = `${remaining}/${total} tokens (${(percent * 100).toFixed(0)}% used)`;
    if (percent > 0.80) {
        el.classList.add('budget-critical');
    } else if (percent > 0.50) {
        el.classList.add('budget-warning');
    } else {
        el.classList.add('budget-normal');
    }
}

// ─── Cloud Budget Warning ──────────────────────────────────────────────
function handleCloudBudgetWarning(data) {
    const el = document.getElementById('cloudBudgetWarning');
    if (!el) return;
    el.classList.remove('hidden', 'level-info', 'level-warning', 'level-critical');
    const level = data.level || 'info';
    el.classList.add(`level-${level}`);
    const percent = data.percent != null ? data.percent.toFixed(1) : '?';
    el.textContent = `Cloud token usage: ${percent}% of daily limit (${data.used || 0}/${data.limit || 0} tokens)`;
    el.classList.remove('hidden');

    // Auto-dismiss info level after 10 seconds
    if (level === 'info') {
        setTimeout(() => {
            el.classList.add('hidden');
        }, 10000);
    }
}

// ─── Memory Updated Notification ───────────────────────────────────────
function handleMemoryUpdated(data) {
    // Legacy agentStatus element removed — show notification via Aurora pattern
    const notif = document.createElement('div');
    notif.className = 'aurora-notification';
    notif.textContent = '🧠 Memory updated';
    document.body.appendChild(notif);
    setTimeout(() => notif.remove(), 3000);
}

// ─── Fallback Chain Display ────────────────────────────────────────────
function showFallbackChain(chain) {
    if (!chain || chain.length <= 1) return;
    // Find the last AI message wrapper to append the chain display
    const _messagesArea = document.getElementById('messagesArea');
    const wrappers = _messagesArea ? _messagesArea.querySelectorAll('[data-sender="agent"]') : [];
    const lastWrapper = wrappers.length > 0 ? wrappers[wrappers.length - 1] : null;
    if (!lastWrapper) return;
    const contentDiv = lastWrapper.querySelector('.message-content') || lastWrapper.lastElementChild;
    if (!contentDiv) return;

    // Remove any existing chain display
    const existing = contentDiv.querySelector('.fallback-chain-display');
    if (existing) existing.remove();

    const container = document.createElement('div');
    container.className = 'fallback-chain-display';
    container.innerHTML = '<span style="font-weight:500;margin-right:0.2rem;">Models:</span>';

    chain.forEach((step, i) => {
        if (i > 0) {
            const arrow = document.createElement('span');
            arrow.className = 'chain-arrow';
            arrow.textContent = '→';
            container.appendChild(arrow);
        }
        const stepEl = document.createElement('span');
        stepEl.className = `chain-step ${step.status || ''}`;
        stepEl.textContent = step.model || '?';
        if (step.reason && step.status === 'failed') {
            stepEl.title = step.reason;
        }
        container.appendChild(stepEl);
    });

    contentDiv.appendChild(container);
}

function resetTransientExecutionUI() {
    clearThinkingIndicator();
    activeToolName = null;
    liveToolCards.clear();
}

/**
 * DOM anchor for streamed answer + live tool cards: keep tools above the answer and
 * the answer above footer actions (copy/regenerate), not at the very end of the bubble.
 */
function getAgentAnswerAnchor(contentDiv) {
    if (!contentDiv) return null;
    return contentDiv.querySelector('.agent-final-answer')
        || contentDiv.querySelector('.message-actions');
}

/** Insert a live tool card above the streamed/final answer (and above message actions). */
function insertAgentToolCard(contentDiv, toolCard) {
    if (!contentDiv || !toolCard) return;
    const anchor = getAgentAnswerAnchor(contentDiv);
    if (anchor) {
        contentDiv.insertBefore(toolCard, anchor);
    } else {
        contentDiv.appendChild(toolCard);
    }
}

/** Keep streamed final answer after tool cards but before .message-actions. */
function moveActiveAnswerToEnd() {
    if (!activeAiMessage?.mainContainer || !activeAiMessage?.contentDiv) return;
    activeAiMessage.mainContainer.classList.add('agent-final-answer');
    const cd = activeAiMessage.contentDiv;
    const actions = cd.querySelector('.message-actions');
    if (actions) {
        cd.insertBefore(activeAiMessage.mainContainer, actions);
    } else {
        cd.appendChild(activeAiMessage.mainContainer);
    }
}

// ─── DOM Helpers (Aurora) ────────────────────────────────────────────────────
// Elements that exist in the Aurora index.html are accessed inline via
// document.getElementById() where needed, or through Aurora module helpers
// (LeftPane, BottomInputBar, etc.).  Legacy global declarations removed.

async function loadSettingsData() {
    try {
        // Try unified endpoint first (single round-trip)
        let profile = null;
        let advancedSettings = null;
        let unifiedOk = false;
        try {
            const unifiedRes = await fetch(API_BASE + '/api/unified-settings');
            if (unifiedRes.ok) {
                const unified = await unifiedRes.json();
                profile = unified;
                advancedSettings = unified;
                unifiedOk = true;
            }
        } catch (_) { /* fall through to individual fetches */ }

        let persona, memories, systemSettings, topicsData, interestsData, conversationsData;

        if (unifiedOk) {
            // Fetch remaining endpoints that aren't part of unified
            const [personaRes, memoriesRes, systemRes, topicsRes, interestsRes, conversationsRes] = await Promise.all([
                fetch(API_BASE + '/api/persona'),
                fetch(API_BASE + '/api/memories'),
                fetch(API_BASE + '/api/system-settings').catch(() => null),
                fetch(API_BASE + '/api/topics').catch(() => null),
                fetch(API_BASE + '/api/interests').catch(() => null),
                fetch(API_BASE + '/api/conversations').catch(() => null)
            ]);
            persona = await personaRes.json();
            memories = await memoriesRes.json();
            systemSettings = systemRes ? await systemRes.json() : {};
            topicsData = topicsRes ? await topicsRes.json() : { topics: [] };
            interestsData = interestsRes ? await interestsRes.json() : { interests: [] };
            conversationsData = conversationsRes ? await conversationsRes.json() : { conversations: [] };
        } else {
            // Fallback: parallel fetches to individual endpoints
            const [profileRes, personaRes, memoriesRes, systemRes, advancedRes, topicsRes, interestsRes, conversationsRes] = await Promise.all([
                fetch(API_BASE + '/api/profile'),
                fetch(API_BASE + '/api/persona'),
                fetch(API_BASE + '/api/memories'),
                fetch(API_BASE + '/api/system-settings').catch(() => null),
                fetch(API_BASE + '/api/advanced-settings').catch(() => null),
                fetch(API_BASE + '/api/topics').catch(() => null),
                fetch(API_BASE + '/api/interests').catch(() => null),
                fetch(API_BASE + '/api/conversations').catch(() => null)
            ]);
            profile = await profileRes.json();
            persona = await personaRes.json();
            memories = await memoriesRes.json();
            systemSettings = systemRes ? await systemRes.json() : {};
            advancedSettings = advancedRes ? await advancedRes.json() : {};
            topicsData = topicsRes ? await topicsRes.json() : { topics: [] };
            interestsData = interestsRes ? await interestsRes.json() : { interests: [] };
            conversationsData = conversationsRes ? await conversationsRes.json() : { conversations: [] };
        }

        // Populate Profile — settings form fields created by renderSettingsUI()
        const profileNameInput = document.querySelector('#profileName');
        const profileLangInput = document.querySelector('#profileLang');
        const profileStyleInput = document.querySelector('#profileStyle');
        const profileLlmUrlInput = document.querySelector('#profileLlmUrl');
        const profileLlmModelInput = document.querySelector('#profileLlmModel');
        if (profileNameInput) profileNameInput.value = profile.name || '';
        // Update welcome heading and sidebar profile name
        const welcomeH = document.getElementById('welcomeHeading');
        if (welcomeH) welcomeH.textContent = `Welcome, ${profile.name || 'User'}`;
        const profileDisp = document.getElementById('profileNameDisplay');
        if (profileDisp) profileDisp.textContent = profile.name || 'User';
        const profileAvatar = document.querySelector('.profile-avatar');
        if (profileAvatar) profileAvatar.textContent = (profile.name || 'U')[0].toUpperCase();
        if (profileLangInput) profileLangInput.value = profile.preferred_language || 'en';
        if (profileStyleInput) profileStyleInput.value = profile.response_style || 'detailed';
        if (profileLlmUrlInput) profileLlmUrlInput.value = profile.llm_base_url || 'http://127.0.0.1:8080/v1';
        if (profileLlmModelInput) {
            const fromMap = profile.medium_models && profile.medium_models.default;
            profileLlmModelInput.value = fromMap || profile.llm_model_name || 'qwen/qwen3.5-9b';
        }
        // Populate new small/medium/cloud LLM fields
        const smallUrlEl = document.getElementById('profileSmallLlmUrl');
        const smallModelEl = document.getElementById('profileSmallLlmModel');
        if (smallUrlEl) smallUrlEl.value = profile.small_llm_base_url || 'http://127.0.0.1:1234/v1';
        if (smallModelEl) smallModelEl.value = profile.small_llm_model_name || '';

        // Medium models
        const medModels = profile.medium_models || {};
        const mediumDefaultEl = document.getElementById('profileMediumDefault');
        const mediumVisionEl = document.getElementById('profileMediumVision');
        const mediumLongctxEl = document.getElementById('profileMediumLongctx');
        const cloudUrlEl = document.getElementById('profileCloudUrl');
        const cloudModelEl = document.getElementById('profileCloudModel');
        const cloudApiKeyEl = document.getElementById('profileCloudApiKey');
        if (mediumDefaultEl) mediumDefaultEl.value = medModels.default || 'qwen/qwen3.5-9b';
        if (mediumVisionEl) mediumVisionEl.value = medModels.vision || 'zai-org/glm-4.6v-flash';
        if (mediumLongctxEl) mediumLongctxEl.value = medModels.longctx || 'lfm2-8b-a1b';
        if (cloudUrlEl) cloudUrlEl.value = profile.cloud_llm_base_url || 'https://api.deepseek.com/v1';
        if (cloudModelEl) cloudModelEl.value = profile.cloud_llm_model_name || 'deepseek-chat';
        if (cloudApiKeyEl) cloudApiKeyEl.value = profile.deepseek_api_key ? '••••••••' : '';

        updateComposerStyleQuickLabel();

        // Populate Persona
        const personaNameInput = document.querySelector('#personaName');
        const personaToneInput = document.querySelector('#personaTone');
        const agentNameDisplay = document.querySelector('#agentNameDisplay');
        const agentRoleDisplay = document.querySelector('#agentRoleDisplay');
        if (personaNameInput) personaNameInput.value = persona.name || '';
        if (personaToneInput) personaToneInput.value = persona.tone || '';
        if (agentNameDisplay) agentNameDisplay.innerHTML = `
            <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="text-anthropic"><path d="M12 2a8 8 0 0 0-8 8c0 5.4 7.05 11.5 7.35 11.76a1 1 0 0 0 1.3 0C12.95 21.5 20 15.4 20 10a8 8 0 0 0-8-8z"/><circle cx="12" cy="10" r="3"/></svg>
            ${persona.name || 'Owlynn'}
        `;
        if (agentRoleDisplay) agentRoleDisplay.innerText = persona.role || '';

        // Populate System Settings
        if (systemPromptInput) {
            systemPromptInput.value = systemSettings.system_prompt || DEFAULT_SYSTEM_PROMPT;
        }
        if (customInstructionsInput) {
            customInstructionsInput.value = systemSettings.custom_instructions || '';
        }

        // Populate Advanced Settings
        if (temperatureSlider) {
            temperatureSlider.value = advancedSettings.temperature || 0.7;
            if (temperatureValue) temperatureValue.textContent = parseFloat(temperatureSlider.value).toFixed(1);
        }
        if (topPSlider) {
            topPSlider.value = advancedSettings.top_p || 0.9;
            if (topPValue) topPValue.textContent = parseFloat(topPSlider.value).toFixed(2);
        }
        if (maxTokensSlider) {
            maxTokensSlider.value = advancedSettings.max_tokens || 2048;
            if (maxTokensValue) maxTokensValue.textContent = parseInt(maxTokensSlider.value);
        }
        if (topKSlider) {
            topKSlider.value = advancedSettings.top_k || 40;
            if (topKValue) topKValue.textContent = parseInt(topKSlider.value);
        }
        if (streamingToggle) streamingToggle.checked = advancedSettings.streaming_enabled !== false;
        if (thinkingToggle) thinkingToggle.checked = advancedSettings.show_thinking || false;
        if (toolVisibilityToggle) toolVisibilityToggle.checked = advancedSettings.show_tool_execution !== false;
        const lmStudioFoldEl = document.getElementById('lmStudioFoldToggle');
        if (lmStudioFoldEl) lmStudioFoldEl.checked = advancedSettings.lm_studio_fold_system !== false;

        // Populate Routing & Cloud advanced settings
        const cloudEscalationEl = document.getElementById('cloudEscalationToggle');
        const cloudAnonymizationEl = document.getElementById('cloudAnonymizationToggle');
        const routerHitlEl = document.getElementById('routerHitlToggle');
        const routerThresholdEl = document.getElementById('routerThresholdSlider');
        const thresholdValueEl = document.getElementById('thresholdValue');
        const customSensitiveEl = document.getElementById('customSensitiveTerms');
        const redisUrlEl = document.getElementById('redisUrlInput');
        if (cloudEscalationEl) cloudEscalationEl.checked = profile.cloud_escalation_enabled !== false;
        if (cloudAnonymizationEl) cloudAnonymizationEl.checked = profile.cloud_anonymization_enabled !== false;
        if (routerHitlEl) routerHitlEl.checked = profile.router_hitl_enabled !== false;
        if (routerThresholdEl) routerThresholdEl.value = profile.router_clarification_threshold || 0.6;
        if (thresholdValueEl) thresholdValueEl.textContent = profile.router_clarification_threshold || 0.6;
        if (customSensitiveEl) customSensitiveEl.value = (profile.custom_sensitive_terms || []).join(', ');
        if (redisUrlEl) redisUrlEl.value = profile.redis_url || 'redis://localhost:6379';

        // Cache latest loaded profile for safe partial settings saves.
        window.__latestProfileSettings = profile;

        // Populate Memories
        const memoriesCountEl = document.querySelector('#memoriesCount');
        if (memoriesCountEl) memoriesCountEl.innerText = memories.length || 0;
        renderMemories(memories);

        // Populate Topics
        renderTrackedTopics(topicsData.topics || []);

        // Populate Interests
        renderDetectedInterests(interestsData.interests || []);

        // Populate Conversations
        renderRecentConversations(conversationsData.conversations || []);

    } catch (e) {
        // settings load error silenced
    }
}

function updateComposerStyleQuickLabel() {
    const el = document.getElementById('composerStyleQuickLabel');
    const welcomeEl = document.getElementById('welcomeStyleLabel');
    const styleMap = {
        normal: 'Normal',
        learning: 'Learning',
        concise: 'Concise',
        explanatory: 'Explanatory',
        formal: 'Formal',
    };
    const text = `Style: ${styleMap[responseStyle] || 'Normal'}`;
    if (el) el.textContent = text;
    if (welcomeEl) welcomeEl.textContent = text;
}

function setComposerWebSearchUI() {
    const chk = document.getElementById('composerWebSearchCheck');
    if (chk) chk.classList.toggle('hidden', !webSearchEnabled);
    const row = document.getElementById('composerMenuWebSearch');
    if (row) row.setAttribute('aria-pressed', webSearchEnabled ? 'true' : 'false');
}

function setComposerStyleUI() {
    document.querySelectorAll('.composer-style-option').forEach((b) => {
        const st = b.getAttribute('data-style');
        const check = b.querySelector('.style-check');
        const on = st === responseStyle;
        b.classList.toggle('active-style', on);
        if (check) check.classList.toggle('hidden', !on);
    });
    updateComposerStyleQuickLabel();
}

function closeComposerPlusMenu() {
    document.getElementById('composerPlusMenu')?.classList.add('hidden');
    document.getElementById('composerStyleSubmenu')?.classList.add('hidden');
    document.getElementById('composerPlusBtn')?.setAttribute('aria-expanded', 'false');
}

/** Clamp for viewport positioning */
function clampComposer(n, min, max) {
    return Math.max(min, Math.min(max, n));
}

/**
 * Position fixed menu above anchor. align: 'start' | 'end' (match left or right edge like style pill).
 */
function positionMenuAboveAnchor(menuEl, anchorEl, align = 'start', gap = 8) {
    if (!menuEl || !anchorEl) return;
    menuEl.style.position = 'fixed';
    menuEl.classList.remove('hidden');
    const ar = anchorEl.getBoundingClientRect();
    let br = menuEl.getBoundingClientRect();
    let top = ar.top - br.height - gap;
    let left = align === 'end' ? ar.right - br.width : ar.left;
    if (top < 8) {
        top = ar.bottom + gap;
    }
    top = clampComposer(top, 8, window.innerHeight - br.height - 8);
    left = clampComposer(left, 8, window.innerWidth - br.width - 8);
    menuEl.style.top = `${Math.round(top)}px`;
    menuEl.style.left = `${Math.round(left)}px`;
}

function positionStyleSubmenuBesideMainMenu() {
    const main = document.getElementById('composerPlusMenu');
    const sub = document.getElementById('composerStyleSubmenu');
    if (!main || !sub || main.classList.contains('hidden')) return;
    sub.style.position = 'fixed';
    sub.classList.remove('hidden');
    const mr = main.getBoundingClientRect();
    let sr = sub.getBoundingClientRect();
    let left = mr.right + 8;
    let top = mr.bottom - sr.height;
    if (left + sr.width > window.innerWidth - 8) {
        left = mr.left - sr.width - 8;
    }
    top = clampComposer(top, 8, window.innerHeight - sr.height - 8);
    left = clampComposer(left, 8, window.innerWidth - sr.width - 8);
    sub.style.top = `${Math.round(top)}px`;
    sub.style.left = `${Math.round(left)}px`;
}

function toggleComposerPlusMenu(anchorEl) {
    const menu = document.getElementById('composerPlusMenu');
    const sub = document.getElementById('composerStyleSubmenu');
    const plus = document.getElementById('composerPlusBtn');
    if (!menu || !anchorEl) return;
    if (!menu.classList.contains('hidden')) {
        closeComposerPlusMenu();
        return;
    }
    sub?.classList.add('hidden');
    positionMenuAboveAnchor(menu, anchorEl, 'start', 8);
    plus?.setAttribute('aria-expanded', 'true');
}

/** Style pill: only the style list (not the full + menu). */
function toggleStyleSubmenuOnly(anchorEl) {
    const menu = document.getElementById('composerPlusMenu');
    const sub = document.getElementById('composerStyleSubmenu');
    if (!sub || !anchorEl) return;
    if (!sub.classList.contains('hidden')) {
        sub.classList.add('hidden');
        return;
    }
    menu?.classList.add('hidden');
    document.getElementById('composerPlusBtn')?.setAttribute('aria-expanded', 'false');
    positionMenuAboveAnchor(sub, anchorEl, 'end', 8);
}

function initComposerUI() {
    const plus = document.getElementById('composerPlusBtn');
    const menu = document.getElementById('composerPlusMenu');
    if (!plus || !menu) return;

    plus.addEventListener('click', (e) => {
        e.stopPropagation();
        toggleComposerPlusMenu(plus);
    });

    document.getElementById('composerMenuAttach')?.addEventListener('click', (e) => {
        e.stopPropagation();
        document.getElementById('fileInput')?.click();
        closeComposerPlusMenu();
    });

    document.getElementById('composerMenuWebSearch')?.addEventListener('click', (e) => {
        e.stopPropagation();
        webSearchEnabled = !webSearchEnabled;
        setComposerWebSearchUI();
    });

    document.getElementById('composerMenuStyleBtn')?.addEventListener('click', (e) => {
        e.stopPropagation();
        const sub = document.getElementById('composerStyleSubmenu');
        const main = document.getElementById('composerPlusMenu');
        if (!sub || !main || main.classList.contains('hidden')) return;
        if (sub.classList.contains('hidden')) {
            positionStyleSubmenuBesideMainMenu();
        } else {
            sub.classList.add('hidden');
        }
    });

    document.querySelectorAll('.composer-style-option').forEach((btn) => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            responseStyle = btn.getAttribute('data-style') || 'normal';
            setComposerStyleUI();
            closeComposerPlusMenu();
        });
    });

    document.getElementById('composerMenuProject')?.addEventListener('click', (e) => {
        e.stopPropagation();
        closeComposerPlusMenu();
        document.getElementById('nav-projects')?.click();
    });

    document.getElementById('composerMenuGithub')?.addEventListener('click', (e) => {
        e.stopPropagation();
        closeComposerPlusMenu();
        alert('GitHub import is coming soon.');
    });

    document.getElementById('composerMenuConnectors')?.addEventListener('click', (e) => {
        e.stopPropagation();
        closeComposerPlusMenu();
        document.getElementById('nav-customize')?.click();
        document.getElementById('customizeConnectorsTabBtn')?.click();
    });

    document.getElementById('composerStyleQuickBtn')?.addEventListener('click', (e) => {
        e.stopPropagation();
        toggleStyleSubmenuOnly(e.currentTarget);
    });

    document.addEventListener('click', (ev) => {
        if (
            ev.target.closest?.('#composerPlusBtn') ||
            ev.target.closest?.('#composerPlusMenu') ||
            ev.target.closest?.('#welcomeAttachBtn') ||
            ev.target.closest?.('#welcomeStyleBtn') ||
            ev.target.closest?.('#composerStyleQuickBtn') ||
            ev.target.closest?.('#composerStyleSubmenu')
        ) {
            return;
        }
        closeComposerPlusMenu();
    });

    setComposerWebSearchUI();
    setComposerStyleUI();
    updateComposerStyleQuickLabel();
}

function renderMemories(memories) {
    const memoriesListEl = document.querySelector('#memoriesList');
    if (!memoriesListEl) return;
    memoriesListEl.innerHTML = '';
    
    if (memories.length === 0) {
        memoriesListEl.innerHTML = '<p class="text-xs text-gray-400 italic text-center py-4">No memories stored yet.</p>';
        return;
    }
    
    memories.forEach(m => {
        const item = document.createElement('div');
        item.className = 'flex items-center justify-between gap-3 p-3 bg-cloud border border-bordercolor rounded-xl text-sm group hover:border-anthropic/30 transition-colors';
        
        item.innerHTML = `
            <div class="flex-1">
                <p class="text-textdark font-medium">${m.fact}</p>
                <p class="text-[10px] text-gray-400 mt-1">${new Date(m.timestamp).toLocaleString()}</p>
            </div>
            <button class="delete-memory-btn p-1.5 rounded-lg text-gray-400 hover:text-red-500 hover:bg-red-50 transition-all opacity-0 group-hover:opacity-100" title="Delete Memory">
                <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><line x1="10" y1="11" x2="10" y2="17"/><line x1="14" y1="11" x2="14" y2="17"/></svg>
            </button>
        `;
        
        item.querySelector('.delete-memory-btn').onclick = () => deleteMemory(m.fact);
        memoriesListEl.appendChild(item);
    });
}

async function deleteMemory(fact) {
    const confirmed = await showCustomConfirm('Forget Memory', `Are you sure you want to forget: "${fact}"?`, true);
    if (!confirmed) return;
    
    try {
        const res = await fetch(API_BASE + '/api/memories', {
            method: 'DELETE',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ fact })
        });
        const data = await res.json();
        if (data.status === 'ok') {
            const memoriesCountEl = document.querySelector('#memoriesCount');
            if (memoriesCountEl) memoriesCountEl.innerText = data.memories.length;
            renderMemories(data.memories);
        }
    } catch (e) {
        // delete memory error silenced
    }
}

function renderTrackedTopics(topics) {
    const topicsEl = document.getElementById('trackedTopics');
    if (!topicsEl) return;
    
    topicsEl.innerHTML = '';
    if (topics.length === 0) {
        topicsEl.innerHTML = '<span class="text-[12px] text-gray-500 italic">No topics tracked yet. They will appear as you chat.</span>';
        return;
    }
    
    topics.forEach(topic => {
        const badge = document.createElement('div');
        badge.className = 'inline-flex items-center gap-2 px-3 py-1.5 bg-blue-100 text-blue-700 rounded-full text-[12px] font-medium border border-blue-200';
        badge.innerHTML = `
            <span>🏷️ ${topic.topic || topic}</span>
            ${topic.count ? `<span class="text-[10px] bg-blue-200 px-1.5 py-0.5 rounded-full">${topic.count}</span>` : ''}
        `;
        topicsEl.appendChild(badge);
    });
}

function renderDetectedInterests(interests) {
    const interestsEl = document.getElementById('detectedInterests');
    if (!interestsEl) return;
    
    interestsEl.innerHTML = '';
    if (interests.length === 0) {
        interestsEl.innerHTML = '<span class="text-[12px] text-gray-500 italic">No interests detected yet. I\'ll learn about you as we chat.</span>';
        return;
    }
    
    interests.forEach(interest => {
        const chip = document.createElement('div');
        chip.className = 'inline-flex items-center gap-2 px-3 py-1.5 bg-green-100 text-green-700 rounded-full text-[12px] font-medium border border-green-200';
        const interestLabel = interest.interest || interest;
        chip.innerHTML = `
            <span>✨ ${interestLabel}</span>
            ${interest.count ? `<span class="text-[10px] bg-green-200 px-1.5 py-0.5 rounded-full">${interest.count}</span>` : ''}
        `;
        interestsEl.appendChild(chip);
    });
}

function renderRecentConversations(conversations) {
    const conversationsEl = document.getElementById('recentConversations');
    if (!conversationsEl) return;
    
    conversationsEl.innerHTML = '';
    if (conversations.length === 0) {
        conversationsEl.innerHTML = '<span class="text-[12px] text-gray-500 italic">No conversations recorded yet.</span>';
        return;
    }
    
    conversations.slice(0, 5).forEach((conv, idx) => {
        const card = document.createElement('div');
        card.className = 'p-2.5 bg-white border border-purple-200 rounded-lg hover:border-purple-300 hover:bg-purple-50 transition-colors cursor-pointer';
        const summary = (conv.summary || conv.user_message || 'Conversation').substring(0, 60) + '...';
        const timestamp = conv.timestamp ? new Date(conv.timestamp).toLocaleDateString() : 'Recent';
        card.innerHTML = `
            <p class="text-[12px] font-medium text-gray-700">${summary}</p>
            <p class="text-[10px] text-gray-500 mt-1">${timestamp}</p>
        `;
        conversationsEl.appendChild(card);
    });
}

// Legacy addMemoryBtn/newMemoryInput — don't exist in Aurora HTML
// Memory management handled by renderSettingsUI() when implemented

// Legacy addProjectBtn — doesn't exist in Aurora HTML
document.getElementById('addProjectViewBtn')?.addEventListener('click', handleCreateProject);

async function loadProjects() {
    try {
        const res = await fetch(API_BASE + '/api/projects');
        const projects = await res.json();
        if (!Array.isArray(projects) || projects.length === 0) return;

        // Normalize active project selection from localStorage/current state/default.
        const resolvedProjectId = (window.WorkspaceState && typeof WorkspaceState.syncFromProjects === 'function')
            ? WorkspaceState.syncFromProjects(projects, activeProjectId)
            : (activeProjectId || 'default');
        const normalizedProjectId = setWorkspaceProject(resolvedProjectId, true);
        setChatProjectContext(normalizedProjectId);
        if (typeof StateManager !== 'undefined') {
            StateManager.set('activeProjectId', normalizedProjectId);
        }

        assignCachedProjects(projects);
        renderProjects(projects);
        renderWelcomeRecents();
        renderProjectInspector(projects.find((p) => p.id === activeProjectId) || null);
        setWorkspaceVisibility();
        if (typeof loadWorkspaceFiles === 'function') loadWorkspaceFiles();
        // Populate sidebar recents from the active/default project
        const activeProject = projects.find((p) => p.id === getEffectiveProjectId());
        if (activeProject) {
            renderProjectChats(activeProject.chats || []);
        }
    } catch (e) {
        // load projects error silenced
    }
}

function renderProjects(projects) {
    const projectsListEl = document.querySelector('#projectsList');
    if (!projectsListEl) {
        if (window.Explorer && typeof Explorer.updateProjects === 'function') {
            Explorer.updateProjects(projects);
        }
        return;
    }
    projectsListEl.innerHTML = '';
    
    projects.forEach(project => {
        const isActive = project.id === activeProjectId;
        const item = document.createElement('div');
        item.className = `group flex items-center gap-2 px-2 py-1.5 rounded-md text-sm cursor-pointer transition-colors ${
            isActive ? 'bg-white border border-anthropic/20 shadow-sm' : 'hover:bg-gray-100 text-gray-600'
        }`;
        
        item.innerHTML = `
            <span class="w-2 h-2 rounded-full ${isActive ? 'bg-anthropic' : 'bg-gray-300'}"></span>
            <span class="truncate flex-1 ${isActive ? 'font-medium text-textdark' : ''}">${project.name}</span>
            ${project.id !== 'default' ? `
            <div class="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                <button class="edit-project-btn p-1 rounded-md hover:bg-gray-200 text-gray-400 hover:text-anthropic" title="Rename Project">
                    <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/></svg>
                </button>
                <button class="delete-project-btn p-1 rounded-md hover:bg-gray-200 text-gray-400 hover:text-red-500" title="Delete Project">
                    <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
                </button>
            </div>
            ` : ''}
        `;
        
        item.querySelector('.edit-project-btn')?.addEventListener('click', (e) => {
            e.stopPropagation();
            editProject(project.id, project.name);
        });
        
        item.querySelector('.delete-project-btn')?.addEventListener('click', (e) => {
            e.stopPropagation();
            deleteProject(project.id, project.name);
        });
        
        item.onclick = () => StateManager.switchProject(project.id);
        projectsListEl.appendChild(item);
    });
}


async function loadChatHistory(sessionId) {
    const _messagesArea = document.getElementById('messagesArea');
    if (_messagesArea) _messagesArea.innerHTML = '';
    activeAiMessage = null;
    resetTransientExecutionUI();
    
    try {
        const res = await fetch(`${API_BASE}/api/history/${sessionId}`);
        const history = await res.json();
        hasSentMessageInCurrentSession = history && history.length > 0;
        
        if (history.length === 0) {
            renderMessage({ type: 'ai', content: 'Chat started. How can I help you today?' });
            return;
        }
        
        history.forEach(msg => {
            renderMessage(msg);
        });
        
        // Scroll to bottom
        if (_messagesArea) _messagesArea.scrollTop = _messagesArea.scrollHeight;
    } catch (e) {
        hasSentMessageInCurrentSession = false;
        renderMessage({ type: 'ai', content: 'Chat started. How can I help you today?' });
    }
}

function renderProjectFiles(files) {
    const projectFilesList = document.querySelector('#projectFilesList');
    if (!projectFilesList) return;
    projectFilesList.innerHTML = '';
    
    files.forEach(file => {
        const item = document.createElement('div');
        item.className = 'flex items-center gap-2 p-2 bg-white border border-bordercolor rounded text-xs';
        item.innerHTML = `
            <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="text-gray-400"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
            <span class="truncate flex-1">${file.name}</span>
        `;
        projectFilesList.appendChild(item);
    });
}

function renderProjectChats(chats) {
    const projectChatsList = document.getElementById('projectChatsList');
    if (!projectChatsList) return;
    projectChatsList.innerHTML = '';
    
    const sortedChats = [...chats].sort((a, b) => {
        // Pinned chats first
        const aPinned = localStorage.getItem(`pin_${a.id}`) ? 1 : 0;
        const bPinned = localStorage.getItem(`pin_${b.id}`) ? 1 : 0;
        if (bPinned !== aPinned) return bPinned - aPinned;
        return (b.created_at || 0) - (a.created_at || 0);
    });
    
    sortedChats.forEach(chat => {
        const isActive = chat.id === currentSessionId;
        if (isActive) currentChatName = chat.name || '';
        const isPinned = Boolean(localStorage.getItem(`pin_${chat.id}`));
        
        const item = document.createElement('div');
        item.className = `recent-item${isActive ? ' active' : ''}`;
        item.innerHTML = `
            ${isPinned ? '<span class="recent-pin">*</span>' : ''}
            <span class="recent-title">${DOMPurify.sanitize(chat.name || 'Untitled')}</span>
            <button class="recent-menu-btn" title="More">···</button>
        `;
        
        item.querySelector('.recent-title').onclick = () => switchChat(chat.id);
        item.querySelector('.recent-menu-btn').onclick = (e) => {
            e.stopPropagation();
            showSidebarContextMenu(e, chat, isPinned);
        };
        
        projectChatsList.appendChild(item);
    });
}

function showSidebarContextMenu(event, chat, isPinned) {
    // Remove any existing menu
    document.getElementById('sidebarCtxMenu')?.remove();
    
    const menu = document.createElement('div');
    menu.id = 'sidebarCtxMenu';
    menu.className = 'sidebar-context-menu';
    menu.innerHTML = `
        <button class="ctx-item" data-action="pin">${isPinned ? 'Unpin' : 'Pin to top'}</button>
        <button class="ctx-item" data-action="rename">Rename</button>
        <div class="ctx-divider"></div>
        <button class="ctx-item danger" data-action="delete">Delete</button>
    `;
    
    // Position near the button
    const rect = event.target.getBoundingClientRect();
    menu.style.top = `${rect.bottom + 4}px`;
    menu.style.left = `${Math.min(rect.left, window.innerWidth - 180)}px`;
    document.body.appendChild(menu);
    
    menu.addEventListener('click', async (e) => {
        const action = e.target.dataset.action;
        menu.remove();
        if (action === 'pin') {
            if (isPinned) localStorage.removeItem(`pin_${chat.id}`);
            else localStorage.setItem(`pin_${chat.id}`, '1');
            await refreshSidebarRecents();
        } else if (action === 'rename') {
            editChat(chat.id, chat.name);
        } else if (action === 'delete') {
            deleteChat(chat.id, chat.name);
        }
    });
    
    // Close on click outside
    setTimeout(() => {
        const closer = (e) => {
            if (!menu.contains(e.target)) { menu.remove(); document.removeEventListener('click', closer); }
        };
        document.addEventListener('click', closer);
    }, 10);
}

async function switchChat(sessionId) {
    resetTransientExecutionUI();
    currentSessionId = sessionId;
    navigateView('chat');
    setWorkspaceVisibility();
    
    // Update mapping in localStorage
    const selectedProjectId = getEffectiveProjectId();
    if (selectedProjectId) {
        localStorage.setItem(`project_session_${selectedProjectId}`, currentSessionId);
    }
    
    // Reload UI
    await loadChatHistory(sessionId);
    
    // Reconnect WebSocket to the correct thread
    if (StateManager.socket) {
        StateManager.socket.onclose = null; 
        StateManager.socket.close();
    }
    StateManager.connectWebSocket(currentSessionId);
    
    // Refresh project details to update active chat highlighting
    const res = await fetch(`${API_BASE}/api/projects/${getEffectiveProjectId()}`);
    const project = await res.json();
    setChatProjectContext(getEffectiveProjectId());
    chatRegisteredInBackend = Boolean((project.chats || []).find((c) => c.id === sessionId));
    renderProjectChats(project.chats || []);
    currentChatName = (project.chats || []).find((c) => c.id === sessionId)?.name || '';
    assignCachedProjects(cachedProjects.map(p => p.id === project.id ? project : p));
    renderWelcomeRecents();
    renderProjects(cachedProjects);
}

async function editChat(chatId, currentName) {
    const newName = await showCustomInput('Rename Chat', 'Chat Name', currentName);
    if (!newName || newName === currentName) return;
    
    try {
        await fetch(`${API_BASE}/api/projects/${getEffectiveProjectId()}/chats/${chatId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: newName })
        });
        if (chatId === currentSessionId) currentChatName = newName;
        // Invalidate Explorer cache so renamed chat shows new name
        if (window.Explorer) Explorer.invalidateCache(getEffectiveProjectId());
        // Lightweight refresh — just update sidebar and Explorer
        await refreshSidebarRecents(getEffectiveProjectId());
    } catch (e) {
        // rename chat error silenced
    }
}

async function deleteChat(chatId, chatName) {
    const confirmed = await showCustomConfirm('Delete Chat', `Are you sure you want to delete the chat "${chatName || 'Untitled'}"?`, true);
    if (!confirmed) return;
    
    try {
        await fetch(`${API_BASE}/api/projects/${getEffectiveProjectId()}/chats/${chatId}`, {
            method: 'DELETE'
        });
        // Invalidate Explorer cache so deleted chat disappears
        if (window.Explorer) Explorer.invalidateCache(getEffectiveProjectId());

        if (chatId === currentSessionId) {
            // Deleted the active chat — start a fresh session
            currentSessionId = generateUUID();
            currentChatName = '';
            chatRegisteredInBackend = false;
            localStorage.setItem(`project_session_${getEffectiveProjectId()}`, currentSessionId);
            const _messagesArea = document.getElementById('messagesArea');
            if (_messagesArea) _messagesArea.innerHTML = '';
            if (StateManager.socket) {
                StateManager.socket.onclose = null;
                StateManager.socket.close();
            }
            StateManager.connectWebSocket(currentSessionId);
        }
        // Refresh sidebar and Explorer
        await refreshSidebarRecents(getEffectiveProjectId());
    } catch (e) {
        // delete chat error silenced
    }
}

async function maybeAutoNameCurrentChat(userText, fileNames = []) {
    if (!userText?.trim()) return;
    if (!isUntitledName(currentChatName)) return;
    if (titleGenerationInFlight) return;
    titleGenerationInFlight = true;

    try {
        await ensureChatRegistered();
        const projectId = getChatProjectId();

        // Ask small LLM for a title
        let title = '';
        try {
            const res = await fetch(API_BASE + '/api/chats/generate-title', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message: userText, files: fileNames.map(n => ({ name: n })) })
            });
            const data = await res.json();
            title = (data?.title || '').trim().replace(/\s+/g, ' ').slice(0, 60);
        } catch (_) {}

        // Fallback to local heuristic
        if (!title) title = deriveChatTitle(userText);
        if (!title) return;

        // Save the title
        await fetch(`${API_BASE}/api/projects/${projectId}/chats/${currentSessionId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: title })
        });
        currentChatName = title;

        // Refresh sidebar
        await refreshSidebarRecents(projectId);
    } catch (e) {
        // auto-name error silenced
    } finally {
        titleGenerationInFlight = false;
    }
}

async function refreshSidebarRecents(projectId) {
    try {
        const res = await fetch(`${API_BASE}/api/projects/${projectId || getEffectiveProjectId()}`);
        const project = await res.json();
        assignCachedProjects(cachedProjects.map(p => p.id === project.id ? project : p));
        if (getEffectiveProjectId() === project.id) {
            renderProjectChats(project.chats || []);
        }
        renderProjects(cachedProjects);
    } catch (_) {}
}

async function editProjectInstructions(projectId, currentInstructions) {
    const modal = document.getElementById('customInputModal');
    const titleEl = document.getElementById('customInputTitle');
    const labelEl = document.getElementById('customInputLabel');
    const fieldEl = document.getElementById('customInputField');
    const confirmBtn = document.getElementById('confirmCustomInputBtn');
    const cancelBtn = document.getElementById('cancelCustomInputBtn');
    const closeBtn = document.getElementById('closeCustomInputBtn');
    if (!modal || !fieldEl) return;

    titleEl.textContent = 'Edit Instructions';
    const formArea = fieldEl.parentElement;
    const origHTML = formArea.innerHTML;
    formArea.innerHTML = `
        <div class="form-field">
            <label style="font-size:0.75rem;color:var(--text-muted)">Instructions for this project</label>
            <textarea id="_editProjInstr" rows="6" style="margin-top:0.25rem;resize:vertical" placeholder="Add instructions to tailor Owlynn's responses for this project...">${DOMPurify.sanitize(currentInstructions || '')}</textarea>
        </div>
    `;
    if (labelEl) labelEl.style.display = 'none';
    modal.classList.remove('hidden'); modal.classList.add('flex');
    document.getElementById('_editProjInstr')?.focus();

    const result = await new Promise(resolve => {
        const cleanup = (val) => { modal.classList.add('hidden'); modal.classList.remove('flex'); formArea.innerHTML = origHTML; if (labelEl) labelEl.style.display = ''; confirmBtn.onclick = null; cancelBtn.onclick = null; if (closeBtn) closeBtn.onclick = null; resolve(val); };
        confirmBtn.onclick = () => cleanup(document.getElementById('_editProjInstr')?.value?.trim() ?? null);
        cancelBtn.onclick = () => cleanup(null);
        if (closeBtn) closeBtn.onclick = () => cleanup(null);
    });

    if (result === null) return;
    try {
        await fetch(`${API_BASE}/api/projects/${projectId}`, {
            method: 'PUT', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ instructions: result })
        });
        await loadProjects();
        openProjectDetail(projectId);
    } catch (e) { /* update instructions error silenced */ }
}

async function editProject(projectId, currentName) {
    const project = cachedProjects.find(p => p.id === projectId);
    const currentDesc = project?.instructions || '';

    // Build a two-field modal using the existing customInputModal
    const modal = document.getElementById('customInputModal');
    const titleEl = document.getElementById('customInputTitle');
    const labelEl = document.getElementById('customInputLabel');
    const fieldEl = document.getElementById('customInputField');
    const confirmBtn = document.getElementById('confirmCustomInputBtn');
    const cancelBtn = document.getElementById('cancelCustomInputBtn');
    const closeBtn = document.getElementById('closeCustomInputBtn');
    if (!modal || !fieldEl) return;

    titleEl.textContent = 'Edit Project';

    // Replace the single field with two fields
    const formArea = fieldEl.parentElement;
    const origHTML = formArea.innerHTML;
    formArea.innerHTML = `
        <div class="form-field" style="margin-bottom:0.75rem">
            <label style="font-size:0.75rem;color:var(--text-muted)">Project Name</label>
            <input id="_editProjName" type="text" value="${DOMPurify.sanitize(currentName)}" style="margin-top:0.25rem">
        </div>
        <div class="form-field">
            <label style="font-size:0.75rem;color:var(--text-muted)">Description</label>
            <textarea id="_editProjDesc" rows="3" style="margin-top:0.25rem;resize:vertical">${DOMPurify.sanitize(currentDesc)}</textarea>
        </div>
    `;
    if (labelEl) labelEl.style.display = 'none';

    modal.classList.remove('hidden');
    modal.classList.add('flex');
    document.getElementById('_editProjName')?.focus();

    const result = await new Promise(resolve => {
        const cleanup = (val) => {
            modal.classList.add('hidden');
            modal.classList.remove('flex');
            formArea.innerHTML = origHTML;
            if (labelEl) labelEl.style.display = '';
            confirmBtn.onclick = null;
            cancelBtn.onclick = null;
            if (closeBtn) closeBtn.onclick = null;
            resolve(val);
        };
        confirmBtn.onclick = () => {
            const name = document.getElementById('_editProjName')?.value?.trim();
            const desc = document.getElementById('_editProjDesc')?.value?.trim();
            cleanup({ name, desc });
        };
        cancelBtn.onclick = () => cleanup(null);
        if (closeBtn) closeBtn.onclick = () => cleanup(null);
    });

    if (!result || !result.name) return;

    try {
        await fetch(`${API_BASE}/api/projects/${projectId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: result.name, instructions: result.desc || '' })
        });
        // Invalidate Explorer cache for this project so stale data doesn't persist
        if (window.Explorer && typeof Explorer.invalidateCache === 'function') {
            Explorer.invalidateCache(projectId);
        }
        loadProjects();
        if (currentView === 'projects') loadProjectsGrid();
    } catch (e) {
        // update project error silenced
    }
}

async function deleteProject(projectId, projectName) {
    const confirmed = await showCustomConfirm('Delete Project', `Are you sure you want to delete the project "${projectName}"? This will delete associated workspace files.`, true);
    if (!confirmed) return;
    
    try {
        const res = await fetch(`${API_BASE}/api/projects/${projectId}`, {
            method: 'DELETE'
        });
        const data = await res.json();
        if (data.status === 'ok') {
             // Invalidate Explorer cache for deleted project
             if (window.Explorer && typeof Explorer.invalidateCache === 'function') {
                 Explorer.invalidateCache(projectId);
             }
             if (projectId === activeProjectId) {
                 setWorkspaceProject('default', true);
                  currentChatName = '';
                 setChatProjectContext('default');
                 if (typeof StateManager !== 'undefined') {
                     StateManager.set('activeProjectId', 'default');
                 }
                  setWorkspaceVisibility();
                  navigateView('home');
                  renderProjectInspector(null);
                  renderWelcomeRecents();
                  loadProjects();
             } else {
                  loadProjects();
             }
        } else {
             alert(data.message || 'Failed to delete project');
        }
    } catch (e) {
        // delete project error silenced
    }
}


async function handleCreateProject() {
    const name = await showCustomInput('New Project', 'Project Name');
    if (!name) return;
    
    const instructions = await showCustomInput('Project Details', 'Project Instructions (optional)');
    
    try {
        const res = await fetch(API_BASE + '/api/projects', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, instructions })
        });
        const newProject = await res.json();
        await loadProjects();
        StateManager.switchProject(newProject.id);
        navigateView('chat');
    } catch (e) {
        // create project error silenced
    }
}

// Legacy addProjectBtn removed — doesn't exist in Aurora HTML
document.getElementById('addProjectViewBtn')?.addEventListener('click', handleCreateProject);

// ─── Event Listeners ────────────────────────────────────────────────────────

// Legacy openSettingsBtn/closeSettingsBtn/closeSettingsFooterBtn removed — don't exist in Aurora HTML
// Settings modal open is handled by BottomInputBar.init() via settingsBtn
// Settings modal close is handled by inline onclick in index.html

// Close modal when clicking outside content
document.getElementById('settingsModal')?.addEventListener('click', (e) => {
    const _settingsModal = document.getElementById('settingsModal');
    if (e.target === _settingsModal) {
        _settingsModal.classList.add('hidden');
    }
});

// ===== SETTINGS TABS FUNCTIONALITY =====
const settingsTabs = document.querySelectorAll('.settings-tab');
const tabContents = document.querySelectorAll('.settings-tab-content, .tab-content');

settingsTabs.forEach(tab => {
    tab.addEventListener('click', () => {
        const tabName = tab.getAttribute('data-tab');
        
        // Remove active class from all tabs and contents
        settingsTabs.forEach(t => t.classList.remove('active'));
        tabContents.forEach(c => c.classList.remove('active'));
        
        // Add active class to clicked tab and corresponding content
        tab.classList.add('active');
        // Support both old and new class names
        const content = document.querySelector(`.settings-tab-content[data-tab="${tabName}"]`)
            || document.querySelector(`.tab-content[data-tab="${tabName}"]`);
        content?.classList.add('active');
        
        // Refresh memory data when Memory tab is opened
        if (tabName === 'memory') {
            loadMemoryTabData();
        }
    });
});

// Set first tab as active on load
if (settingsTabs.length > 0) {
    settingsTabs[0].classList.add('active');
}
if (tabContents.length > 0) {
    tabContents[0].classList.add('active');
}

// Function to refresh just the memory tab data
async function loadMemoryTabData() {
    try {
        const [topicsRes, interestsRes, conversationsRes, memoriesRes] = await Promise.all([
            fetch(API_BASE + '/api/topics').catch(() => null),
            fetch(API_BASE + '/api/interests').catch(() => null),
            fetch(API_BASE + '/api/conversations').catch(() => null),
            fetch(API_BASE + '/api/memories')
        ]);
        
        const topicsData = topicsRes ? await topicsRes.json() : { topics: [] };
        const interestsData = interestsRes ? await interestsRes.json() : { interests: [] };
        const conversationsData = conversationsRes ? await conversationsRes.json() : { conversations: [] };
        const memories = await memoriesRes.json();
        
        renderTrackedTopics(topicsData.topics || []);
        renderDetectedInterests(interestsData.interests || []);
        renderRecentConversations(conversationsData.conversations || []);
        renderMemories(memories);
        
        const memoriesCountEl = document.querySelector('#memoriesCount');
        if (memoriesCountEl) memoriesCountEl.innerText = memories.length || 0;
    } catch (e) {
        // refresh memory tab error silenced
    }
}

// ===== SYSTEM PROMPT =====
const systemPromptInput = document.getElementById('systemPromptInput');
const customInstructionsInput = document.getElementById('customInstructionsInput');
const saveSystemPromptBtn = document.getElementById('saveSystemPromptBtn');
const resetSystemPromptBtn = document.getElementById('resetSystemPromptBtn');

const DEFAULT_SYSTEM_PROMPT = `You are Owlynn, a helpful AI assistant built on LangGraph. You have access to tools for:
- Executing code in a sandboxed environment
- Reading and writing files in the workspace
- Searching the web
- Managing long-term memory
- Processing various file formats (JSON, YAML, PDF, etc.)

Be clear, concise, and helpful. When using tools, explain what you're doing. Break down complex problems into steps.`;

resetSystemPromptBtn?.addEventListener('click', () => {
    if (confirm('Reset to default system prompt?')) {
        systemPromptInput.value = DEFAULT_SYSTEM_PROMPT;
    }
});

saveSystemPromptBtn?.addEventListener('click', async () => {
    const data = {
        system_prompt: systemPromptInput.value,
        custom_instructions: customInstructionsInput.value,
        name: document.querySelector('#personaName')?.value || '',
        tone: document.querySelector('#personaTone')?.value || ''
    };
    try {
        const res = await fetch(API_BASE + '/api/system-settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        alert('System settings saved!');
    } catch (e) {
        // save system settings error silenced
        alert('Failed to save settings');
    }
});

// ===== MEMORY TOGGLES =====
const shortTermMemoryToggle = document.getElementById('shortTermMemoryToggle');
const longTermMemoryToggle = document.getElementById('longTermMemoryToggle');

shortTermMemoryToggle?.addEventListener('change', async (e) => {
    try {
        await fetch(API_BASE + '/api/memory-settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ short_term_enabled: e.target.checked })
        });
    } catch (err) {
        // short-term memory setting error silenced
    }
});

longTermMemoryToggle?.addEventListener('change', async (e) => {
    try {
        await fetch(API_BASE + '/api/memory-settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ long_term_enabled: e.target.checked })
        });
    } catch (err) {
        // long-term memory setting error silenced
    }
});

// ===== ADVANCED SETTINGS =====
const temperatureSlider = document.getElementById('temperatureSlider');
const temperatureValue = document.getElementById('temperatureValue');
const topPSlider = document.getElementById('topPSlider');
const topPValue = document.getElementById('topPValue');
const maxTokensSlider = document.getElementById('maxTokensSlider');
const maxTokensValue = document.getElementById('maxTokensValue');
const topKSlider = document.getElementById('topKSlider');
const topKValue = document.getElementById('topKValue');
const streamingToggle = document.getElementById('streamingToggle');
const thinkingToggle = document.getElementById('thinkingToggle');
const toolVisibilityToggle = document.getElementById('toolVisibilityToggle');
const saveAdvancedBtn = document.getElementById('saveAdvancedBtn');

// Update slider display values
temperatureSlider?.addEventListener('input', (e) => {
    temperatureValue.textContent = parseFloat(e.target.value).toFixed(1);
});

topPSlider?.addEventListener('input', (e) => {
    topPValue.textContent = parseFloat(e.target.value).toFixed(2);
});

maxTokensSlider?.addEventListener('input', (e) => {
    maxTokensValue.textContent = parseInt(e.target.value);
});

topKSlider?.addEventListener('input', (e) => {
    topKValue.textContent = parseInt(e.target.value);
});

document.getElementById('routerThresholdSlider')?.addEventListener('input', (e) => {
    document.getElementById('thresholdValue').textContent = e.target.value;
});

saveAdvancedBtn?.addEventListener('click', async () => {
    const customTermsRaw = document.getElementById('customSensitiveTerms')?.value || '';
    const customTerms = customTermsRaw.split(',').map(t => t.trim()).filter(Boolean);
    const data = {
        temperature: parseFloat(temperatureSlider.value),
        top_p: parseFloat(topPSlider.value),
        max_tokens: parseInt(maxTokensSlider.value),
        top_k: parseInt(topKSlider.value),
        streaming_enabled: streamingToggle.checked,
        show_thinking: thinkingToggle.checked,
        show_tool_execution: toolVisibilityToggle.checked,
        cloud_escalation_enabled: document.getElementById('cloudEscalationToggle')?.checked ?? true,
        cloud_anonymization_enabled: document.getElementById('cloudAnonymizationToggle')?.checked ?? true,
        router_hitl_enabled: document.getElementById('routerHitlToggle')?.checked ?? true,
        router_clarification_threshold: parseFloat(document.getElementById('routerThresholdSlider')?.value || 0.6),
        custom_sensitive_terms: customTerms,
        redis_url: document.getElementById('redisUrlInput')?.value || 'redis://localhost:6379',
        lm_studio_fold_system: document.getElementById('lmStudioFoldToggle')?.checked ?? true,
    };
    try {
        await fetch(API_BASE + '/api/advanced-settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        alert('Advanced settings saved!');
    } catch (e) {
        // save advanced settings error silenced
        alert('Failed to save settings');
    }
});

// Legacy saveProfileBtn/savePersonaBtn — these elements don't exist in Aurora HTML.
// Settings save is handled by renderSettingsUI() when implemented.

// Legacy chatForm/messageInput listeners — handled by BottomInputBar.init()
// Keep handleSend wired for backward compat via BottomInputBar.submit()

// newChatBtn — use document.getElementById since global was removed
document.getElementById('newTaskBtn')?.addEventListener('click', async () => {
    // Reset reasoning state
    isReasoning = false;
    resetTransientExecutionUI();
    finalizeActiveMessage();

    const keepCurrentDraft =
        !hasSentMessageInCurrentSession &&
        isUntitledName(currentChatName) &&
        currentSessionId && StateManager.socket;

    if (!keepCurrentDraft) {
        currentSessionId = generateUUID();
        currentChatName = 'Untitled';
        hasSentMessageInCurrentSession = false;
        chatRegisteredInBackend = false;
        titleGenerationInFlight = false;
        setChatProjectContext(getEffectiveProjectId());
        setWorkspaceProject(getEffectiveProjectId(), true);
    }

    const _messagesArea = document.getElementById('messagesArea');
    if (_messagesArea) _messagesArea.innerHTML = '';
    resetTransientExecutionUI();
    pendingFiles = [];
    renderPreviews();
    
    // Start as untitled/floating chat. It can be auto-renamed from the first user message.
    const chatName = 'Untitled';
    
    // Save mapping to localStorage (draft sessions too, so switching projects can restore them)
    const currentChatProjectId = getChatProjectId();
    if (currentChatProjectId) {
        localStorage.setItem(`project_session_${currentChatProjectId}`, currentSessionId);
    }

    if (!keepCurrentDraft) {
        if (StateManager.socket) {
            StateManager.socket.onclose = null; // Prevent auto-reconnect
            StateManager.socket.close();
        }
        StateManager.connectWebSocket(currentSessionId);
    } else {
        StateManager.connectWebSocket(currentSessionId);
    }
    navigateView('home');
    setWorkspaceVisibility();
});

// Mode Toggle Listeners — legacy modeFastBtn/modeReasoningBtn removed (don't exist in Aurora HTML)

// Legacy attachBtn listener removed — handled by BottomInputBar.init()
// Keep fileInput change listener for legacy processFiles path
{
    const _fileInput = document.getElementById('fileInput');
    if (_fileInput) _fileInput.addEventListener('change', (e) => processFiles(e.target.files));
}

// ─── Drag and Drop ──────────────────────────────────────────────────────────

// Prevent browser default file-open behavior for drag-and-drop globally.
// Without this, dropping a file anywhere opens it in the browser tab.
document.addEventListener('dragover', (e) => { e.preventDefault(); });
document.addEventListener('drop', (e) => { e.preventDefault(); });

// ─── Drag and Drop (Chat Attachments) ───────────────────────────────────────
// Only activate the global drag overlay when the chat or welcome view is active
const composerDock = document.querySelector('.composer-dock');

function isChatOrWelcomeActive() {
    return currentView === 'chat' || currentView === 'welcome';
}

{
    const _chatContainer = document.getElementById('chatContainer');
    const _dragOverlay = document.getElementById('dragOverlay');

    _chatContainer?.addEventListener('dragenter', (e) => {
        if (!isChatOrWelcomeActive()) return;
        e.preventDefault();
        const types = e.dataTransfer.types;
        if (types.includes('Files') || types.includes('application/json')) {
            if (_dragOverlay) { _dragOverlay.classList.remove('hidden'); _dragOverlay.classList.add('flex'); }
        }
    });

    _chatContainer?.addEventListener('dragover', (e) => {
        e.preventDefault();
    });

    _chatContainer?.addEventListener('dragleave', (e) => {
        if (!e.relatedTarget || !_chatContainer.contains(e.relatedTarget)) {
            if (_dragOverlay) { _dragOverlay.classList.add('hidden'); _dragOverlay.classList.remove('flex'); }
        }
    });

    _chatContainer?.addEventListener('drop', handleAttachmentDrop);
    _dragOverlay?.addEventListener('drop', handleAttachmentDrop);
}

function handleAttachmentDrop(e) {
    e.preventDefault();
    const _dragOverlay = document.getElementById('dragOverlay');
    if (_dragOverlay) { _dragOverlay.classList.add('hidden'); _dragOverlay.classList.remove('flex'); }
    
    // Check for Workspace Drag Reference
    const workspaceData = e.dataTransfer.getData('application/json');
    if (workspaceData) {
        try {
            const file = JSON.parse(workspaceData);
            if (file.source === 'workspace') {
                processWorkspaceFileToChat(file);
                return;
            }
        } catch (err) {
            // workspace drop parse error silenced
        }
    }
    
    processFiles(e.dataTransfer.files);
}

composerDock?.addEventListener('dragover', (e) => { e.preventDefault(); e.dataTransfer.dropEffect = 'copy'; });
composerDock?.addEventListener('drop', handleAttachmentDrop);

// Helper for adding Workspace file references to Chat Attachments
function processWorkspaceFileToChat(file) {
    const fileItem = {
        name: file.name,
        type: 'workspace_ref', // Mark as internal reference
        path: file.path, 
        size: 0, 
        base64: "" // Safe loaded bypass
    };
    pendingFiles.push(fileItem);
    renderPreviews();
}
// Legacy connectWebSocket() removed — use StateManager.connectWebSocket(threadId) instead

// Handle tool execution events
function handleToolExecution(data) {
    const { tool_name, status, input, output, error, duration, tool_call_id } = data;
    const toolKey = tool_call_id || `tool:${tool_name || 'unknown'}`;

    if (status === 'running') {
        activeToolName = tool_name || null;
        showThinkingIndicator();
        updateThinkingIndicatorText();
    } else if (activeToolName && tool_name && activeToolName === tool_name) {
        activeToolName = null;
        updateThinkingIndicatorText();
    }
    
    const _messagesArea = document.getElementById('messagesArea');
    let wrapper = _messagesArea ? _messagesArea.lastElementChild : null;
    if (!wrapper || !['agent', 'agent-thinking'].includes(wrapper.dataset.sender)) {
        wrapper = document.createElement('div');
        wrapper.className = 'flex gap-4 group-msg mb-6';
        wrapper.dataset.sender = 'agent';
        
        const avatar = document.createElement('div');
        avatar.className = 'w-8 h-8 rounded shrink-0 bg-anthropic flex items-center justify-center text-white mt-1';
        avatar.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 8V4H8"/><rect x="4" y="8" width="16" height="12" rx="2"/><path d="M2 14h2"/><path d="M20 14h2"/><path d="M15 13v2"/><path d="M9 13v2"/></svg>';
        wrapper.appendChild(avatar);
        
        const contentDiv = document.createElement('div');
        contentDiv.className = 'flex-1 message-content text-base text-textdark';
        wrapper.appendChild(contentDiv);
        if (_messagesArea) _messagesArea.appendChild(wrapper);
    }
    wrapper.dataset.sender = 'agent';

    if (thinkingIndicatorEl && thinkingIndicatorEl === wrapper) {
        clearThinkingIndicator();
        wrapper = null;
    }

    if (!wrapper) {
        wrapper = document.createElement('div');
        wrapper.className = 'flex gap-4 group-msg mb-6';
        wrapper.dataset.sender = 'agent';

        const avatar = document.createElement('div');
        avatar.className = 'w-8 h-8 rounded shrink-0 bg-anthropic flex items-center justify-center text-white mt-1';
        avatar.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 8V4H8"/><rect x="4" y="8" width="16" height="12" rx="2"/><path d="M2 14h2"/><path d="M20 14h2"/><path d="M15 13v2"/><path d="M9 13v2"/></svg>';
        wrapper.appendChild(avatar);

        const contentDiv = document.createElement('div');
        contentDiv.className = 'flex-1 message-content text-base text-textdark';
        wrapper.appendChild(contentDiv);
        if (_messagesArea) _messagesArea.appendChild(wrapper);
    }

    const contentDiv = wrapper.querySelector('.message-content');
    const toolCard = renderToolExecution(tool_name, status, input, output, error);
    
    if (duration) {
        const durationEl = document.createElement('div');
        durationEl.className = 'text-xs text-gray-400 mt-2';
        durationEl.textContent = `⏱ ${duration.toFixed(2)}s`;
        toolCard.appendChild(durationEl);
    }

    if (liveToolCards.has(toolKey)) {
        const existingCard = liveToolCards.get(toolKey);
        existingCard.replaceWith(toolCard);
    } else {
        insertAgentToolCard(contentDiv, toolCard);
    }
    if (status === 'running') {
        liveToolCards.set(toolKey, toolCard);
    } else {
        liveToolCards.delete(toolKey);
    }
    moveActiveAnswerToEnd();
    scrollToBottom();
}

function _safeToolArgsPreview(args) {
    try {
        if (typeof args === 'string') return args.slice(0, 200);
        return JSON.stringify(args).slice(0, 200);
    } catch (_) {
        return '[unavailable]';
    }
}

async function showSecurityApprovalConfirm(interruptPayload) {
    const calls = Array.isArray(interruptPayload?.sensitive_tool_calls) ? interruptPayload.sensitive_tool_calls : [];
    const toolNames = calls.map((c) => String(c?.name || 'unknown_tool'));
    const summary = toolNames.length > 0
        ? `Sensitive action requested for: ${toolNames.join(', ')}`
        : 'Sensitive action requested.';

    const details = calls.length > 0
        ? `\n\nDetails:\n${calls.map((c) => `- ${c.name}: ${_safeToolArgsPreview(c.args)}`).join('\n')}`
        : '';

    return new Promise((resolve) => {
        const modal = document.getElementById('customConfirmModal');
        const titleEl = document.getElementById('confirmModalTitle');
        const messageEl = document.getElementById('confirmModalMessage');
        const confirmBtn = document.getElementById('confirmConfirmBtn');
        const cancelBtn = document.getElementById('cancelConfirmBtn');

        if (!modal || !titleEl || !messageEl || !confirmBtn || !cancelBtn) {
            resolve(confirm(`${summary}\n\nApprove to continue?`));
            return;
        }

        titleEl.textContent = 'Approve Sensitive Tool Action';
        messageEl.textContent = `${summary}${details}\n\nApprove to continue, or cancel to deny.`;
        confirmBtn.className = "px-4 py-2 rounded-xl text-sm bg-anthropic text-white hover:bg-opacity-90 transition-opacity font-medium";
        confirmBtn.textContent = "Approve";
        cancelBtn.textContent = "Deny";

        modal.classList.remove('hidden');
        modal.classList.add('flex');

        const cleanup = (result) => {
            modal.classList.add('hidden');
            modal.classList.remove('flex');
            confirmBtn.onclick = null;
            cancelBtn.onclick = null;
            cancelBtn.textContent = "Cancel";
            resolve(result);
        };

        confirmBtn.onclick = () => cleanup(true);
        cancelBtn.onclick = () => cleanup(false);
    });
}

async function handleSecurityInterrupt(interrupts) {
    const firstRaw = Array.isArray(interrupts) && interrupts.length > 0 ? interrupts[0] : null;
    if (firstRaw == null) return;
    // Normalize scalar interrupts into an object so UI doesn't silently drop payloads.
    const first = (typeof firstRaw === 'object') ? firstRaw : { message: String(firstRaw) };

    // Handle ask_user interrupts (agent asking a clarifying question)
    if (first.type === 'ask_user' || first.question) {
        handleAskUserInterrupt(first);
        return;
    }

    activeToolName = null;
    showThinkingIndicator();
    const textEl = thinkingIndicatorEl?.querySelector('#thinkingText');
    if (textEl) textEl.textContent = 'Waiting for approval to run sensitive action...';

    const approved = await showSecurityApprovalConfirm(first);
    if (StateManager.socket && StateManager.socket.readyState === WebSocket.OPEN) {
        StateManager.socket.send(JSON.stringify({ type: 'security_approval', approved: Boolean(approved) }));
    }
}

function handleAskUserInterrupt(payload) {
    resetTransientExecutionUI();
    const question = payload.question || 'The agent needs more information to continue.';
    const choices = Array.isArray(payload.choices) ? payload.choices.slice(0, 3) : [];

    const wrapper = document.createElement('div');
    wrapper.className = 'flex gap-4 group-msg mb-6';
    wrapper.dataset.sender = 'ai';

    const avatar = document.createElement('div');
    avatar.className = 'w-8 h-8 rounded shrink-0 bg-anthropic flex items-center justify-center text-white mt-1';
    avatar.textContent = '🦉';
    wrapper.appendChild(avatar);

    const contentDiv = document.createElement('div');
    contentDiv.className = 'flex-1';

    const card = document.createElement('div');
    card.className = 'ask-user-card';

    // Header
    const headerDiv = document.createElement('div');
    headerDiv.className = 'flex items-center gap-2 mb-3 text-sm font-medium';
    headerDiv.style.color = 'var(--owl-accent)';
    headerDiv.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg> Owlynn needs your input`;
    card.appendChild(headerDiv);

    const questionP = document.createElement('p');
    questionP.className = 'text-sm mb-3';
    questionP.style.color = 'var(--owl-text)';
    questionP.textContent = question;
    card.appendChild(questionP);

    // Choice buttons (1-3) — using addEventListener instead of inline onclick
    if (choices.length > 0) {
        const choicesDiv = document.createElement('div');
        choicesDiv.className = 'ask-user-choices';
        choicesDiv.style.cssText = 'display:flex;flex-wrap:wrap;gap:0.5rem;margin-bottom:0.75rem;';
        choices.forEach((c) => {
            const btn = document.createElement('button');
            btn.className = 'ask-choice-btn';
            btn.style.cssText = 'padding:0.4rem 0.8rem;border-radius:0.5rem;font-size:0.85rem;font-weight:500;background:var(--accent-soft);border:1px solid rgba(199,154,59,0.4);color:#f6e2b4;cursor:pointer;transition:all 0.15s;';
            // Choices may be plain strings (from ask_user tool) or objects with
            // label/route/toolbox (from router HITL). Display the label and send
            // the full object back so the backend can extract route/toolbox.
            const label = (typeof c === 'object' && c !== null) ? (c.label || JSON.stringify(c)) : String(c);
            btn.textContent = label;
            btn.addEventListener('click', () => submitAskUserChoice(c));
            choicesDiv.appendChild(btn);
        });
        card.appendChild(choicesDiv);
    }

    // Free text input (always present)
    const inputRow = document.createElement('div');
    inputRow.className = 'flex gap-2';
    const textInput = document.createElement('input');
    textInput.type = 'text';
    textInput.className = 'flex-1 px-3 py-2 rounded-lg text-sm border outline-none focus:ring-1 focus:ring-[var(--owl-accent)]';
    textInput.placeholder = choices.length > 0 ? 'Or type your own answer...' : 'Type your answer...';
    textInput.id = 'askUserInput';
    inputRow.appendChild(textInput);

    const sendBtn = document.createElement('button');
    sendBtn.className = 'px-4 py-2 rounded-lg text-sm font-medium transition-colors';
    sendBtn.style.cssText = 'background:var(--accent-soft);border:1px solid rgba(199,154,59,0.4);color:#f6e2b4;';
    sendBtn.textContent = 'Send';
    sendBtn.addEventListener('click', () => submitAskUserResponse());
    inputRow.appendChild(sendBtn);
    card.appendChild(inputRow);

    contentDiv.appendChild(card);
    wrapper.appendChild(contentDiv);
    const _messagesArea2 = document.getElementById('messagesArea');
    if (_messagesArea2) _messagesArea2.appendChild(wrapper);
    scrollToBottom(true);

    setTimeout(() => {
        const input = document.getElementById('askUserInput');
        if (input) {
            input.focus();
            input.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') submitAskUserResponse();
            });
        }
    }, 100);
}

function submitAskUserChoice(choice) {
    _sendAskUserAnswer(choice);
}

function submitAskUserResponse() {
    const input = document.getElementById('askUserInput');
    if (!input) return;
    const answer = input.value.trim();
    if (!answer) return;
    _sendAskUserAnswer(answer);
}

function _sendAskUserAnswer(answer) {
    // Disable all inputs and buttons in the ask-user card
    const card = document.querySelector('.ask-user-card');
    if (card) {
        card.querySelectorAll('input, button').forEach(el => { el.disabled = true; });
        // Show what was selected
        const feedback = document.createElement('div');
        feedback.className = 'text-xs mt-2';
        feedback.style.color = 'var(--owl-accent)';
        const displayText = (typeof answer === 'object' && answer !== null) ? (answer.label || JSON.stringify(answer)) : String(answer);
        feedback.textContent = `✓ ${displayText}`;
        card.appendChild(feedback);
    }
    if (StateManager.socket && StateManager.socket.readyState === WebSocket.OPEN) {
        // Router HITL choices are objects with route/toolbox — send the full object.
        // ask_user tool choices are plain strings — wrap in {answer: ...}.
        const payload = (typeof answer === 'object' && answer !== null)
            ? { type: 'ask_user_response', answer: answer }
            : { type: 'ask_user_response', answer: String(answer) };
        StateManager.socket.send(JSON.stringify(payload));
    }
}

// Render error with better styling
function renderErrorUI(message, title = 'Error', details = null) {
    resetTransientExecutionUI();
    const wrapper = document.createElement('div');
    wrapper.className = 'flex gap-4 group-msg mb-6';
    wrapper.dataset.sender = 'error';
    
    const avatar = document.createElement('div');
    avatar.className = 'w-8 h-8 rounded shrink-0 bg-red-500 flex items-center justify-center text-white mt-1';
    avatar.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>';
    wrapper.appendChild(avatar);
    
    const contentDiv = document.createElement('div');
    contentDiv.className = 'flex-1';
    contentDiv.appendChild(renderErrorMessage(title, message, details));
    wrapper.appendChild(contentDiv);
    
    const _messagesArea = document.getElementById('messagesArea');
    if (_messagesArea) _messagesArea.appendChild(wrapper);
    scrollToBottom();
}

// UI Updaters
function quickAction(text) {
    const _messageInput = document.getElementById('messageInput');
    if (!_messageInput) return;
    _messageInput.value = text;
    // Trigger input event to resize textarea
    _messageInput.dispatchEvent(new Event('input'));
    // Small delay to ensure resize finished
    setTimeout(() => {
        BottomInputBar.submit();
    }, 10);
}

// updateConnectionStatus removed — Aurora StateManager subscriber handles status dot updates
// updateAgentStatus removed — callers now inline the needed logic (isReasoning flag, resetTransientExecutionUI, finalizeActiveMessage)

async function ensureChatRegistered() {
    if (chatRegisteredInBackend) return;
    if (!currentSessionId) return;

    const projectId = getChatProjectId();
    if (!projectId) return;

    const nameForRegistration = isUntitledName(currentChatName) ? 'Untitled' : (currentChatName || 'Untitled');

    try {
        await fetch(`${API_BASE}/api/projects/${projectId}/chats`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ id: currentSessionId, name: nameForRegistration })
        });

        chatRegisteredInBackend = true;
        localStorage.setItem(`project_session_${projectId}`, currentSessionId);

        // Refresh cached project so recents updates across views
        const res = await fetch(`${API_BASE}/api/projects/${projectId}`);
        const project = await res.json();
        assignCachedProjects(cachedProjects.map((p) => (p.id === projectId ? project : p)));

        // Only re-render the sidebar recents if this chat belongs to the project currently being shown.
        const sidebarProjectId = getEffectiveProjectId();
        if (sidebarProjectId === projectId) {
            const projectChatsSection = document.getElementById('projectChatsSection');
            if (projectChatsSection) projectChatsSection.classList.remove('hidden');
            renderProjectChats(project.chats || []);
            renderProjectInspector(project);
        }
        renderWelcomeRecents();
    } catch (e) {
        // register chat error silenced
    }
}

// ─── File Handling ──────────────────────────────────────────────────────────
function processFiles(fileList) {
    Array.from(fileList).forEach(file => {
        const reader = new FileReader();
        reader.onload = (e) => {
            const dataUrl = e.target.result;
            // Strip the data URL prefix to get raw base64
            const base64 = dataUrl.split(',')[1];
            const fileObj = { name: file.name, type: file.type || 'application/octet-stream', data: base64 };
            
            // Image preview
            if (file.type.startsWith('image/')) {
                fileObj.preview = dataUrl;
            }
            
            pendingFiles.push(fileObj);
            renderPreviews();
        };
        reader.readAsDataURL(file);
    });
}

function renderPreviews() {
    const renderInto = (containerEl) => {
        if (!containerEl) return;
        containerEl.innerHTML = '';
        if (pendingFiles.length === 0) {
            containerEl.classList.add('hidden');
            return;
        }
        containerEl.classList.remove('hidden');
        containerEl.className = 'flex flex-wrap gap-2 mb-2';
        
        pendingFiles.forEach((f, idx) => {
            const chip = document.createElement('div');
            chip.className = 'relative flex items-center gap-2 bg-cloud border border-bordercolor rounded-lg px-3 py-1.5 text-sm';
            
            if (f.preview) {
                const img = document.createElement('img');
                img.src = f.preview;
                img.className = 'w-8 h-8 object-cover rounded';
                chip.appendChild(img);
            } else if (f.type === 'workspace_ref') {
                // Workspace File Icon
                const icon = document.createElement('div');
                icon.className = 'w-8 h-8 rounded bg-orange-50 flex items-center justify-center text-orange-600';
                icon.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 22h16a2 2 0 0 0 2-2V7.5L14.5 2H6a2 2 0 0 0-2 2v4"/><polyline points="14 2 14 8 20 8"/></svg>';
                chip.appendChild(icon);
                chip.classList.add('border-orange-200', 'bg-orange-50/50');
            } else {
                // File type icon
                const icon = document.createElement('div');
                icon.className = 'w-8 h-8 rounded bg-gray-200 flex items-center justify-center text-gray-600';
                icon.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>';
                chip.appendChild(icon);
            }
            
            const name = document.createElement('span');
            name.className = 'max-w-[120px] truncate text-gray-700';
            name.textContent = f.name;
            chip.appendChild(name);
            
            // Remove button
            const removeBtn = document.createElement('button');
            removeBtn.type = 'button';
            removeBtn.className = 'ml-1 text-gray-400 hover:text-red-500 transition-colors';
            removeBtn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>';
            removeBtn.addEventListener('click', () => {
                pendingFiles.splice(idx, 1);
                renderPreviews();
            });
            chip.appendChild(removeBtn);
            
            containerEl.appendChild(chip);
        });
    };
    
    renderInto(document.getElementById('attachmentPreviews'));
    renderInto(document.querySelector('#welcomeAttachmentPreviews'));
}

/**
 * Flatten API/stream content (string | blocks | nested objects) to plain text for markdown.
 * Avoids "[object Object]" when providers nest { text: { ... } } or table-like blocks.
 */
function flattenAiContentForUi(content) {
    if (content == null || content === undefined) return '';
    if (typeof content === 'string') return content;
    if (typeof content === 'number' || typeof content === 'boolean') return String(content);
    if (Array.isArray(content)) {
        return content.map(flattenAiContentForUi).join('');
    }
    if (typeof content === 'object') {
        if (content.text != null) return flattenAiContentForUi(content.text);
        if (content.content != null) return flattenAiContentForUi(content.content);
        if (content.delta != null) return flattenAiContentForUi(content.delta);
        if (content.value != null) return flattenAiContentForUi(content.value);
        const type = content.type;
        if (type === 'text' && content.text != null) return flattenAiContentForUi(content.text);
        try {
            return JSON.stringify(content);
        } catch (_) {
            return '';
        }
    }
    return '';
}

/** LLM stream chunks may be a string or LangChain-style content blocks. */
function normalizeStreamChunk(chunk) {
    return flattenAiContentForUi(chunk);
}

function handleChunk(chunkText, metadata = {}) {
    chunkText = normalizeStreamChunk(chunkText);
    clearThinkingIndicator();
    if (!activeAiMessage) {
        const _messagesArea = document.getElementById('messagesArea');
        const lastWrapper = _messagesArea ? _messagesArea.lastElementChild : null;
        let wrapper, contentDiv;
        
        if (lastWrapper && lastWrapper.dataset.sender === 'agent') {
            wrapper = lastWrapper;
            contentDiv = wrapper.querySelector('.message-content');
        } else {
            wrapper = document.createElement('div');
            wrapper.className = 'flex gap-4 group-msg mb-6';
            wrapper.dataset.sender = 'agent';
            
            const avatar = document.createElement('div');
            avatar.className = 'w-8 h-8 rounded shrink-0 bg-anthropic flex items-center justify-center text-white mt-1';
            avatar.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 8V4H8"/><rect x="4" y="8" width="16" height="12" rx="2"/><path d="M2 14h2"/><path d="M20 14h2"/><path d="M15 13v2"/><path d="M9 13v2"/></svg>';
            wrapper.appendChild(avatar);
            
            contentDiv = document.createElement('div');
            contentDiv.className = 'flex-1 message-content text-base text-textdark leading-relaxed space-y-4';
            wrapper.appendChild(contentDiv);
            if (_messagesArea) _messagesArea.appendChild(wrapper);
        }
        
        const mainContainer = document.createElement('div');
        mainContainer.className = 'agent-final-answer';
        contentDiv.appendChild(mainContainer);
        
        activeAiMessage = {
            wrapper: wrapper,
            contentDiv: contentDiv,
            mainContainer: mainContainer,
            buffer: "",
            insideThought: false,
            thoughtContainer: null,
            mainText: "",
            thoughtText: ""
        };
    }
    moveActiveAnswerToEnd();

    activeAiMessage.buffer += chunkText;
    let buf = activeAiMessage.buffer;

    // Handle <think>...</think> tags (Qwen3.5 reasoning format) — suppress from display
    if (!activeAiMessage.insideThought && buf.includes('<think>')) {
        const idx = buf.indexOf('<think>');
        const textBefore = buf.substring(0, idx);
        if (textBefore) {
            if (!activeAiMessage.mainContainer) {
                activeAiMessage.mainContainer = document.createElement('div');
                activeAiMessage.contentDiv.appendChild(activeAiMessage.mainContainer);
            }
            activeAiMessage.mainText += textBefore;
            activeAiMessage.mainContainer.innerHTML = DOMPurify.sanitize(marked.parse(activeAiMessage.mainText));
        }
        activeAiMessage.insideThought = true;
        activeAiMessage._thinkTagMode = true; // track that we're in <think> not <thought>
        activeAiMessage.thoughtText = '';
        return;
    }
    if (activeAiMessage._thinkTagMode && activeAiMessage.insideThought) {
        if (buf.includes('</think>')) {
            const idx = buf.indexOf('</think>');
            activeAiMessage.insideThought = false;
            activeAiMessage._thinkTagMode = false;
            activeAiMessage.buffer = buf.substring(idx + 8); // len('</think>') = 8
            return handleChunk('');
        }
        // Still inside <think> — swallow the content silently
        activeAiMessage.buffer = '';
        return;
    }

    if (!activeAiMessage.insideThought && buf.includes('<thought>')) {
        const idx = buf.indexOf('<thought>');
        const textBefore = buf.substring(0, idx);
        if (textBefore) {
            if (!activeAiMessage.mainContainer) {
                activeAiMessage.mainContainer = document.createElement('div');
                activeAiMessage.contentDiv.appendChild(activeAiMessage.mainContainer);
            }
            activeAiMessage.mainText += textBefore;
            activeAiMessage.mainContainer.innerHTML = DOMPurify.sanitize(marked.parse(activeAiMessage.mainText));
        }
        activeAiMessage.insideThought = true;
        activeAiMessage.buffer = buf.substring(idx + 9);
        
        const details = document.createElement('details');
        details.className = 'mb-4 bg-gray-50 border border-bordercolor rounded-lg overflow-hidden';
        details.open = true;
        
        const summary = document.createElement('summary');
        summary.className = 'px-4 py-2 text-sm font-medium text-gray-700 cursor-pointer hover:bg-gray-100 flex items-center gap-2';
        summary.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="text-anthropic transition-transform duration-200"><polyline points="6 9 12 15 18 9"/></svg> Thinking Process`;
        
        const thoughtContent = document.createElement('div');
        thoughtContent.className = 'p-4 text-sm text-gray-600 border-t border-bordercolor';
        
        details.appendChild(summary);
        details.appendChild(thoughtContent);
        
        // Append details element
        if (activeAiMessage.mainContainer) {
             activeAiMessage.contentDiv.insertBefore(details, activeAiMessage.mainContainer);
        } else {
             activeAiMessage.contentDiv.appendChild(details);
        }
        
        activeAiMessage.thoughtContainer = thoughtContent;
        return handleChunk(""); 
    }
    
    if (activeAiMessage.insideThought && buf.includes('</thought>')) {
        const idx = buf.indexOf('</thought>');
        const textBefore = buf.substring(0, idx);
        if (textBefore) {
            activeAiMessage.thoughtText += textBefore;
            activeAiMessage.thoughtContainer.innerHTML = DOMPurify.sanitize(marked.parse(activeAiMessage.thoughtText));
        }
        activeAiMessage.insideThought = false;
        activeAiMessage.buffer = buf.substring(idx + 10);
        
        // Close details
        if (activeAiMessage.thoughtContainer && activeAiMessage.thoughtContainer.parentElement) {
            activeAiMessage.thoughtContainer.parentElement.open = false;
        }
        
        return handleChunk("");
    }

    // --- GLM Adaptive Fallback (Robust token-split search) ---
    const fullTextSearch = activeAiMessage.mainText + buf;
    if (fullTextSearch.includes('<|begin_of_box|>')) {
        const idx = fullTextSearch.indexOf('<|begin_of_box|>');
        const textBefore = fullTextSearch.substring(0, idx);
        
        if (activeAiMessage.insideThought) {
            // Unlikely to hit if insideThought, but safe fallback
            activeAiMessage.thoughtText += textBefore;
            activeAiMessage.insideThought = false;
        } else {
            // Everything before <|begin_of_box|> is Thought!
            activeAiMessage.thoughtText = (activeAiMessage.thoughtText || "") + textBefore;
        }
        
        // Clear mainText so answer doesn't append to thought
        activeAiMessage.mainText = "";
        if (activeAiMessage.mainContainer) activeAiMessage.mainContainer.innerHTML = "";
        
        if (!activeAiMessage.thoughtContainer) {
            const details = document.createElement('details');
            details.className = 'mb-4 bg-gray-50 border border-bordercolor rounded-lg overflow-hidden';
            details.open = false; 
            
            const summary = document.createElement('summary');
            summary.className = 'px-4 py-2 text-sm font-medium text-gray-700 cursor-pointer hover:bg-gray-100 flex items-center gap-2';
            summary.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="text-anthropic transition-transform duration-200"><polyline points="6 9 12 15 18 9"/></svg> Thinking Process`;
            
            const thoughtContent = document.createElement('div');
            thoughtContent.className = 'p-4 text-sm text-gray-600 border-t border-bordercolor';
            
            details.appendChild(summary);
            details.appendChild(thoughtContent);
            
            activeAiMessage.contentDiv.insertBefore(details, activeAiMessage.contentDiv.firstChild);
            activeAiMessage.thoughtContainer = thoughtContent;
        }
        activeAiMessage.thoughtContainer.innerHTML = DOMPurify.sanitize(marked.parse(activeAiMessage.thoughtText));
        
        // Update buffer to rest of text after <|begin_of_box|>
        activeAiMessage.buffer = fullTextSearch.substring(idx + 16);
        return handleChunk(""); 
    }

    if (fullTextSearch.includes('<|end_of_box|>')) {
        const idx = fullTextSearch.indexOf('<|end_of_box|>');
        const textBefore = fullTextSearch.substring(0, idx);
        if (textBefore) {
            if (!activeAiMessage.mainContainer) {
                activeAiMessage.mainContainer = document.createElement('div');
                activeAiMessage.contentDiv.appendChild(activeAiMessage.mainContainer);
            }
            // textBefore contains correct relative text
            activeAiMessage.mainText = textBefore; 
            activeAiMessage.mainContainer.innerHTML = DOMPurify.sanitize(marked.parse(activeAiMessage.mainText));
        }
        activeAiMessage.buffer = fullTextSearch.substring(idx + 14);
        return handleChunk("");
    }

    if (activeAiMessage.insideThought) {
        if (activeAiMessage.buffer) {
            activeAiMessage.thoughtText += activeAiMessage.buffer;
            activeAiMessage.thoughtContainer.innerHTML = DOMPurify.sanitize(marked.parse(activeAiMessage.thoughtText));
            activeAiMessage.buffer = "";
        }
    } else {
        if (activeAiMessage.buffer) {
            if (!activeAiMessage.mainContainer) {
                activeAiMessage.mainContainer = document.createElement('div');
                activeAiMessage.contentDiv.appendChild(activeAiMessage.mainContainer);
            }
            activeAiMessage.mainText += activeAiMessage.buffer;
            activeAiMessage.mainContainer.innerHTML = DOMPurify.sanitize(marked.parse(activeAiMessage.mainText));
            activeAiMessage.buffer = "";
        }
    }

    scrollToBottom();
}

function finalizeActiveMessage() {
    if (activeAiMessage) {
        addMessageActions(activeAiMessage.contentDiv, activeAiMessage.mainText || activeAiMessage.thoughtText, activeAiMessage.wrapper);
        activeAiMessage = null;
        // Scroll to bottom after finalizing — tool call cards may have pushed the answer up
        setTimeout(scrollToBottom, 50);
        // Poll cumulative session token usage
        updateSessionTokenUsage();
    }
}

async function updateSessionTokenUsage() {
    try {
        const res = await fetch(API_BASE + '/api/usage');
        if (!res.ok) return;
        const usage = await res.json();
        const total = (usage.total_tokens || 0);
        const el = document.getElementById('sessionTokenUsage');
        if (!el) return;
        if (total > 0) {
            el.textContent = `☁ ${total} tokens`;
            el.classList.remove('hidden');
        } else {
            el.classList.add('hidden');
        }
    } catch (e) { /* ignore fetch errors */ }
}

function addMessageActions(contentDiv, textContent, wrapper) {
    if (contentDiv.querySelector('.message-actions')) return; 

    const actionsDiv = document.createElement('div');
    actionsDiv.className = 'flex flex-col gap-2 mt-3 pt-2 border-t border-gray-100';
    
    // Show style badge instead of model badge for cleaner UX.
    const styleMap = {
        normal: 'Normal',
        learning: 'Learning',
        concise: 'Concise',
        explanatory: 'Explanatory',
        formal: 'Formal',
    };
    const perMessageModel = (wrapper && wrapper.dataset.modelUsed) || currentModelUsed;
    const badgeClass = getModelBadgeClass(perMessageModel);
    const badgeIcon = getModelBadgeIcon(perMessageModel);
    const infoBadge = document.createElement('div');
    infoBadge.className = `model-info-badge ${badgeClass}`;
    infoBadge.innerHTML = `${badgeIcon} <span>${DOMPurify.sanitize(perMessageModel || 'unknown')}</span> · <span>Style: ${DOMPurify.sanitize(styleMap[responseStyle] || 'Normal')}</span>`;
    actionsDiv.appendChild(infoBadge);

    // Append cloud token indicator if token_usage is present
    if (wrapper && wrapper.dataset.tokenUsage) {
        try {
            const tokenUsage = JSON.parse(wrapper.dataset.tokenUsage);
            const tokenHtml = renderTokenUsage(tokenUsage);
            if (tokenHtml) {
                infoBadge.insertAdjacentHTML('beforeend', ' ' + tokenHtml);
            }
        } catch (e) { /* ignore malformed data */ }
    }
    
    const buttonsDiv = document.createElement('div');
    buttonsDiv.className = 'flex gap-2 message-actions';
    
    const copyBtn = document.createElement('button');
    copyBtn.className = 'text-xs flex items-center gap-1 text-gray-400 hover:text-black transition-colors';
    copyBtn.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg> Copy`;
    copyBtn.addEventListener('click', () => {
         navigator.clipboard.writeText(textContent);
         const original = copyBtn.innerHTML;
         copyBtn.innerHTML = `✅ Copied`;
         setTimeout(() => copyBtn.innerHTML = original, 2000);
    });
    
    const regenBtn = document.createElement('button');
    regenBtn.className = 'text-xs flex items-center gap-1 text-gray-400 hover:text-black transition-colors';
    regenBtn.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67"/></svg> Regenerate`;
    regenBtn.addEventListener('click', () => {
         if (lastHumanMessage) {
              if (wrapper) wrapper.remove();
              StateManager.socket.send(JSON.stringify(buildChatWsPayload(lastHumanMessage, [])));
         }
    });

    buttonsDiv.appendChild(copyBtn);
    buttonsDiv.appendChild(regenBtn);
    actionsDiv.appendChild(buttonsDiv);
    contentDiv.appendChild(actionsDiv);
}
async function handleSend(e) {
    if (e) e.preventDefault();

    if (isReasoning) {
        stopLlm();
        return;
    }
    
    const _messageInput = document.getElementById('messageInput');
    const _fileInput = document.getElementById('fileInput');
    const text = _messageInput ? _messageInput.value.trim() : '';
    if ((!text && pendingFiles.length === 0) || !StateManager.socket || StateManager.socket.readyState !== WebSocket.OPEN) return;

    // Register this thread once so it shows up in recents/history views.
    await ensureChatRegistered();

    if (text) {
        maybeAutoNameCurrentChat(text, pendingFiles.map(f => f.name));
    }
    
    // Optimistic UI
    renderUserMessage(text, pendingFiles);
    lastHumanMessage = text; // Remember for regenerate
    
    // Send to backend with files and current mode
    const wsPayload = (window.OrchestratorPanel && typeof OrchestratorPanel.buildWsPayload === 'function')
        ? OrchestratorPanel.buildWsPayload(text, pendingFiles.map(f => ({ name: f.name, type: f.type, data: f.data, path: f.path })))
        : buildChatWsPayload(text, pendingFiles.map(f => ({ name: f.name, type: f.type, data: f.data, path: f.path })));
    StateManager.socket.send(JSON.stringify(wsPayload));
    hasSentMessageInCurrentSession = true;

    
    // Clear
    if (_messageInput) {
        _messageInput.value = '';
        _messageInput.style.height = '56px';
    }
    pendingFiles = [];
    renderPreviews();
    if (_fileInput) _fileInput.value = '';
}

function stopLlm() {
    if (StateManager.socket && StateManager.socket.readyState === WebSocket.OPEN) {
        StateManager.socket.send(JSON.stringify({ type: 'stop' }));
        activeToolName = null;
        showThinkingIndicator();
        const textEl = thinkingIndicatorEl?.querySelector('#thinkingText');
        if (textEl) textEl.textContent = 'Stopping generation...';
    }
}

function renderUserMessage(text, files = []) {
    const wrapper = document.createElement('div');
    wrapper.className = 'flex justify-end mb-6';
    wrapper.dataset.sender = 'human';
    
    const inner = document.createElement('div');
    inner.className = 'flex flex-col items-end gap-2 max-w-[85%]';
    
    // Show attached file previews
    if (files && files.length > 0) {
        const fileRow = document.createElement('div');
        fileRow.className = 'flex flex-wrap gap-2 justify-end';
        files.forEach(f => {
            const chip = document.createElement('div');
            chip.className = 'flex items-center gap-1.5 bg-userbubble border border-bordercolor px-2 py-1 rounded-lg text-xs text-gray-600';
            if (f.preview) {
                const img = document.createElement('img');
                img.src = f.preview;
                img.className = 'w-6 h-6 object-cover rounded';
                chip.appendChild(img);
            }
            const span = document.createElement('span');
            span.textContent = f.name;
            chip.appendChild(span);
            fileRow.appendChild(chip);
        });
        inner.appendChild(fileRow);
    }
    
    if (text) {
        let cleanedText = text;
        const foundFiles = [];

        if (typeof text === 'string') {
            const fileRegex = /\[File:\s+([^\]]+)\]\s*[\r\n]+```[\s\S]*?```/g;
            let match;
            while ((match = fileRegex.exec(text)) !== null) {
                foundFiles.push(match[1]);
            }
            if (foundFiles.length > 0) {
                cleanedText = text.replace(fileRegex, '').trim();
                
                const fileRow = document.createElement('div');
                fileRow.className = 'flex flex-wrap gap-2 justify-end mb-1';
                foundFiles.forEach(name => {
                    const chip = document.createElement('div');
                    chip.className = 'flex items-center gap-1.5 bg-userbubble border border-bordercolor px-2 py-1 rounded-lg text-xs text-gray-600';
                    chip.innerHTML = `📄 <span>${name}</span>`;
                    fileRow.appendChild(chip);
                });
                inner.appendChild(fileRow);
            }
        }

        if (cleanedText || Array.isArray(text)) {
            const bubble = document.createElement('div');
            bubble.className = 'bg-userbubble text-textdark px-5 py-3.5 rounded-[1.15rem] text-[15px] leading-relaxed border border-bordercolor/60 shadow-[0_8px_20px_rgba(2,8,22,0.24)] relative group';
            
            const textSpan = document.createElement('span');
            if (typeof text === 'string') {
                textSpan.textContent = cleanedText;
            } else if (Array.isArray(text)) {
                // Find the text part in multimodal content
                const textPart = text.find(p => p.type === 'text');
                textSpan.textContent = textPart ? textPart.text : '[Multimodal Content]';
            }

        
        const editBtn = document.createElement('button');
        editBtn.className = 'absolute -left-6 top-1/2 -translate-y-1/2 opacity-0 group-hover:opacity-100 transition-opacity text-gray-400 hover:text-black';
        editBtn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>';
        
        editBtn.addEventListener('click', () => {
            const originalText = textSpan.textContent;
            bubble.innerHTML = '';
            
            const textarea = document.createElement('textarea');
            textarea.className = 'w-full bg-transparent resize-none focus:outline-none text-base border-b border-gray-400 mb-2';
            textarea.value = originalText;
            textarea.rows = 1;
            bubble.appendChild(textarea);
            
            const controls = document.createElement('div');
            controls.className = 'flex gap-2 justify-end';
            
            const cancelBtn = document.createElement('button');
            cancelBtn.className = 'text-xs px-2 py-1 bg-gray-200 rounded hover:bg-gray-300';
            cancelBtn.textContent = 'Cancel';
            
            const saveBtn = document.createElement('button');
            saveBtn.className = 'text-xs px-2 py-1 bg-anthropic text-white rounded hover:opacity-90';
            saveBtn.textContent = 'Save';
            
            controls.appendChild(cancelBtn);
            controls.appendChild(saveBtn);
            bubble.appendChild(controls);
            textarea.focus();
            
            cancelBtn.addEventListener('click', () => {
                bubble.innerHTML = '';
                bubble.appendChild(textSpan);
                bubble.appendChild(editBtn);
            });
            
            saveBtn.addEventListener('click', () => {
                const newText = textarea.value.trim();
                if (newText && newText !== originalText) {
                    textSpan.textContent = newText;
                    lastHumanMessage = newText;
                    
                    // Clear following DOM elements
                    let sibling = wrapper.nextSibling;
                    while (sibling) {
                        const next = sibling.nextSibling;
                        sibling.remove();
                        sibling = next;
                    }
                    
                    // Resubmit
                    const _mi = document.getElementById('messageInput');
                    if (_mi) _mi.value = newText;
                    handleSend(new Event('submit'));
                } else {
                    bubble.innerHTML = '';
                    bubble.appendChild(textSpan);
                    bubble.appendChild(editBtn);
                }
            });
        });

        bubble.appendChild(textSpan);
        bubble.appendChild(editBtn);
        inner.appendChild(bubble);
    }
    }
    
    wrapper.appendChild(inner);
    const _messagesArea = document.getElementById('messagesArea');
    if (_messagesArea) _messagesArea.appendChild(wrapper);
    scrollToBottom(true);
}

function renderMessage(msg, modelUsed, tokenUsage) {
    if (msg.type === 'ai' || msg.type === 'tool') {
        clearThinkingIndicator();
    }
    if (msg.type === 'human') {
        renderUserMessage(msg.content);
        return;
    }

    // Guard up-front: skip messages with no useful content at all
    const flatContent = flattenAiContentForUi(msg.content);
    const hasContent = flatContent && flatContent.trim();
    const hasToolCalls = msg.tool_calls && msg.tool_calls.length > 0;
    if (msg.type === 'ai' && !hasContent && !hasToolCalls) return;
    if (msg.type === 'tool' && !msg.content) return;

    // Final model reply after tools: backend now sends this even when stream events were missed.
    if (msg.type === 'ai' && hasContent && !hasToolCalls && activeAiMessage?.contentDiv) {
        const sanitized = flatContent
            .replace(/```(?:json)?\s*\{[^}]*\}\s*```/gs, '')
            .replace(/```(?:json)?\s*```/g, '')
            .trim();
        if (sanitized) {
            if (!activeAiMessage.mainContainer) {
                const mc = document.createElement('div');
                mc.className = 'agent-final-answer';
                activeAiMessage.contentDiv.appendChild(mc);
                activeAiMessage.mainContainer = mc;
            }
            activeAiMessage.mainText = sanitized;
            activeAiMessage.mainContainer.innerHTML = DOMPurify.sanitize(marked.parse(sanitized));
            if (modelUsed && activeAiMessage.wrapper) activeAiMessage.wrapper.dataset.modelUsed = modelUsed;
            if (tokenUsage && activeAiMessage.wrapper) activeAiMessage.wrapper.dataset.tokenUsage = JSON.stringify(tokenUsage);
            moveActiveAnswerToEnd();
            finalizeActiveMessage();
            scrollToBottom();
            return;
        }
    }

    // --- Message Grouping Logic ---
    // We group AI messages and Tool results into the same visual block if they are consecutive.
    const _messagesArea = document.getElementById('messagesArea');
    const lastWrapper = _messagesArea ? _messagesArea.lastElementChild : null;
    let contentContainer = null;
    let isNewGroup = true;

    if (lastWrapper && lastWrapper.dataset.sender === 'agent' && (msg.type === 'ai' || msg.type === 'tool')) {
        contentContainer = lastWrapper.querySelector('.message-content');
        isNewGroup = false;
    }

    if (isNewGroup) {
        const wrapper = document.createElement('div');
        wrapper.className = 'flex gap-4 group-msg mb-6';
        wrapper.dataset.sender = (msg.type === 'ai' || msg.type === 'tool') ? 'agent' : 'human';

        // Avatar
        const avatar = document.createElement('div');
        avatar.className = 'w-8 h-8 rounded shrink-0 bg-anthropic flex items-center justify-center text-white mt-1';
        avatar.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 8V4H8"/><rect x="4" y="8" width="16" height="12" rx="2"/><path d="M2 14h2"/><path d="M20 14h2"/><path d="M15 13v2"/><path d="M9 13v2"/></svg>';
        wrapper.appendChild(avatar);

        // Content Container
        contentContainer = document.createElement('div');
        contentContainer.className = 'flex-1 message-content text-base text-textdark leading-relaxed space-y-4';
        wrapper.appendChild(contentContainer);
        
        // Store per-message model_used on wrapper if available
        if (modelUsed) wrapper.dataset.modelUsed = modelUsed;
        if (tokenUsage) wrapper.dataset.tokenUsage = JSON.stringify(tokenUsage);
        if (_messagesArea) _messagesArea.appendChild(wrapper);
    } else if (modelUsed && lastWrapper) {
        // Update existing wrapper with per-message model_used
        lastWrapper.dataset.modelUsed = modelUsed;
        if (tokenUsage) lastWrapper.dataset.tokenUsage = JSON.stringify(tokenUsage);
    }

    // --- Content Rendering ---
    if (msg.type === 'ai') {
        // Reorder: tool plan / calls first, brief pre-tool text next, final answer comes last via stream or merge above
        if (hasToolCalls) {
            if (!contentContainer.querySelector('.agent-process-label')) {
                const lab = document.createElement('div');
                lab.className = 'agent-process-label text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2';
                lab.textContent = 'Tools & sources';
                contentContainer.appendChild(lab);
            }
            msg.tool_calls.forEach(tc => {
                const toolDiv = createToolCallUI(tc);
                contentContainer.appendChild(toolDiv);
            });
        }

        if (hasContent) {
            const textDiv = document.createElement('div');
            // Strip any residual ```json ... ``` fences
            const sanitized = flatContent
                .replace(/```(?:json)?\s*\{[^}]*\}\s*```/gs, '')
                .replace(/```(?:json)?\s*```/g, '')
                .trim();
            if (sanitized) {
                if (!hasToolCalls) {
                    const existingFinal = contentContainer.querySelector('.agent-final-answer');
                    if (existingFinal && (existingFinal.textContent || '').trim().length > 24) {
                        scrollToBottom();
                        return;
                    }
                }
                if (hasToolCalls) {
                    textDiv.className = 'text-sm text-gray-600 mb-2 border-l-2 border-gray-200 pl-3';
                } else {
                    textDiv.classList.add('agent-final-answer', 'mt-4', 'pt-3', 'border-t', 'border-bordercolor');
                }
                textDiv.innerHTML = DOMPurify.sanitize(marked.parse(sanitized));
                contentContainer.appendChild(textDiv);
                if (!hasToolCalls) {
                    const groupWrapper = contentContainer.closest('.group-msg');
                    if (groupWrapper) {
                        addMessageActions(textDiv, sanitized, groupWrapper);
                    }
                }
            }
        }
    } else if (msg.type === 'tool') {
        // Tool Result
        const container = document.createElement('div');
        container.className = 'mt-2 border border-bordercolor rounded-lg overflow-hidden max-w-2xl';
        
        const header = document.createElement('div');
        header.className = 'bg-gray-50 px-4 py-2 flex items-center justify-between cursor-pointer hover:bg-gray-100 transition-colors border-b border-bordercolor';
        
        const headerTitle = document.createElement('div');
        headerTitle.className = 'flex items-center gap-2 text-xs font-semibold text-green-600 uppercase tracking-wider';
        headerTitle.innerHTML = `
            <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>
            Output [${msg.tool_name || 'Tool'}]
        `;
        
        const arrow = document.createElement('div');
        arrow.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="text-gray-400 transition-transform duration-200 transform"><polyline points="6 9 12 15 18 9"/></svg>';
        
        header.appendChild(headerTitle);
        header.appendChild(arrow);
        
        const body = document.createElement('div');
        body.className = 'bg-white p-4 hidden';
        
        const pre = document.createElement('pre');
        pre.className = 'text-xs font-mono text-gray-600 m-0 p-0 bg-transparent overflow-x-auto whitespace-pre-wrap';
        
        const out = flattenAiContentForUi(msg.content);
        pre.textContent = out.length > 3000 ? out.substring(0, 3000) + '\n\n... (truncated for display)' : out;
        
        body.appendChild(pre);
        container.appendChild(header);
        container.appendChild(body);
        
        // Toggle Logic
        let isExpanded = false;
        header.addEventListener('click', () => {
            isExpanded = !isExpanded;
            body.classList.toggle('hidden', !isExpanded);
            arrow.querySelector('svg').classList.toggle('rotate-180', isExpanded);
        });
        
        contentContainer.appendChild(container);
    }
    
    scrollToBottom();
}

function createToolCallUI(tc) {
    const container = document.createElement('div');
    container.className = 'mt-3 mb-1 border border-bordercolor rounded-lg overflow-hidden max-w-2xl';
    
    const header = document.createElement('div');
    header.className = 'bg-cloud px-4 py-2 flex items-center justify-between cursor-pointer hover:bg-gray-100 transition-colors';
    
    const title = document.createElement('div');
    title.className = 'flex items-center gap-2 text-sm font-medium text-gray-700';
    title.innerHTML = `
        <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="text-anthropic"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/></svg>
        Using tool <code class="bg-white border border-gray-200 px-1.5 py-0.5 rounded ml-1 text-xs text-anthropic">${tc.name}</code>
    `;
    
    const arrow = document.createElement('div');
    arrow.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="text-gray-400 transition-transform duration-200 transform rotate-180"><polyline points="6 9 12 15 18 9"/></svg>';
    
    header.appendChild(title);
    header.appendChild(arrow);
    
    const body = document.createElement('div');
    body.className = 'bg-white p-4 border-t border-bordercolor hidden';
    
    const pre = document.createElement('pre');
    pre.className = 'text-xs font-mono text-gray-600 m-0 p-0 bg-transparent overflow-x-auto';
    pre.textContent = JSON.stringify(tc.args, null, 2);
    
    body.appendChild(pre);
    
    // Toggle Logic
    let isExpanded = false;
    header.addEventListener('click', () => {
        isExpanded = !isExpanded;
        if(isExpanded) {
            body.classList.remove('hidden');
            arrow.querySelector('svg').classList.remove('rotate-180');
        } else {
            body.classList.add('hidden');
            arrow.querySelector('svg').classList.add('rotate-180');
        }
    });
    
    container.appendChild(header);
    container.appendChild(body);
    return container;
}

function renderError(err) {
    renderErrorUI(err || 'An unexpected error occurred', 'Error');
}

// Helpers
function generateUUID() {
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
        var r = Math.random() * 16 | 0, v = c == 'x' ? r : (r & 0x3 | 0x8);
        return v.toString(16);
    });
}

function scrollToBottom(force = false) {
    const _chatContainer = document.getElementById('chatContainer');
    if (!_chatContainer) return;
    // Only auto-scroll if user is near the bottom (within 150px) or forced
    const distFromBottom = _chatContainer.scrollHeight - _chatContainer.scrollTop - _chatContainer.clientHeight;
    if (force || distFromBottom < 150) {
        _chatContainer.scrollTop = _chatContainer.scrollHeight;
    }
}

// Custom Confirm Modal Helper
function showCustomConfirm(title, message, isDanger = false) {
    return new Promise((resolve) => {
        const modal = document.getElementById('customConfirmModal');
        const titleEl = document.getElementById('confirmModalTitle');
        const messageEl = document.getElementById('confirmModalMessage');
        const confirmBtn = document.getElementById('confirmConfirmBtn');
        const cancelBtn = document.getElementById('cancelConfirmBtn');

        if (!modal || !titleEl || !messageEl || !confirmBtn || !cancelBtn) {
            console.error('Custom Confirm Modal elements not found');
            resolve(confirm(message)); 
            return;
        }

        titleEl.textContent = title;
        messageEl.textContent = message;

        if (isDanger) {
            confirmBtn.className = "px-4 py-2 rounded-xl text-sm bg-red-500 text-white hover:bg-red-600 transition-colors font-medium";
            confirmBtn.textContent = "Delete";
        } else {
            confirmBtn.className = "px-4 py-2 rounded-xl text-sm bg-anthropic text-white hover:bg-opacity-90 transition-opacity font-medium";
            confirmBtn.textContent = "Confirm";
        }

        modal.classList.remove('hidden');
        modal.classList.add('flex');

        const cleanup = (result) => {
            modal.classList.add('hidden');
            modal.classList.remove('flex');
            confirmBtn.onclick = null;
            cancelBtn.onclick = null;
            resolve(result);
        };

        confirmBtn.onclick = () => cleanup(true);
        cancelBtn.onclick = () => cleanup(false);
    });
}

// Custom Input Modal Helper
function showCustomInput(title, label, defaultValue = '') {
    return new Promise((resolve) => {
        const modal = document.getElementById('customInputModal');
        const titleEl = document.getElementById('customInputTitle');
        const labelEl = document.getElementById('customInputLabel');
        const inputEl = document.getElementById('customInputField');
        const confirmBtn = document.getElementById('confirmCustomInputBtn');
        const cancelBtn = document.getElementById('cancelCustomInputBtn');
        const closeBtn = document.getElementById('closeCustomInputBtn');

        if (!modal || !titleEl || !labelEl || !inputEl || !confirmBtn || !cancelBtn || !closeBtn) {
            console.error('Custom Input Modal elements not found');
            resolve(prompt(label, defaultValue)); // Fallback
            return;
        }

        titleEl.textContent = title;
        labelEl.textContent = label;
        inputEl.value = defaultValue;
        
        modal.classList.remove('hidden');
        modal.classList.add('flex');
        
        // Timeout to ensure display is applied before focus
        setTimeout(() => {
            inputEl.focus();
            inputEl.select();
        }, 10);

        const cleanup = () => {
            modal.classList.add('hidden');
            modal.classList.remove('flex');
            confirmBtn.onclick = null;
            cancelBtn.onclick = null;
            closeBtn.onclick = null;
            inputEl.onkeydown = null;
            modal.onclick = null;
        };

        const handleConfirm = () => {
            const value = inputEl.value;
            cleanup();
            resolve(value);
        };

        const handleCancel = () => {
            cleanup();
            resolve(null);
        };

        confirmBtn.onclick = handleConfirm;
        cancelBtn.onclick = handleCancel;
        closeBtn.onclick = handleCancel;

        modal.onclick = (e) => {
            if (e.target === modal) handleCancel();
        };

        inputEl.onkeydown = (e) => {
            if (e.key === 'Enter') handleConfirm();
            if (e.key === 'Escape') handleCancel();
        };
    });
}

// ─── Workspace File Explorer Panel ──────────────────────────────────────────
async function loadWorkspaceFiles() {
    const listEl = document.getElementById('workspaceFilesList');
    if (!listEl) return;
    const projectId = getEffectiveProjectId();
    if (!projectId) {
        listEl.innerHTML = '<p class="text-xs text-gray-400 italic text-center py-8">Select a project to open workspace files.</p>';
        return;
    }
    
    try {
        const res = await fetch(`${API_BASE}/api/files?sub_path=${encodeURIComponent(currentSubPath)}&project_id=${encodeURIComponent(projectId)}`);
        const files = await res.json();
        renderWorkspaceFiles(files);
        renderBreadcrumbs();
    } catch (e) {
        // load workspace files error silenced
    }
}

function renderBreadcrumbs() {
    const breadcrumbs = document.getElementById('workspaceBreadcrumbs');
    if (!breadcrumbs) return;
    
    breadcrumbs.innerHTML = '<span class="cursor-pointer hover:text-black font-medium text-gray-700" onclick="navigateToFolder(\'\')">Workspace</span>';
    
    if (currentSubPath) {
        const parts = currentSubPath.split('/').filter(p => p);
        let pathAccum = '';
        parts.forEach(part => {
            pathAccum += (pathAccum ? '/' : '') + part;
            const currentPath = pathAccum; // Capture closed scope
            breadcrumbs.innerHTML += `
                <span class="text-gray-400">/</span>
                <span class="cursor-pointer hover:text-black" onclick="navigateToFolder('${currentPath.replace(/'/g, "\\'")}')">${part}</span>
            `;
        });
    }
}

function navigateToFolder(path) {
    currentSubPath = path;
    loadWorkspaceFiles();
}

function renderWorkspaceFiles(files) {
    const listEl = document.getElementById('workspaceFilesList');
    if (!listEl) return;
    listEl.innerHTML = '';
    
    if (files.length === 0) {
        listEl.innerHTML = '<p class="text-xs text-gray-400 italic text-center py-8">No files in workspace.</p>';
        return;
    }
    
    files.forEach(file => {
        const item = document.createElement('div');
        item.className = 'group flex items-center justify-between gap-2 p-2.5 bg-gray-50 border border-bordercolor rounded-xl text-xs hover:border-anthropic/30 hover:bg-white transition-all';
        item.dataset.filename = file.name;
        
        // Make draggable only for files
        if (file.type === 'file') {
             item.setAttribute('draggable', 'true');
             item.classList.add('cursor-grab', 'active:cursor-grabbing');
             item.addEventListener('dragstart', (e) => {
                 e.dataTransfer.setData('application/json', JSON.stringify({
                     source: 'workspace',
                     name: file.name,
                     path: currentSubPath ? `${currentSubPath}/${file.name}` : file.name
                 }));
             });
        } else if (file.type === 'folder') {
             item.classList.add('cursor-pointer');
             item.onclick = () => navigateToFolder(currentSubPath ? `${currentSubPath}/${file.name}` : file.name);
             
             // Move Drag-Drop support into folder items
             item.addEventListener('dragover', (e) => {
                 e.preventDefault();
                 item.classList.add('bg-yellow-50/50', 'border-yellow-200');
             });
             item.addEventListener('dragleave', () => {
                 item.classList.remove('bg-yellow-50/50', 'border-yellow-200');
             });
             item.addEventListener('drop', async (e) => {
                 e.preventDefault();
                 item.classList.remove('bg-yellow-50/50', 'border-yellow-200');
                 const data = e.dataTransfer.getData('application/json');
                 if (data) {
                      try {
                          const dragItem = JSON.parse(data);
                          if (dragItem.source === 'workspace' && dragItem.name !== file.name) {
                               await moveWorkspaceFile(dragItem.name, dragItem.path, currentSubPath ? `${currentSubPath}/${file.name}` : file.name);
                          }
                      } catch(err) {}
                 }
             });
        }
        
        const isProcessing = file.status === 'processing';
        const isProcessed = file.status === 'processed';
        const isFolder = file.type === 'folder';
        
        item.innerHTML = `
            <div class="flex items-center gap-2 flex-1 min-w-0 pointer-events-none">
                <div class="p-1.5 rounded-lg ${isFolder ? 'bg-yellow-50 text-yellow-600' : 'bg-gray-100 text-gray-500'}">
                    ${isFolder ? 
                       '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 20h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.93a2 2 0 0 1-1.66-.9l-.82-1.2A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/></svg>' :
                       '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>'
                    }
                </div>
                <div class="flex-1 min-w-0">
                    <p class="font-medium text-gray-800 truncate" title="${file.name}">${file.name}</p>
                    <p class="text-[10px] text-gray-400">${isFolder ? 'Folder' : formatBytes(file.size)} ${!isFolder ? '• ' + new Date(file.modified * 1000).toLocaleDateString() : ''}</p>
                </div>
                <div class="status-badge">
                    ${isProcessing && !isFolder ? '<span class="flex h-2 w-2 relative"><span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-yellow-400 opacity-75"></span><span class="relative inline-flex rounded-full h-2 w-2 bg-yellow-500"></span></span>' : ''}
                    ${isProcessed && !isFolder ? '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" class="text-green-500"><polyline points="20 6 9 17 4 12"/></svg>' : ''}
                </div>
            </div>
            <div class="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                ${!isFolder ? `
                <button class="view-file-btn p-1 rounded-md hover:bg-gray-100 text-gray-400 hover:text-black" title="View">
                    <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M2.062 12.348a1 1 0 0 1 0-.696 10.75 10.75 0 0 1 19.876 0 1 1 0 0 1 0 .696 10.75 10.75 0 0 1-19.876 0z"/><circle cx="12" cy="12" r="3"/></svg>
                </button>
                ` : ''}
                <button class="rename-file-btn p-1 rounded-md hover:bg-gray-100 text-gray-400 hover:text-anthropic" title="Rename">
                    <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/></svg>
                </button>
                <button class="delete-file-btn p-1 rounded-md hover:bg-gray-100 text-gray-400 hover:text-red-500" title="Delete">
                    <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 6h18"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
                </button>
            </div>
        `;
        
        const viewBtn = item.querySelector('.view-file-btn');
        if (viewBtn) viewBtn.onclick = (e) => { e.stopPropagation(); viewWorkspaceFile(file.name); };
        item.querySelector('.rename-file-btn').onclick = (e) => { e.stopPropagation(); renameWorkspaceFile(file.name); };
        item.querySelector('.delete-file-btn').onclick = (e) => { e.stopPropagation(); deleteWorkspaceFile(file.name); };
        
        listEl.appendChild(item);
    });
}

async function deleteWorkspaceFile(name) {
    const confirmed = await showCustomConfirm('Delete File', `Are you sure you want to delete "${name}" from the workspace?`, true);
    if (!confirmed) return;
    try {
        await fetch(`${API_BASE}/api/files/${encodeURIComponent(name)}?sub_path=${encodeURIComponent(currentSubPath)}&project_id=${getEffectiveProjectId()}`, { method: 'DELETE' });
        loadWorkspaceFiles();
    } catch (e) {
        // delete file error silenced
    }
}

async function renameWorkspaceFile(name) {
    const newName = await showCustomInput('Rename File', 'New Name', name);
    if (!newName || newName === name) return;
    try {
        await fetch(`${API_BASE}/api/files/${encodeURIComponent(name)}/rename`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ new_name: newName, sub_path: currentSubPath, project_id: getEffectiveProjectId() })
        });
        loadWorkspaceFiles();
    } catch (e) {
        // rename file error silenced
    }
}

async function moveWorkspaceFile(filename, fullSrcPath, targetSubPath) {
    try {
        let current_sub = "";
        if (fullSrcPath.includes('/')) {
             current_sub = fullSrcPath.substring(0, fullSrcPath.lastIndexOf('/'));
        }
        await fetch(`${API_BASE}/api/files/${encodeURIComponent(filename)}/move`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ 
                 current_sub_path: current_sub, 
                 target_sub_path: targetSubPath, 
                 project_id: getEffectiveProjectId() 
            })
        });
        loadWorkspaceFiles();
    } catch (e) {
        // move error silenced
    }
}

function formatBytes(bytes, decimals = 2) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const dm = decimals < 0 ? 0 : decimals;
    const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i];
}

// Bind direct upload buttons
const uploadWorkspaceBtn = document.getElementById('uploadWorkspaceBtn');
const workspaceFileInput = document.getElementById('workspaceFileInput');

uploadWorkspaceBtn?.addEventListener('click', () => workspaceFileInput?.click());

workspaceFileInput?.addEventListener('change', async (e) => {
    if (e.target.files.length === 0) return;

    for (const file of e.target.files) {
        const formData = new FormData();
        formData.append('file', file);

        try {
            await fetch(`${API_BASE}/api/upload?sub_path=${encodeURIComponent(currentSubPath)}&project_id=${getEffectiveProjectId()}`, { method: 'POST', body: formData });
        } catch (err) {
            // upload error silenced
        }
    }
    loadWorkspaceFiles(); // Refresh
});

// Bind specialized Drag & Drop on Workspace Explorer Panel
const workspacePanel = document.getElementById('workspacePanel');
const workspaceDropZone = document.getElementById('workspaceDropZone');
let workspaceDragCounter = 0; // Fixes nested bubbling locks

if (workspacePanel && workspaceDropZone) {
    workspacePanel.addEventListener('dragenter', (e) => {
        e.preventDefault(); e.stopPropagation();
        if (e.dataTransfer.types.includes('Files')) {
            workspaceDragCounter++;
            workspaceDropZone.classList.remove('hidden');
        }
    });

    workspacePanel.addEventListener('dragover', (e) => {
        e.preventDefault(); e.stopPropagation();
    });

    workspacePanel.addEventListener('dragleave', (e) => {
        e.preventDefault(); e.stopPropagation();
        workspaceDragCounter--;
        if (workspaceDragCounter <= 0) {
            workspaceDropZone.classList.add('hidden');
        }
    });

    // Handle dragleave on dropzone as well to safeguard exiting
    workspaceDropZone.addEventListener('dragleave', (e) => {
        e.preventDefault(); e.stopPropagation();
        workspaceDragCounter = 0;
        workspaceDropZone.classList.add('hidden');
    });

    workspaceDropZone.addEventListener('drop', async (e) => {
        e.preventDefault(); e.stopPropagation();
        workspaceDragCounter = 0; // Reset
        workspaceDropZone.classList.add('hidden');
        
        const files = e.dataTransfer.files;
        if (!files.length) return;
        
        for (const file of files) {
            const formData = new FormData();
            formData.append('file', file);
            try {
                await fetch(`${API_BASE}/api/upload?sub_path=${encodeURIComponent(currentSubPath)}&project_id=${getEffectiveProjectId()}`, { method: 'POST', body: formData });
            } catch (err) {
                // upload error silenced
            }
        }
        loadWorkspaceFiles();
    });
}

// ─── Workspace File Viewer Modal ────────────────────────────────────────────
async function viewWorkspaceFile(name) {
    const modal = document.getElementById('fileViewerModal');
    const titleEl = document.getElementById('fileViewerTitle');
    const contentEl = document.getElementById('fileViewerBody');
    
    if (!modal || !contentEl) return;
    
    titleEl.textContent = name;
    contentEl.innerHTML = '<p class="text-xs text-gray-400 animate-pulse">Loading preview...</p>';
    modal.classList.remove('hidden');
    modal.classList.add('flex');
    
    const fileUrl = `${API_BASE}/api/files/${encodeURIComponent(name)}?sub_path=${encodeURIComponent(currentSubPath)}&project_id=${getEffectiveProjectId()}`;
    // downloadBtn removed — element doesn't exist in Aurora HTML
    
    const ext = name.split('.').pop().toLowerCase();
    
    if (ext === 'pdf') {
        contentEl.innerHTML = `<iframe src="${fileUrl}" class="w-full h-full border-0"></iframe>`;
    } else if (['png', 'jpg', 'jpeg', 'gif', 'svg'].includes(ext)) {
        contentEl.innerHTML = `<img src="${fileUrl}" class="max-w-full max-h-full object-contain p-4" />`;
    } else {
        try {
            const res = await fetch(fileUrl);
            const text = await res.text();
            contentEl.innerHTML = `<pre class="w-full h-full p-6 text-xs text-gray-700 font-mono bg-white overflow-auto whitespace-pre-wrap">${escapeHtml(text)}</pre>`;
        } catch (e) {
            contentEl.innerHTML = `<p class="text-red-500 text-xs">Failed to load content.</p>`;
        }
    }
}

function escapeHtml(text) {
    return text.replace(/[&<>"']/g, function(m) {
        return {
            '&': '&amp;', '<': '&lt;', '>': '&gt;',
            '"': '&quot;', "'": '&#039;'
        }[m];
    });
}

// Bind Viewer Modal Close Events
document.getElementById('closeFileViewerBtn')?.addEventListener('click', () => {
    const modal = document.getElementById('fileViewerModal');
    modal.classList.add('hidden');
    modal.classList.remove('flex');
    const body = document.getElementById('fileViewerBody');
    if (body) body.innerHTML = ''; // Clear iframe memory leaky
});

document.getElementById('fileViewerModal')?.addEventListener('click', (e) => {
    if (e.target === document.getElementById('fileViewerModal')) {
        const modal = document.getElementById('fileViewerModal');
        modal.classList.add('hidden');
        modal.classList.remove('flex');
        const body = document.getElementById('fileViewerBody');
        if (body) body.innerHTML = '';
    }
});

// ─── Workspace Resizable Sidebar ───────────────────────────────────────────
(function initWorkspaceResizer() {
    const handle = document.getElementById('workspaceResizeHandle');
    const panel = document.getElementById('workspacePanel');
    if (!handle || !panel) return;

    let isResizing = false;

    handle.addEventListener('mousedown', (e) => {
        isResizing = true;
        document.body.style.cursor = 'col-resize';
        document.body.style.userSelect = 'none'; // Prevent text selection
    });

    window.addEventListener('mousemove', (e) => {
        if (!isResizing) return;
        const offsetLeft = panel.getBoundingClientRect().left;
        const newWidth = e.clientX - offsetLeft;
        
        // Boundaries
        if (newWidth > 200 && newWidth < 600) {
             panel.style.width = `${newWidth}px`;
        }
    });

    window.addEventListener('mouseup', () => {
        if (isResizing) {
            isResizing = false;
            document.body.style.cursor = '';
            document.body.style.userSelect = '';
        }
    });
})();

// ─── Workspace New Folder Toolbar Trigger ───────────────────────────────────
document.getElementById('newFolderBtn')?.addEventListener('click', async () => {
    const name = await showCustomInput('New Folder', 'Folder Name', '');
    if (!name) return;
    
    try {
        const res = await fetch(API_BASE + '/api/folders', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: name, sub_path: currentSubPath, project_id: getEffectiveProjectId() })
        });
        const data = await res.json();
        if (data.status === 'ok') {
            loadWorkspaceFiles(); // Refresh
        } else {
            alert(data.message || 'Failed to create folder');
        }
    } catch (e) {
        // new folder error silenced
    }
});

// ─── Claude-like View Management ──────────────────────────────────────────

function normalizeText(value) {
    return String(value || '').toLowerCase();
}

function setWorkspaceProject(projectId, persist = true) {
    const next = String(projectId || 'default').trim() || 'default';
    if (window.WorkspaceState && typeof WorkspaceState.setActiveProject === 'function') {
        WorkspaceState.setActiveProject(next, { persist });
    } else if (persist) {
        localStorage.setItem('active_project_id', next);
    }
    activeProjectId = next;
    return next;
}

function setChatProjectContext(projectId) {
    const next = String(projectId || getEffectiveProjectId() || 'default').trim() || 'default';
    chatProjectIdForThread = next;
    return next;
}

function getEffectiveProjectId() {
    if (window.WorkspaceState && typeof WorkspaceState.getActiveProjectId === 'function') {
        const pid = WorkspaceState.getActiveProjectId();
        if (pid) {
            if (activeProjectId !== pid) activeProjectId = pid;
            return pid;
        }
    }
    return activeProjectId || 'default';
}

function getChatProjectId() {
    const pid = getEffectiveProjectId();
    if (!chatProjectIdForThread) setChatProjectContext(pid);
    return chatProjectIdForThread || pid;
}

function isUntitledName(name) {
    const value = String(name || '').trim().toLowerCase();
    return !value || value === 'untitled' || value === 'untitled chat' || value === 'new chat';
}

function deriveChatTitle(text) {
    const cleaned = String(text || '')
        .replace(/\s+/g, ' ')
        .trim();
    if (!cleaned) return 'Untitled';
    const words = cleaned.split(' ').slice(0, 7).join(' ');
    return words.length > 52 ? `${words.slice(0, 49)}...` : words;
}

function setWorkspaceVisibility() {
    const shell = document.getElementById('auroraShell') || document.getElementById('appShell');
    const workspace = document.getElementById('workspacePanel');
    if (!shell || !workspace) return;

    const narrow = window.innerWidth < 1200;
    const view = currentView || (typeof StateManager !== 'undefined' ? StateManager.currentView : '');
    const selectedProjectId = getEffectiveProjectId();
    const hasSelectedProject = window.WorkspaceState && typeof WorkspaceState.hasProjectSelected === 'function'
        ? WorkspaceState.hasProjectSelected()
        : Boolean(selectedProjectId);
    const showWorkspace = Boolean(selectedProjectId) && view === 'chat' && !narrow;
    shell.classList.toggle('workspace-hidden', !showWorkspace);
    workspace.classList.toggle('hidden', !showWorkspace);
}

function renderProjectInspector(project) {
    const titleEl = document.getElementById('projectInspectorTitle');
    const instructionsEl = document.getElementById('projectInspectorInstructions');
    const usageEl = document.getElementById('projectInspectorUsage');
    const usageBarEl = document.getElementById('projectInspectorUsageBar');
    const metaEl = document.getElementById('projectInspectorMeta');
    const statusEl = document.getElementById('projectInspectorStatus');
    if (!titleEl || !instructionsEl || !usageEl || !usageBarEl || !metaEl || !statusEl) return;

    if (!project) {
        titleEl.textContent = 'No project selected';
        instructionsEl.textContent = 'Select a project to open workspace files and keep chats organized.';
        usageEl.textContent = '0%';
        usageBarEl.style.width = '0%';
        metaEl.textContent = '0 chats • 0 files';
        statusEl.textContent = 'Pick a project to enter workspace mode.';
        return;
    }

    const fileCount = Array.isArray(project.files) ? project.files.length : 0;
    const chatCount = Array.isArray(project.chats) ? project.chats.length : 0;
    const usagePercent = Math.min(100, fileCount * 8);
    titleEl.textContent = project.name || 'Project';
    instructionsEl.textContent = project.instructions || 'No project instructions yet.';
    usageEl.textContent = `${usagePercent}%`;
    usageBarEl.style.width = `${usagePercent}%`;
    metaEl.textContent = `${chatCount} chats • ${fileCount} files`;
    statusEl.textContent = Boolean(getEffectiveProjectId())
        ? 'Workspace unlocked. You can upload files and start chatting.'
        : 'Select this project to unlock its workspace.';
}

function renderWelcomeRecents() {
    const listEl = document.getElementById('welcomeRecentList');
    const openAllBtn = document.getElementById('welcomeOpenChatsBtn');
    if (!listEl) return;

    let candidates = [];
    if (activeProjectId) {
        const project = cachedProjects.find((p) => p.id === activeProjectId);
        candidates = (project?.chats || []).map((chat) => ({
            ...chat,
            _projectName: project?.name || 'Project',
            _projectId: project?.id || '',
        }));
    } else {
        candidates = cachedProjects.flatMap((project) =>
            (project?.chats || []).map((chat) => ({
                ...chat,
                _projectName: project?.name || 'Project',
                _projectId: project?.id || '',
            }))
        );
    }

    const sorted = [...candidates]
        .sort((a, b) => (b.created_at || 0) - (a.created_at || 0))
        .slice(0, 5);

    if (sorted.length === 0) {
        const emptyMessage = activeProjectId
            ? 'No chats yet. Start a conversation to see recents here.'
            : 'Select a project or start chatting to populate recents.';
        listEl.innerHTML = `<p class="text-xs text-gray-400 italic">${emptyMessage}</p>`;
        if (openAllBtn) openAllBtn.classList.add('opacity-40', 'pointer-events-none');
        return;
    }
    if (openAllBtn) openAllBtn.classList.remove('opacity-40', 'pointer-events-none');

    listEl.innerHTML = '';
    sorted.forEach((chat) => {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'welcome-recent-item w-full text-left px-3 py-2 rounded-xl';
        btn.innerHTML = `
            <div class="flex items-center justify-between gap-2">
                <span class="text-sm font-medium text-textdark truncate">${DOMPurify.sanitize(chat.name || 'Untitled')}</span>
                <span class="text-[10px] text-gray-400 whitespace-nowrap">${chat.created_at ? new Date(chat.created_at * 1000).toLocaleDateString() : ''}</span>
            </div>
            <div class="mt-1 text-[11px] text-gray-500 truncate">${DOMPurify.sanitize(chat._projectName || 'Project')}</div>
        `;
        btn.addEventListener('click', async () => {
            if (chat._projectId && chat._projectId !== activeProjectId) {
                await StateManager.switchProject(chat._projectId, false);
            }
            await switchChat(chat.id);
            navigateView('chat');
        });
        listEl.appendChild(btn);
    });
}


// ─── Project Detail View ────────────────────────────────────────────────────

// Standalone function to refresh only the #projectDetailFiles section
// without tearing down the entire project detail view.
async function refreshFileCards(projectId) {
    const filesEl = document.getElementById('projectDetailFiles');
    if (!filesEl) return;
    try {
        const res = await fetch(`${API_BASE}/api/files?sub_path=&project_id=${projectId}`);
        const fileList = await res.json();
        filesEl.innerHTML = '';
        if (!fileList.length) { filesEl.innerHTML = '<p class="empty-hint">No files yet.</p>'; return; }
        fileList.forEach(f => {
            if (f.is_dir) return;
            const name = f.name || f;
            const ext = name.split('.').pop().toLowerCase();
            const size = f.size ? `${(f.size / 1024).toFixed(1)} KB` : '';
            const fmtClass = ['pdf'].includes(ext)?'pdf':['docx','doc'].includes(ext)?'docx':['xlsx','xls','csv'].includes(ext)?'xlsx':['pptx','ppt'].includes(ext)?'pptx':['png','jpg','jpeg','gif','svg','webp'].includes(ext)?'img':'';
            const card = document.createElement('div');
            card.className = 'project-file-card';
            card.innerHTML = `<div class="file-actions"><button class="file-action-btn" data-action="index" title="Index to Knowledge Base">📚</button><button class="file-action-btn" data-action="rename" title="Rename">R</button><button class="file-action-btn danger" data-action="delete" title="Delete">\u00d7</button></div><span class="file-format ${fmtClass}">${ext}</span><span class="file-name" title="${DOMPurify.sanitize(name)}">${DOMPurify.sanitize(name)}</span><span class="file-size">${size}</span>`;
            card.onclick = (e) => { if (!e.target.closest('.file-action-btn')) openProjectFileViewer(projectId, name, ext); };
            card.querySelector('[data-action="index"]').onclick = (e) => { e.stopPropagation(); indexProjectFile(projectId, name); };
            card.querySelector('[data-action="rename"]').onclick = (e) => { e.stopPropagation(); renameProjectFile(projectId, name); };
            card.querySelector('[data-action="delete"]').onclick = (e) => { e.stopPropagation(); deleteProjectFile(projectId, name); };
            filesEl.appendChild(card);
        });
    } catch (_) {
        filesEl.innerHTML = '<p class="empty-hint">Could not load files.</p>';
    }
}

async function openProjectDetail(projectId) {
    const project = cachedProjects.find(p => p.id === projectId);
    if (!project) return;

    navigateView('project-detail');

    let isPinned = Boolean(localStorage.getItem(`pinproj_${projectId}`));
    document.getElementById('projectDetailName').textContent = project.name || 'Project';
    document.getElementById('projectDetailDesc').textContent = project.instructions || 'Add instructions to tailor responses for this project.';
    document.getElementById('projectDetailInstructions').textContent = project.instructions || 'Add instructions to tailor responses for this project.';
    document.getElementById('projectDetailPin').textContent = isPinned ? '★' : '☆';

    // Render recent chats for this project
    const chatsEl = document.getElementById('projectDetailChats');
    if (chatsEl) {
        const chats = (project.chats || []).sort((a, b) => (b.created_at || 0) - (a.created_at || 0)).slice(0, 10);
        if (chats.length === 0) {
            chatsEl.innerHTML = '<p class="empty-hint">No chats in this project yet.</p>';
        } else {
            chatsEl.innerHTML = '';
            chats.forEach(chat => {
                const item = document.createElement('div');
                item.className = 'chat-list-item';
                item.style.maxWidth = 'none';
                const relTime = chat.created_at ? _relativeTime(chat.created_at * 1000) : '';
                item.innerHTML = `
                    <span class="chat-title">${DOMPurify.sanitize(chat.name || 'Untitled')}</span>
                    <span class="chat-meta">${relTime}</span>
                `;
                item.onclick = () => { StateManager.switchProject(projectId, false); switchChat(chat.id); navigateView('chat'); };
                chatsEl.appendChild(item);
            });
        }
    }

    // Render files from workspace directory as cards
    await refreshFileCards(projectId);

    // Wire up buttons
    document.getElementById('projectBackBtn').onclick = () => navigateView('home');
    document.getElementById('projectDetailMenu').onclick = (e) => {
        showProjectContextMenu(e, project, isPinned);
    };
    document.getElementById('projectDetailPin').onclick = () => {
        const pinEl = document.getElementById('projectDetailPin');
        if (isPinned) {
            localStorage.removeItem(`pinproj_${projectId}`);
            if (pinEl) pinEl.textContent = '☆';
        } else {
            localStorage.setItem(`pinproj_${projectId}`, '1');
            if (pinEl) pinEl.textContent = '★';
        }
        isPinned = !isPinned;
    };
    document.getElementById('projectEditInstructions').onclick = () => editProjectInstructions(projectId, project.instructions);
    document.getElementById('projectUploadFile').onclick = () => {
        const input = document.getElementById('workspaceFileInput');
        if (!input) return;
        // One-time listener for this upload
        const handler = async () => {
            input.removeEventListener('change', handler);
            const files = input.files;
            if (!files?.length) return;
            for (const file of files) {
                const formData = new FormData();
                formData.append('file', file);
                try {
                    await fetch(`${API_BASE}/api/upload?sub_path=&project_id=${projectId}`, { method: 'POST', body: formData });
                } catch (_) {}
            }
            input.value = '';
            // Wait for file processor then refresh file cards only
            setTimeout(() => refreshFileCards(projectId), 2000);
        };
        input.addEventListener('change', handler);
        input.click();
    };
    // Project composer file attachments
    const projPreviews = document.getElementById('projectComposerPreviews');
    let projPendingFiles = [];

    function renderProjectPreviews() {
        if (!projPreviews) return;
        if (projPendingFiles.length === 0) { projPreviews.classList.add('hidden'); return; }
        projPreviews.classList.remove('hidden');
        projPreviews.innerHTML = '';
        projPendingFiles.forEach((f, i) => {
            const chip = document.createElement('span');
            chip.style.cssText = 'display:inline-flex;align-items:center;gap:0.3rem;padding:0.25rem 0.5rem;border-radius:4px;font-size:0.75rem;background:var(--surface-el);color:var(--text);border:1px solid var(--border)';
            chip.textContent = f.name;
            const x = document.createElement('button');
            x.textContent = '\u00d7'; x.style.cssText = 'cursor:pointer;color:var(--text-muted);background:none;border:none';
            x.onclick = () => { projPendingFiles.splice(i, 1); renderProjectPreviews(); };
            chip.appendChild(x);
            projPreviews.appendChild(chip);
        });
    }

    async function handleFileDrop(fileList) {
        if (!fileList?.length) return;
        for (const file of fileList) {
            const formData = new FormData();
            formData.append('file', file);
            try { await fetch(`${API_BASE}/api/upload?sub_path=&project_id=${projectId}`, { method: 'POST', body: formData }); } catch (_) {}
            try {
                const data = await new Promise((res, rej) => { const r = new FileReader(); r.onload = () => res(r.result.split(',')[1]); r.onerror = rej; r.readAsDataURL(file); });
                projPendingFiles.push({ name: file.name, type: file.type, data });
            } catch (_) {}
        }
        renderProjectPreviews();
        setTimeout(() => refreshFileCards(projectId), 2500);
    }

    // View-level drag-drop — wire events directly on the drop zone AND the detail view
    const dropZone = document.getElementById('projectDropZone');
    const detailView = document.getElementById('view-project-detail');
    if (dropZone && detailView) {
        // Abort previous listeners
        if (detailView._dragAbort) detailView._dragAbort.abort();
        const ac = new AbortController();
        detailView._dragAbort = ac;

        // Drop zone: direct handlers (most reliable for the visible drop target)
        dropZone.addEventListener('dragover', (e) => {
            e.preventDefault();
            e.stopPropagation();
            e.dataTransfer.dropEffect = 'copy';
            dropZone.classList.add('drag-active');
        }, { signal: ac.signal });

        dropZone.addEventListener('dragenter', (e) => {
            e.preventDefault();
            e.stopPropagation();
            dropZone.classList.add('drag-active');
        }, { signal: ac.signal });

        dropZone.addEventListener('dragleave', (e) => {
            e.preventDefault();
            e.stopPropagation();
            dropZone.classList.remove('drag-active');
        }, { signal: ac.signal });

        dropZone.addEventListener('drop', (e) => {
            e.preventDefault();
            e.stopPropagation();
            dropZone.classList.remove('drag-active');
            handleFileDrop(e.dataTransfer?.files);
        }, { signal: ac.signal });

        // Also handle drops anywhere on the detail view (fallback)
        detailView.addEventListener('dragover', (e) => { e.preventDefault(); }, { signal: ac.signal });
        detailView.addEventListener('drop', (e) => {
            e.preventDefault();
            handleFileDrop(e.dataTransfer?.files);
        }, { signal: ac.signal });

        dropZone.onclick = () => document.getElementById('projectUploadFile')?.click();
    }

    document.getElementById('projectSendBtn').onclick = () => {
        const input = document.getElementById('projectInput');
        const text = input?.value?.trim();
        if (!text && projPendingFiles.length === 0) return;
        StateManager.switchProject(projectId, false);
        if (projPendingFiles.length > 0) { pendingFiles.push(...projPendingFiles); projPendingFiles = []; if (projPreviews) { projPreviews.classList.add('hidden'); projPreviews.innerHTML = ''; } }
        navigateView('chat');
        const _mi = document.getElementById('messageInput');
        if (_mi) _mi.value = text || '';
        input.value = '';
        handleSend(new Event('submit'));
    };
    document.getElementById('projectInput')?.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); document.getElementById('projectSendBtn')?.click(); }
    });
}
function openProjectFileViewer(projectId, filename, ext) {
    const viewer = document.getElementById('projectFileViewer');
    const titleEl = document.getElementById('projectViewerTitle');
    const contentEl = document.getElementById('projectViewerContent');
    if (!viewer || !contentEl) return;

    titleEl.textContent = filename;
    viewer.classList.remove('hidden');
    contentEl.innerHTML = '<p class="empty-hint">Loading...</p>';

    const rawUrl = `${API_BASE}/api/files/${encodeURIComponent(filename)}?sub_path=&project_id=${projectId}`;

    if (ext === 'pdf') {
        contentEl.innerHTML = `<iframe src="${rawUrl}"></iframe>`;
    } else if (['png','jpg','jpeg','gif','svg','webp'].includes(ext)) {
        contentEl.innerHTML = `<img src="${rawUrl}" alt="${filename}">`;
    } else if (['docx','doc'].includes(ext) && typeof mammoth !== 'undefined') {
        // Render docx as HTML using mammoth.js
        fetch(rawUrl).then(r => r.arrayBuffer()).then(buffer => {
            mammoth.convertToHtml({ arrayBuffer: buffer }).then(result => {
                contentEl.innerHTML = `<div class="message-content" style="padding:0.5rem">${DOMPurify.sanitize(result.value)}</div>`;
            }).catch(() => {
                // Fallback to processed text
                loadProcessedText(contentEl, rawUrl, filename, projectId);
            });
        }).catch(() => {
            contentEl.innerHTML = '<p class="empty-hint">Could not load file.</p>';
        });
    } else {
        loadProcessedText(contentEl, rawUrl, filename, projectId);
    }
}

function loadProcessedText(contentEl, rawUrl, filename, projectId) {
    const textUrl = `${API_BASE}/api/files/${encodeURIComponent(filename)}?sub_path=&project_id=${projectId}&mode=text`;
    fetch(textUrl).then(r => {
        if (!r.ok) throw new Error('not found');
        return r.text();
    }).then(text => {
        if (text.startsWith('#') || text.includes('\n## ') || text.includes('\n- ')) {
            contentEl.innerHTML = `<div class="message-content">${DOMPurify.sanitize(marked.parse(text))}</div>`;
        } else {
            contentEl.innerHTML = `<pre>${escapeHtml(text)}</pre>`;
        }
    }).catch(() => {
        contentEl.innerHTML = '<p class="empty-hint">Could not load file content.</p>';
    });
}

async function renameProjectFile(projectId, oldName) {
    const newName = await showCustomInput('Rename File', 'New name', oldName);
    if (!newName || newName === oldName) return;
    try {
        await fetch(`${API_BASE}/api/files/${encodeURIComponent(oldName)}/rename`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ new_name: newName, sub_path: '', project_id: projectId })
        });
        openProjectDetail(projectId);
    } catch (_) {}
}

async function deleteProjectFile(projectId, filename) {
    const ok = await showCustomConfirm('Delete File', `Delete "${filename}"?`, true);
    if (!ok) return;
    try {
        await fetch(`${API_BASE}/api/files/${encodeURIComponent(filename)}?sub_path=&project_id=${projectId}`, { method: 'DELETE' });
        openProjectDetail(projectId);
    } catch (_) {}
}

async function indexProjectFile(projectId, filename) {
    /**
     * Manually index a file into the project's ChromaDB knowledge base.
     * Fetches the processed text content, then sends it to the knowledge API.
     */
    try {
        // Try mode=text first (processed cache or plain text fallback)
        const textUrl = `${API_BASE}/api/files/${encodeURIComponent(filename)}?sub_path=&project_id=${projectId}&mode=text`;
        const res = await fetch(textUrl);
        let text = '';

        if (res.ok) {
            const contentType = res.headers.get('content-type') || '';
            if (contentType.includes('text/plain') || contentType.includes('text/html')) {
                text = await res.text();
            } else {
                // Response might be JSON error
                try {
                    const json = await res.json();
                    if (json.status === 'error') {
                        text = '';
                    }
                } catch (_) {
                    text = await res.text();
                }
            }
        }

        if (!text || text.trim().length < 50) {
            alert('Could not extract text from this file. Make sure the file has been processed (wait a few seconds after upload for PDFs/XLSX).');
            return;
        }

        const indexRes = await fetch(`${API_BASE}/api/projects/${projectId}/knowledge`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ filename, content: text.trim() })
        });
        const data = await indexRes.json();
        if (data.status === 'ok') {
            alert(`Indexed "${filename}" into project knowledge base.`);
            await loadProjects();
        } else {
            alert(data.message || 'Failed to index file. ChromaDB may be unavailable.');
        }
    } catch (e) {
        // index file error silenced
        alert('Failed to index file. Check console for details.');
    }
}

function showProjectContextMenu(event, project, isPinned) {
    document.getElementById('sidebarCtxMenu')?.remove();
    const menu = document.createElement('div');
    menu.id = 'sidebarCtxMenu';
    menu.className = 'sidebar-context-menu';
    menu.innerHTML = `
        <button class="ctx-item" data-action="pin">${isPinned ? 'Unpin' : 'Pin'}</button>
        <button class="ctx-item" data-action="edit">Edit details</button>
        <div class="ctx-divider"></div>
        <button class="ctx-item danger" data-action="delete">Delete</button>
    `;
    const rect = event.target.getBoundingClientRect();
    menu.style.top = `${rect.bottom + 4}px`;
    menu.style.left = `${Math.min(rect.left, window.innerWidth - 180)}px`;
    document.body.appendChild(menu);

    menu.addEventListener('click', async (e) => {
        const action = e.target.dataset.action;
        menu.remove();
        if (action === 'pin') {
            if (isPinned) localStorage.removeItem(`pinproj_${project.id}`);
            else localStorage.setItem(`pinproj_${project.id}`, '1');
            applyProjectsFilter();
        } else if (action === 'edit') {
            editProject(project.id, project.name);
        } else if (action === 'delete') {
            deleteProject(project.id, project.name);
        }
    });
    setTimeout(() => {
        const closer = (e) => { if (!menu.contains(e.target)) { menu.remove(); document.removeEventListener('click', closer); } };
        document.addEventListener('click', closer);
    }, 10);
}

function _relativeTime(ts) {
    const diff = Date.now() - ts;
    const mins = Math.floor(diff / 60000);
    if (mins < 1) return 'Just now';
    if (mins < 60) return `${mins}m ago`;
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return `${hrs}h ago`;
    const days = Math.floor(hrs / 24);
    if (days < 7) return `${days}d ago`;
    return new Date(ts).toLocaleDateString();
}

document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        closeComposerPlusMenu();
    }
});

window.addEventListener('resize', () => {
    closeComposerPlusMenu();
    setWorkspaceVisibility();
});

// ─── Utilities ─────────────────────────────────────────────────────────────

if (typeof escapeHtml !== 'function') {
    window.escapeHtml = function(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    };
}
// ─── Global API (used by HTML onclick handlers) ────────────────────────────

window.submitAskUserResponse = submitAskUserResponse;
window.submitAskUserChoice = submitAskUserChoice;
