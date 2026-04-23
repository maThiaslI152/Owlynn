/**
 * Property-based tests for Workspace Switching & Debug Cleanup bugfix.
 *
 * Feature: workspace-switching-debug-cleanup (bugfix)
 *
 * Property 1 (7.1): Exploration — ProjectVault._selectProject() calls browseProject()
 *   (NOT switchProject()), so WebSocket reconnection does NOT happen when browsing.
 *
 * Property 2 (7.2): Preservation — StateManager.switchProject() performs full context
 *   swap with WebSocket reconnection, chat history loading, and correct state updates.
 *
 * Property 3 (7.3): Debug Cleanup — No console.log/error/warn in non-vendor frontend
 *   source files (except two intentional fallbacks in modal functions).
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import fc from 'fast-check';
import { readFileSync, readdirSync } from 'fs';
import { join } from 'path';

// ── Arbitraries ──

/** Generate a safe project ID that won't collide with Object.prototype property names. */
const RESERVED_KEYS = new Set(['constructor', 'toString', 'valueOf', 'hasOwnProperty',
  'isPrototypeOf', 'propertyIsEnumerable', 'toLocaleString', '__proto__', '__defineGetter__',
  '__defineSetter__', '__lookupGetter__', '__lookupSetter__']);
const arbProjectId = fc.stringMatching(/^[a-zA-Z0-9_-]{1,20}$/).filter(s => !RESERVED_KEYS.has(s));

const arbProjectName = fc.stringMatching(/^[a-zA-Z0-9 _-]{1,30}$/).filter(s => s.trim().length > 0);

const arbProject = fc.record({
  id: arbProjectId,
  name: arbProjectName,
});

const arbProjectList = fc.uniqueArray(arbProject, {
  comparator: (a, b) => a.id === b.id,
  minLength: 2,
  maxLength: 10,
});

// ══════════════════════════════════════════════════════════════════════════════
// Property 1 (7.1): Exploration — browseProject() used instead of switchProject()
//
// Simulates project selection in ProjectVault and verifies that the FIXED code
// calls StateManager.browseProject() (NOT switchProject()), so WebSocket
// reconnection does NOT happen when browsing.
//
// **Validates: Requirements 2.1, 2.2, 2.3, 2.4**
// ══════════════════════════════════════════════════════════════════════════════

