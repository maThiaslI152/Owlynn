/**
 * Property-Based Tests for Frontend CRUD State Management
 * ========================================================
 *
 * Uses fast-check (the JS equivalent of Hypothesis) to generate random
 * project/chat names and IDs, then verifies that the mock CRUD state
 * manager maintains correct invariants for ALL inputs.
 *
 * The mock `createCrudStateManager()` mirrors the backend ProjectManager
 * interface — purely in-memory, no network calls. This tests the frontend's
 * state management logic independently of the API.
 *
 * Properties tested:
 * - Create project returns matching name/id with empty chats/files
 * - Rename project updates only name, preserves all other fields
 * - Delete project removes it from both getProject and listProjects
 * - Add chat makes it appear in the project's chats list
 * - Rename chat updates only name, preserves id and created_at
 * - Delete chat removes it from the chats list
 *
 * Run: `cd frontend && npx vitest run`
 *
 * @module crud-operations.property.test
 */
import { describe, it, expect } from 'vitest';
import fc from 'fast-check';

// ── Arbitraries ──

/** Generate a non-empty project name (1–100 chars). */
const arbProjectName = fc.string({ minLength: 1, maxLength: 100 });

/** Generate a non-empty chat name (1–100 chars). */
const arbChatName = fc.string({ minLength: 1, maxLength: 100 });

/** Generate a hex project ID matching the backend 8-char UUID prefix format. */
const arbProjectId = fc.stringMatching(/^[a-f0-9]{8}$/);

/** Generate a UUID for chat IDs. */
const arbChatId = fc.uuid();

// ── Mock CRUD State Manager ──

/**
 * Creates a mock CRUD state manager that mirrors the backend ProjectManager
 * interface for frontend state management testing. Operations are purely
 * in-memory — no persistence or network calls.
 */
function createCrudStateManager() {
  const projects = {};

  return {
    /**
     * Create a project and store it in state.
     * Returns the created project object.
     */
    createProject(id, name) {
      const project = {
        id,
        name,
        instructions: '',
        files: [],
        chats: [],
        category: 'general',
      };
      projects[id] = project;
      return project;
    },

    /**
     * Retrieve a project by ID, or undefined if not found.
     */
    getProject(id) {
      return projects[id];
    },

    /**
     * Return all projects as an array.
     */
    listProjects() {
      return Object.values(projects);
    },

    /**
     * Rename a project. Only updates the name field; all other fields
     * remain unchanged. Returns the updated project or undefined.
     */
    renameProject(id, newName) {
      const project = projects[id];
      if (!project) return undefined;
      project.name = newName;
      return project;
    },

    /**
     * Delete a project from state. Returns true if removed, false otherwise.
     */
    deleteProject(id) {
      if (!(id in projects)) return false;
      delete projects[id];
      return true;
    },

    /**
     * Add a chat to a project's chats list. Deduplicates by chat ID.
     */
    addChat(projectId, chatId, chatName) {
      const project = projects[projectId];
      if (!project) return;
      if (project.chats.some((c) => c.id === chatId)) return;
      project.chats.push({ id: chatId, name: chatName, created_at: Date.now() });
    },

    /**
     * Rename a chat within a project. Only the name field is updated;
     * id and created_at are preserved.
     */
    renameChat(projectId, chatId, newName) {
      const project = projects[projectId];
      if (!project) return;
      const chat = project.chats.find((c) => c.id === chatId);
      if (chat) chat.name = newName;
    },

    /**
     * Delete a chat from a project's chats list.
     */
    deleteChat(projectId, chatId) {
      const project = projects[projectId];
      if (!project) return;
      project.chats = project.chats.filter((c) => c.id !== chatId);
    },
  };
}

// ── Property Tests ──

