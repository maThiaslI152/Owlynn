/**
 * Property-based tests for project state management using fast-check + vitest (jsdom).
 *
 * Feature: productivity-workspace-overhaul
 * Validates: Requirements 11.2, 11.6
 */
import { describe, it, expect, beforeEach } from 'vitest';
import fc from 'fast-check';

// ── Arbitraries ──

/** Generate a safe project ID. */
const arbProjectId = fc.stringMatching(/^[a-zA-Z0-9_-]{1,20}$/);

/** Generate a pair of distinct project IDs. */
const arbDistinctProjectIds = fc.tuple(arbProjectId, arbProjectId).filter(([a, b]) => a !== b);

/** Generate a non-negative scroll position. */
const arbScrollPos = fc.nat({ max: 50000 });

// ── Helpers ──

/**
 * UUID generator matching the one in StateManager.
 */
function generateUUID() {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function (c) {
    const r = (Math.random() * 16) | 0;
    const v = c === 'x' ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

/**
 * Create a minimal StateManager that replicates the project context switching
 * logic from frontend/script.js — specifically switchProject(), projectThreads,
 * and thread ID generation.
 */
function createStateManager() {
  let _reconnectTimer = null;

  const state = {
    currentSessionId: generateUUID(),
    activeProjectId: null,
    projectThreads: {},
    connectionStatus: 'offline',
    socket: null,
  };

  const _subscribers = [];

  const sm = {
    get currentSessionId() { return state.currentSessionId; },
    get activeProjectId() { return state.activeProjectId; },
    get projectThreads() { return state.projectThreads; },
    get connectionStatus() { return state.connectionStatus; },

    subscribe(name, cb) { _subscribers.push({ name, cb }); },

    notify(changedKeys) {
      for (const sub of _subscribers) {
        try { sub.cb(changedKeys); } catch (_) { /* ignore */ }
      }
    },

    set(key, value) {
      if (key === 'activeProjectId' && value !== state.activeProjectId) {
        sm.switchProject(value);
        return;
      }
      state[key] = value;
      sm.notify([key]);
    },

    /**
     * Stub connectWebSocket — records the thread ID without opening a real socket.
     */
    connectWebSocket(threadId) {
      sm._lastConnectedThreadId = threadId;
    },

    /** Track the last thread ID passed to connectWebSocket. */
    _lastConnectedThreadId: null,

    /**
     * switchProject mirrors the real StateManager.switchProject logic.
     */
    switchProject(newProjectId) {
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

      // 2. Determine thread ID for the new project
      const saved = state.projectThreads[newProjectId];
      const threadId = saved ? saved.threadId : generateUUID();

      // 3. Update state
      state.activeProjectId = newProjectId;
      state.currentSessionId = threadId;

      // 4. Connect WebSocket with project-scoped thread
      sm.connectWebSocket(threadId);

      // 5. Notify subscribers
      sm.notify(['activeProjectId', 'currentSessionId']);

      // 6. Restore scroll position if returning to a previous project
      if (saved && saved.scrollPos != null) {
        const chatContainer = document.getElementById('chatContainer');
        if (chatContainer) chatContainer.scrollTop = saved.scrollPos;
      }
    },
  };

  return sm;
}

/**
 * Set up a minimal DOM with a scrollable chat container.
 */
function setupDOM() {
  document.body.innerHTML = `
    <div id="chatContainer" style="height:200px;overflow:auto;">
      <div id="messagesArea" style="height:10000px;"></div>
    </div>
  `;
}

// ── Property Tests ──

describe('Project State Management Property Tests', () => {

  /**
   * Feature: productivity-workspace-overhaul, Property 26: Project-scoped thread IDs
   *
   * For any two distinct projects, the generated WebSocket thread IDs should be
   * different, ensuring conversation isolation.
   *
   * **Validates: Requirements 11.2**
   */
  describe('Property 26: Project-scoped thread IDs', () => {
    it('distinct projects get distinct thread IDs', () => {
      fc.assert(
        fc.property(arbDistinctProjectIds, ([projectIdA, projectIdB]) => {
          setupDOM();
          const sm = createStateManager();

          // Switch to project A
          sm.switchProject(projectIdA);
          const threadA = sm.currentSessionId;

          // Switch to project B
          sm.switchProject(projectIdB);
          const threadB = sm.currentSessionId;

          // Thread IDs must differ for distinct projects
          expect(threadA).not.toBe(threadB);
        }),
        { numRuns: 200 },
      );
    });

    it('each project connects WebSocket with its own thread ID', () => {
      fc.assert(
        fc.property(arbDistinctProjectIds, ([projectIdA, projectIdB]) => {
          setupDOM();
          const sm = createStateManager();

          sm.switchProject(projectIdA);
          const wsThreadA = sm._lastConnectedThreadId;

          sm.switchProject(projectIdB);
          const wsThreadB = sm._lastConnectedThreadId;

          expect(wsThreadA).toBe(sm.projectThreads[projectIdA].threadId);
          expect(wsThreadB).toBe(sm.currentSessionId);
          expect(wsThreadA).not.toBe(wsThreadB);
        }),
        { numRuns: 200 },
      );
    });
  });

  /**
   * Feature: productivity-workspace-overhaul, Property 28: Project state restoration round-trip
   *
   * For any project that was previously active (with a saved thread ID and scroll
   * position), switching away and then switching back should restore the exact same
   * thread ID and scroll position.
   *
   * **Validates: Requirements 11.6**
   */
  describe('Property 28: Project state restoration round-trip', () => {
    it('switching away and back restores thread ID', () => {
      fc.assert(
        fc.property(arbDistinctProjectIds, ([projectIdA, projectIdB]) => {
          setupDOM();
          const sm = createStateManager();

          // Activate project A
          sm.switchProject(projectIdA);
          const originalThreadId = sm.currentSessionId;

          // Switch to project B
          sm.switchProject(projectIdB);
          expect(sm.currentSessionId).not.toBe(originalThreadId);

          // Switch back to project A
          sm.switchProject(projectIdA);
          expect(sm.currentSessionId).toBe(originalThreadId);
        }),
        { numRuns: 200 },
      );
    });

    it('switching away and back restores scroll position', () => {
      fc.assert(
        fc.property(
          arbDistinctProjectIds,
          arbScrollPos,
          ([projectIdA, projectIdB], scrollPos) => {
            setupDOM();
            const sm = createStateManager();
            const chatContainer = document.getElementById('chatContainer');

            // Activate project A and set a scroll position
            sm.switchProject(projectIdA);
            chatContainer.scrollTop = scrollPos;

            // Switch to project B (saves A's scroll position)
            sm.switchProject(projectIdB);

            // Switch back to project A — scroll position should be restored
            sm.switchProject(projectIdA);
            expect(chatContainer.scrollTop).toBe(scrollPos);
          },
        ),
        { numRuns: 200 },
      );
    });

    it('round-trip works across multiple projects', () => {
      fc.assert(
        fc.property(
          fc.uniqueArray(arbProjectId, { minLength: 3, maxLength: 6 }),
          (projectIds) => {
            setupDOM();
            const sm = createStateManager();
            const savedThreadIds = {};

            // Visit each project, record its thread ID
            for (const pid of projectIds) {
              sm.switchProject(pid);
              savedThreadIds[pid] = sm.currentSessionId;
            }

            // Revisit each project in reverse, verify thread ID is restored
            for (const pid of [...projectIds].reverse()) {
              sm.switchProject(pid);
              expect(sm.currentSessionId).toBe(savedThreadIds[pid]);
            }
          },
        ),
        { numRuns: 100 },
      );
    });
  });
});