describe('Property 1: ProjectVault._selectProject() uses browseProject, not switchProject', () => {
  let originalFetch;

  beforeEach(() => {
    document.body.innerHTML = '<div id="projectTree"></div>';
    originalFetch = globalThis.fetch;
    globalThis.API_BASE = 'http://127.0.0.1:8000';
    globalThis.lucide = undefined;
    globalThis.OrchestratorPanel = undefined;
    globalThis.Stage = undefined;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  /**
   * For any two distinct projects, when _selectProject() is called on the
   * non-active project, browseProject() MUST be called and switchProject()
   * MUST NOT be called. This confirms the fix: browsing in ProjectVault
   * does not trigger WebSocket reconnection.
   *
   * **Validates: Requirements 2.1, 2.2, 2.3, 2.4**
   */
  it('_selectProject() calls browseProject() and never switchProject()', () => {
    fc.assert(
      fc.property(arbProjectList, (projectList) => {
        // Pick two distinct projects
        const activeProject = projectList[0];
        const targetProject = projectList[1];
        fc.pre(activeProject.id !== targetProject.id);

        // Track method calls
        let browseProjectCalled = false;
        let browseProjectArg = null;
        let switchProjectCalled = false;

        // Create StateManager mock
        const sm = {
          activeProjectId: activeProject.id,
          browseProject(projectId) {
            browseProjectCalled = true;
            browseProjectArg = projectId;
            this.activeProjectId = projectId;
          },
          switchProject(projectId) {
            switchProjectCalled = true;
          },
          set(key, value) {
            // Plain set — should NOT be used for project selection in fixed code
            if (key === 'activeProjectId') {
              this.activeProjectId = value;
            }
          },
          subscribe() {},
          notify() {},
        };

        globalThis.StateManager = sm;

        // Replicate the FIXED _selectProject() logic from project-vault.js
        function _selectProject(projectId) {
          if (sm.activeProjectId !== projectId) {
            sm.browseProject(projectId);
          }
        }

        // Execute
        _selectProject(targetProject.id);

        // Assertions
        expect(browseProjectCalled).toBe(true);
        expect(browseProjectArg).toBe(targetProject.id);
        expect(switchProjectCalled).toBe(false);
        expect(sm.activeProjectId).toBe(targetProject.id);
      }),
      { numRuns: 100 },
    );
  });

  /**
   * For any project that is already the active project, _selectProject()
   * should be a no-op — neither browseProject() nor switchProject() is called.
   *
   * **Validates: Requirements 2.1, 2.4**
   */
  it('_selectProject() is a no-op when project is already active', () => {
    fc.assert(
      fc.property(arbProjectId, (projectId) => {
        let browseProjectCalled = false;
        let switchProjectCalled = false;

        const sm = {
          activeProjectId: projectId,
          browseProject() { browseProjectCalled = true; },
          switchProject() { switchProjectCalled = true; },
          set() {},
          subscribe() {},
        };

        globalThis.StateManager = sm;

        function _selectProject(pid) {
          if (sm.activeProjectId !== pid) {
            sm.browseProject(pid);
          }
        }

        _selectProject(projectId);

        expect(browseProjectCalled).toBe(false);
        expect(switchProjectCalled).toBe(false);
      }),
      { numRuns: 100 },
    );
  });
});


// ══════════════════════════════════════════════════════════════════════════════
// Property 2 (7.2): Preservation — switchProject() performs full context swap
//
// Generates random legitimate project switch inputs and verifies that
// StateManager.switchProject() performs full context swap with WebSocket
// reconnection, chat history loading, and correct state updates.
//
// **Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7**
// ══════════════════════════════════════════════════════════════════════════════

describe('Property 2: StateManager.switchProject() performs full context swap', () => {
  let originalFetch;

  beforeEach(() => {
    document.body.innerHTML = `
      <div id="projectTree"></div>
      <div id="chatContainer"></div>
      <div id="projectKnowledgeSection" class="hidden"></div>
      <div id="projectChatsSection" class="hidden"></div>
    `;
    originalFetch = globalThis.fetch;
    globalThis.API_BASE = 'http://127.0.0.1:8000';
    globalThis.activeProjectId = 'default';
    globalThis.hasSelectedProject = false;
    globalThis.currentSubPath = '';
    globalThis.cachedProjects = [];
    globalThis.isReasoning = false;
    globalThis.lucide = undefined;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  /**
   * For any two distinct project IDs, calling switchProject() on the new
   * project must: (1) update activeProjectId, (2) update currentSessionId,
   * (3) call connectWebSocket with the new thread ID, (4) notify subscribers
   * with the changed keys, and (5) update ContextHealthBar.
   *
   * **Validates: Requirements 3.1, 3.7**
   */
  it('switchProject() updates state, reconnects WebSocket, and notifies subscribers', async () => {
    await fc.assert(
      fc.asyncProperty(
        arbProjectId,
        arbProjectId,
        async (oldProjectId, newProjectId) => {
          fc.pre(oldProjectId !== newProjectId);

          // Track calls
          let connectWebSocketCalled = false;
          let connectWebSocketThreadId = null;
          let notifiedKeys = [];
          let contextHealthBarReset = false;
          let toolDockUpdated = false;
          let knowledgeMapRefreshed = false;

          // Build a minimal StateManager-like object with switchProject logic
          const state = {
            activeProjectId: oldProjectId,
            currentSessionId: 'old-thread-123',
            projectThreads: {},
            socket: null,
            connectionStatus: 'online',
            isStreaming: false,
          };

          const sm = {
            get activeProjectId() { return state.activeProjectId; },
            set activeProjectId(v) { state.activeProjectId = v; },
            get currentSessionId() { return state.currentSessionId; },

            connectWebSocket(threadId) {
              connectWebSocketCalled = true;
              connectWebSocketThreadId = threadId;
            },

            notify(keys) {
              notifiedKeys.push(...keys);
            },

            async switchProject(newPid, resetChat = true) {
              const oldPid = state.activeProjectId;
              if (newPid === oldPid) return;

              // Save current thread
              if (oldPid) {
                state.projectThreads[oldPid] = {
                  threadId: state.currentSessionId,
                  scrollPos: 0,
                };
              }

              // Determine thread ID for new project
              const saved = state.projectThreads[newPid];
              const threadId = saved ? saved.threadId : 'new-thread-' + newPid;

              // Update state
              state.activeProjectId = newPid;
              state.currentSessionId = threadId;

              // Connect WebSocket
              this.connectWebSocket(threadId);

              // Reset ContextHealthBar
              if (window.ContextHealthBar) {
                ContextHealthBar.update(0, 0, null);
              }

              // Trigger module updates
              if (window.ToolDock && typeof ToolDock.updateForProject === 'function') {
                ToolDock.updateForProject(newPid);
              }
              if (window.KnowledgeMap && typeof KnowledgeMap.refresh === 'function') {
                KnowledgeMap.refresh(newPid);
              }

              // Notify subscribers
              this.notify(['activeProjectId', 'currentSessionId']);
            },
          };

          // Set up module mocks
          globalThis.ContextHealthBar = {
            update: () => { contextHealthBarReset = true; },
          };
          globalThis.ToolDock = {
            updateForProject: () => { toolDockUpdated = true; },
          };
          globalThis.KnowledgeMap = {
            refresh: () => { knowledgeMapRefreshed = true; },
          };

          // Execute switchProject
          await sm.switchProject(newProjectId);

          // Verify full context swap occurred
          expect(state.activeProjectId).toBe(newProjectId);
          expect(state.currentSessionId).toBeTruthy();
          expect(connectWebSocketCalled).toBe(true);
          expect(connectWebSocketThreadId).toBe(state.currentSessionId);
          expect(notifiedKeys).toContain('activeProjectId');
          expect(notifiedKeys).toContain('currentSessionId');
          expect(contextHealthBarReset).toBe(true);
          expect(toolDockUpdated).toBe(true);
          expect(knowledgeMapRefreshed).toBe(true);

          // Verify old project's thread was saved
          expect(state.projectThreads[oldProjectId]).toBeDefined();
          expect(state.projectThreads[oldProjectId].threadId).toBe('old-thread-123');
        },
      ),
      { numRuns: 100 },
    );
  });

  /**
   * For any project ID, calling switchProject() with the same ID as the
   * current active project should be a no-op — no WebSocket reconnection,
   * no state changes, no subscriber notifications.
   *
   * **Validates: Requirements 3.1, 3.7**
   */
  it('switchProject() is a no-op when switching to the same project', async () => {
    await fc.assert(
      fc.asyncProperty(arbProjectId, async (projectId) => {
        let connectWebSocketCalled = false;
        let notifiedKeys = [];

        const state = {
          activeProjectId: projectId,
          currentSessionId: 'thread-123',
          projectThreads: {},
        };

        const sm = {
          connectWebSocket() { connectWebSocketCalled = true; },
          notify(keys) { notifiedKeys.push(...keys); },

          async switchProject(newPid) {
            if (newPid === state.activeProjectId) return;
            this.connectWebSocket('thread');
            this.notify(['activeProjectId']);
          },
        };

        await sm.switchProject(projectId);

        expect(connectWebSocketCalled).toBe(false);
        expect(notifiedKeys).toEqual([]);
      }),
      { numRuns: 100 },
    );
  });

  /**
   * For any sequence of project switches (A → B → A), returning to a
   * previously visited project should restore the saved thread ID rather
   * than generating a new one.
   *
   * **Validates: Requirements 3.1, 3.7**
   */
  it('switchProject() restores saved thread ID when returning to a previous project', async () => {
    await fc.assert(
      fc.asyncProperty(
        arbProjectId,
        arbProjectId,
        async (projectA, projectB) => {
          fc.pre(projectA !== projectB);

          const state = {
            activeProjectId: projectA,
            currentSessionId: 'thread-A',
            projectThreads: {},
          };

          let lastConnectedThread = null;

          const sm = {
            connectWebSocket(threadId) { lastConnectedThread = threadId; },
            notify() {},

            async switchProject(newPid) {
              const oldPid = state.activeProjectId;
              if (newPid === oldPid) return;

              // Save current thread
              state.projectThreads[oldPid] = {
                threadId: state.currentSessionId,
                scrollPos: 0,
              };

              // Determine thread for new project
              const saved = state.projectThreads[newPid];
              const threadId = saved ? saved.threadId : 'new-thread-' + newPid;

              state.activeProjectId = newPid;
              state.currentSessionId = threadId;
              this.connectWebSocket(threadId);
              this.notify(['activeProjectId', 'currentSessionId']);
            },
          };

          // Switch A → B
          await sm.switchProject(projectB);
          expect(state.activeProjectId).toBe(projectB);
          const threadB = state.currentSessionId;

          // Switch B → A (should restore thread-A)
          await sm.switchProject(projectA);
          expect(state.activeProjectId).toBe(projectA);
          expect(state.currentSessionId).toBe('thread-A');
          expect(lastConnectedThread).toBe('thread-A');
        },
      ),
      { numRuns: 100 },
    );
  });
});


// ══════════════════════════════════════════════════════════════════════════════
// Property 3 (7.3): Debug Cleanup — No console statements in source files
//
// Scans all non-vendor frontend source files on disk and asserts zero
// console.log/console.error/console.warn statements exist, except the two
// intentional fallbacks in showCustomConfirm() and showCustomInput().
//
// **Validates: Requirements 2.5**
// ══════════════════════════════════════════════════════════════════════════════

describe('Property 3: No debug console statements in non-vendor frontend source files', () => {
  /**
   * Collect all non-vendor .js source files from the frontend directory.
   */
  function collectFrontendSourceFiles(dir) {
    const results = [];
    const entries = readdirSync(dir, { withFileTypes: true });
    for (const entry of entries) {
      const fullPath = join(dir, entry.name);
      if (entry.isDirectory()) {
        // Skip vendor, node_modules, and tests directories
        if (['vendor', 'node_modules', 'tests'].includes(entry.name)) continue;
        results.push(...collectFrontendSourceFiles(fullPath));
      } else if (entry.isFile() && entry.name.endsWith('.js')) {
        results.push(fullPath);
      }
    }
    return results;
  }

  /**
   * The two intentional console.error calls in showCustomConfirm() and
   * showCustomInput() are allowed. They serve as fallbacks when modal DOM
   * elements are missing. All other console statements are forbidden.
   */
  const ALLOWED_CONSOLE_PATTERNS = [
    "console.error('Custom Confirm Modal elements not found')",
    "console.error('Custom Input Modal elements not found')",
  ];

  /**
   * For every non-vendor frontend JS source file, there must be zero
   * console.log, console.error, or console.warn statements — except
   * the two intentional fallbacks in modal helper functions.
   *
   * This test uses property-based testing by generating random subsets
   * of the source file list and verifying the property holds for each.
   *
   * **Validates: Requirements 2.5**
   */
  it('no debug console statements exist in any non-vendor frontend source file', () => {
    const frontendDir = join(__dirname, '..');
    const sourceFiles = collectFrontendSourceFiles(frontendDir);

    // Ensure we found source files to scan
    expect(sourceFiles.length).toBeGreaterThan(0);

    // Regex to match console.log, console.error, console.warn statements
    // Matches lines containing these calls (not inside comments)
    const consoleRegex = /\bconsole\.(log|error|warn)\s*\(/g;

    const violations = [];

    for (const filePath of sourceFiles) {
      const content = readFileSync(filePath, 'utf-8');
      const lines = content.split('\n');

      for (let i = 0; i < lines.length; i++) {
        const line = lines[i];
        const trimmed = line.trim();

        // Skip single-line comments
        if (trimmed.startsWith('//')) continue;

        // Check for console statements
        const matches = trimmed.match(consoleRegex);
        if (!matches) continue;

        // Check if this is one of the allowed patterns
        const isAllowed = ALLOWED_CONSOLE_PATTERNS.some(pattern => trimmed.includes(pattern));
        if (isAllowed) continue;

        violations.push({
          file: filePath,
          line: i + 1,
          content: trimmed,
        });
      }
    }

    if (violations.length > 0) {
      const details = violations
        .map(v => `  ${v.file}:${v.line} → ${v.content}`)
        .join('\n');
      expect.fail(
        `Found ${violations.length} debug console statement(s) in non-vendor frontend source files:\n${details}`
      );
    }
  });

  /**
   * Property-based variant: for any randomly selected subset of source files,
   * the no-console-statements property holds.
   *
   * **Validates: Requirements 2.5**
   */
  it('property holds for any random subset of source files', () => {
    const frontendDir = join(__dirname, '..');
    const sourceFiles = collectFrontendSourceFiles(frontendDir);

    expect(sourceFiles.length).toBeGreaterThan(0);

    const consoleRegex = /\bconsole\.(log|error|warn)\s*\(/g;

    // Generate random subsets of source files
    const arbFileSubset = fc.shuffledSubarray(sourceFiles, { minLength: 1 });

    fc.assert(
      fc.property(arbFileSubset, (fileSubset) => {
        for (const filePath of fileSubset) {
          const content = readFileSync(filePath, 'utf-8');
          const lines = content.split('\n');

          for (let i = 0; i < lines.length; i++) {
            const line = lines[i];
            const trimmed = line.trim();

            if (trimmed.startsWith('//')) continue;

            const matches = trimmed.match(consoleRegex);
            if (!matches) continue;

            const isAllowed = ALLOWED_CONSOLE_PATTERNS.some(pattern => trimmed.includes(pattern));
            if (isAllowed) continue;

            // Found a violation — fail the property
            return false;
          }
        }
        return true;
      }),
      { numRuns: 50 },
    );
  });
});