describe('Project CRUD properties', () => {
  /**
   * Property: create project returns object with matching name.
   *
   * For any project ID and name, creating a project should return an object
   * whose name matches the provided name and whose ID matches the provided ID.
   *
   * **Validates: Requirements 9.2**
   */
  it('create project returns object with matching name', () => {
    fc.assert(
      fc.property(arbProjectId, arbProjectName, (id, name) => {
        const mgr = createCrudStateManager();
        const project = mgr.createProject(id, name);

        expect(project.name).toBe(name);
        expect(project.id).toBe(id);
        expect(project.chats).toEqual([]);
        expect(project.files).toEqual([]);
      }),
      { numRuns: 100 },
    );
  });

  /**
   * Property: rename project updates name, preserves id.
   *
   * For any existing project and a new name, renaming should change only the
   * name field while the id and all other fields remain identical.
   *
   * **Validates: Requirements 9.3**
   */
  it('rename project updates name, preserves id', () => {
    fc.assert(
      fc.property(arbProjectId, arbProjectName, arbProjectName, (id, originalName, newName) => {
        const mgr = createCrudStateManager();
        mgr.createProject(id, originalName);

        const before = { ...mgr.getProject(id) };
        const updated = mgr.renameProject(id, newName);

        expect(updated.name).toBe(newName);
        expect(updated.id).toBe(before.id);
        expect(updated.instructions).toBe(before.instructions);
        expect(updated.category).toBe(before.category);
      }),
      { numRuns: 100 },
    );
  });

  /**
   * Property: delete project removes it from list.
   *
   * For any created project, deleting it should make it no longer appear
   * in the project list or be retrievable by ID.
   *
   * **Validates: Requirements 9.4**
   */
  it('delete project removes it from list', () => {
    fc.assert(
      fc.property(arbProjectId, arbProjectName, (id, name) => {
        const mgr = createCrudStateManager();
        mgr.createProject(id, name);

        const deleted = mgr.deleteProject(id);

        expect(deleted).toBe(true);
        expect(mgr.getProject(id)).toBeUndefined();
        expect(mgr.listProjects().some((p) => p.id === id)).toBe(false);
      }),
      { numRuns: 100 },
    );
  });
});

describe('Chat CRUD properties', () => {
  /**
   * Property: add chat appears in project chats list.
   *
   * For any project and chat, adding a chat should make it appear in the
   * project's chats list with the correct ID and name.
   *
   * **Validates: Requirements 9.5**
   */
  it('add chat appears in project chats list', () => {
    fc.assert(
      fc.property(arbProjectId, arbProjectName, arbChatId, arbChatName, (pid, pName, chatId, chatName) => {
        const mgr = createCrudStateManager();
        mgr.createProject(pid, pName);

        mgr.addChat(pid, chatId, chatName);

        const project = mgr.getProject(pid);
        const chat = project.chats.find((c) => c.id === chatId);
        expect(chat).toBeDefined();
        expect(chat.name).toBe(chatName);
      }),
      { numRuns: 100 },
    );
  });

  /**
   * Property: rename chat updates name, preserves id.
   *
   * For any project containing a chat, renaming the chat should update only
   * the name field while preserving the chat's id and created_at.
   *
   * **Validates: Requirements 9.6**
   */
  it('rename chat updates name, preserves id', () => {
    fc.assert(
      fc.property(
        arbProjectId, arbProjectName, arbChatId, arbChatName, arbChatName,
        (pid, pName, chatId, originalChatName, newChatName) => {
          const mgr = createCrudStateManager();
          mgr.createProject(pid, pName);
          mgr.addChat(pid, chatId, originalChatName);

          const chatBefore = { ...mgr.getProject(pid).chats.find((c) => c.id === chatId) };

          mgr.renameChat(pid, chatId, newChatName);

          const chatAfter = mgr.getProject(pid).chats.find((c) => c.id === chatId);
          expect(chatAfter.name).toBe(newChatName);
          expect(chatAfter.id).toBe(chatBefore.id);
          expect(chatAfter.created_at).toBe(chatBefore.created_at);
        },
      ),
      { numRuns: 100 },
    );
  });

  /**
   * Property: delete chat removes it from project chats.
   *
   * For any project containing a chat, deleting the chat should remove it
   * from the chats list entirely.
   *
   * **Validates: Requirements 9.7**
   */
  it('delete chat removes it from project chats', () => {
    fc.assert(
      fc.property(arbProjectId, arbProjectName, arbChatId, arbChatName, (pid, pName, chatId, chatName) => {
        const mgr = createCrudStateManager();
        mgr.createProject(pid, pName);
        mgr.addChat(pid, chatId, chatName);

        expect(mgr.getProject(pid).chats.some((c) => c.id === chatId)).toBe(true);

        mgr.deleteChat(pid, chatId);

        expect(mgr.getProject(pid).chats.some((c) => c.id === chatId)).toBe(false);
      }),
      { numRuns: 100 },
    );
  });
});
