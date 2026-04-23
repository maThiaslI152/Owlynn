/**
 * Property-based tests for Explorer Enhancements using fast-check + vitest (jsdom).
 *
 * Feature: explorer-enhancements
 * Validates: Requirements 1.1, 2.1, 2.2, 3.2, 3.3, 4.1, 4.2, 4.3, 5.1, 5.2, 10.1, 10.2
 *
 * The rendering functions (renderExplorerProjects, renderChatSubList) are defined
 * inline in index.html's DOMContentLoaded handler. We replicate the pure rendering
 * logic here for testing, following the same pattern as project-vault.property.test.js.
 */
import { describe, it, expect, beforeEach } from 'vitest';
import fc from 'fast-check';

// ── Arbitraries ──

/** Safe non-empty alphanumeric project ID. */
const arbProjectId = fc.stringMatching(/^[a-zA-Z0-9_-]{1,20}$/);

/** Safe project name. */
const arbProjectName = fc.stringMatching(/^[a-zA-Z0-9 _-]{1,30}$/).filter(s => s.trim().length > 0);

/** A project object (never 'default' ID). */
const arbNonDefaultProject = fc.record({
  id: arbProjectId.filter(id => id !== 'default'),
  name: arbProjectName,
});

/** A project object that may be default. */
const arbProject = fc.record({
  id: arbProjectId,
  name: arbProjectName,
});

/** List of projects with unique IDs. */
const arbProjectList = fc.uniqueArray(arbProject, {
  comparator: (a, b) => a.id === b.id,
  minLength: 1,
  maxLength: 15,
});

/** Safe chat ID. */
const arbChatId = fc.stringMatching(/^[a-zA-Z0-9_-]{1,20}$/);

/** ISO-ish timestamp for sorting. */
const arbTimestamp = fc.date({ min: new Date('2020-01-01T00:00:00.000Z'), max: new Date('2029-12-31T23:59:59.999Z') })
  .filter(d => !isNaN(d.getTime()))
  .map(d => d.toISOString());

/** Chat name that is a non-empty string. */
const arbChatName = fc.stringMatching(/^[a-zA-Z0-9 _-]{1,30}$/).filter(s => s.trim().length > 0);

/** Chat object with a valid name. */
const arbChatWithName = fc.record({
  id: arbChatId,
  name: arbChatName,
  created_at: arbTimestamp,
});

/** Chat object with a falsy name (null, undefined, or empty string). */
const arbChatFalsyName = fc.record({
  id: arbChatId,
  name: fc.constantFrom(null, undefined, ''),
  created_at: arbTimestamp,
});

/** Chat object with name from mixed pool (valid or falsy). */
const arbChatMixed = fc.oneof(arbChatWithName, arbChatFalsyName);

/** List of chats with unique IDs. */
const arbChatList = fc.uniqueArray(arbChatWithName, {
  comparator: (a, b) => a.id === b.id,
  minLength: 1,
  maxLength: 15,
});

/** List of chats with unique IDs (may have falsy names). */
const arbChatListMixed = fc.uniqueArray(arbChatMixed, {
  comparator: (a, b) => a.id === b.id,
  minLength: 1,
  maxLength: 15,
});

// ── Replicated Rendering Logic ──
// Mirrors the inline code in index.html's DOMContentLoaded handler.

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

/**
 * Set up a fresh DOM + state and return the rendering functions and state objects.
 */
function setup() {
  document.body.innerHTML = '<div id="projectTree"></div>';
  const container = document.getElementById('projectTree');

  // Explorer state
  let activeProjectId = null;
  let currentSessionId = null;
  const explorerExpandedProjects = new Set();
  const explorerChatCache = {};

  function renderExplorerProjects(projects) {
    container.innerHTML = '';
    if (!projects || projects.length === 0) {
      container.innerHTML = '<div class="pv-empty">No projects</div>';
      return;
    }
    for (let i = 0; i < projects.length; i++) {
      const project = projects[i];
      const isActive = (project.id === activeProjectId);
      const isExpanded = explorerExpandedProjects.has(project.id);
      const isDefault = (project.id === 'default');

      const node = document.createElement('div');
      node.className = 'pv-project-node';

      const header = document.createElement('div');
      header.className = 'pv-project-header' + (isActive ? ' active' : '');

      const chevronSpan = '<span class="pv-chevron">' + (isExpanded ? '▼' : '▶') + '</span>';
      const nameSpan = '<span class="pv-project-name">' + escapeHtml(project.name || project.id) + '</span>';
      let actionBtns = '';
      if (!isDefault) {
        actionBtns = '<button class="explorer-edit-btn" title="Rename">✎</button>' +
          '<button class="explorer-delete-btn" title="Delete">🗑</button>';
      }
      header.innerHTML = chevronSpan + nameSpan + actionBtns;
      node.appendChild(header);

      // Render chat sub-list if expanded and cached
      if (isExpanded) {
        const subtree = document.createElement('div');
        subtree.className = 'explorer-chat-subtree';
        if (explorerChatCache[project.id]) {
          renderChatSubList(project.id, explorerChatCache[project.id], subtree);
        } else {
          subtree.innerHTML = '<div class="pv-loading">Loading chats…</div>';
        }
        node.appendChild(subtree);
      }

      container.appendChild(node);
    }
  }

  function renderChatSubList(projectId, chats, subtreeEl) {
    subtreeEl.innerHTML = '';
    const sorted = (chats || []).slice().sort(function (a, b) {
      return (b.created_at || '').localeCompare(a.created_at || '');
    });
    for (let j = 0; j < sorted.length; j++) {
      const chat = sorted[j];
      const isActiveChat = (chat.id === currentSessionId);
      const item = document.createElement('div');
      item.className = 'explorer-chat-item' + (isActiveChat ? ' active' : '');
      const chatName = chat.name ? chat.name : 'Untitled';
      item.innerHTML = '<span class="explorer-chat-icon">💬</span>' +
        '<span class="explorer-chat-name">' + escapeHtml(chatName) + '</span>';
      item.dataset.chatId = chat.id;
      subtreeEl.appendChild(item);
    }
    // "New Chat" button
    const newChatBtn = document.createElement('div');
    newChatBtn.className = 'explorer-new-chat-btn';
    newChatBtn.innerHTML = '<span>+ New Chat</span>';
    subtreeEl.appendChild(newChatBtn);
  }

  return {
    container,
    renderExplorerProjects,
    renderChatSubList,
    explorerExpandedProjects,
    explorerChatCache,
    setActiveProjectId(id) { activeProjectId = id; },
    setCurrentSessionId(id) { currentSessionId = id; },
  };
}

// ── Property Tests ──

describe('Explorer Enhancements Property Tests', () => {

  /**
   * Property 1: Project count matches rendered nodes
   *
   * For any list of projects, the Explorer renderer should produce exactly one
   * `.pv-project-node` element per project. Empty array produces empty-state message.
   *
   * **Validates: Requirement 1.1**
   */
  describe('Property 1: Project count matches rendered nodes', () => {
    it('renders exactly one .pv-project-node per project', () => {
      fc.assert(
        fc.property(arbProjectList, (projects) => {
          const { renderExplorerProjects, container } = setup();
          renderExplorerProjects(projects);

          const nodes = container.querySelectorAll('.pv-project-node');
          expect(nodes.length).toBe(projects.length);
        }),
        { numRuns: 100 },
      );
    });

    it('empty project array produces empty-state message and zero nodes', () => {
      const { renderExplorerProjects, container } = setup();
      renderExplorerProjects([]);

      const nodes = container.querySelectorAll('.pv-project-node');
      expect(nodes.length).toBe(0);

      const emptyMsg = container.querySelector('.pv-empty');
      expect(emptyMsg).not.toBeNull();
      expect(emptyMsg.textContent).toContain('No projects');
    });
  });

  /**
   * Property 2: Active project is visually distinguished
   *
   * For any project list and active project ID from the list, exactly one
   * `.pv-project-header.active` exists. If activeProjectId is not in the list,
   * zero active headers exist.
   *
   * **Validates: Requirements 2.1, 2.2**
   */
  describe('Property 2: Active project highlighting', () => {
    it('exactly one header is .active when activeProjectId is in the list', () => {
      fc.assert(
        fc.property(
          arbProjectList,
          fc.nat(),
          (projects, idxSeed) => {
            const env = setup();
            const idx = idxSeed % projects.length;
            env.setActiveProjectId(projects[idx].id);
            env.renderExplorerProjects(projects);

            const activeHeaders = env.container.querySelectorAll('.pv-project-header.active');
            expect(activeHeaders.length).toBe(1);

            const activeName = activeHeaders[0].querySelector('.pv-project-name');
            expect(activeName.textContent).toBe(projects[idx].name);
          },
        ),
        { numRuns: 100 },
      );
    });

    it('zero active headers when activeProjectId is not in the list', () => {
      fc.assert(
        fc.property(arbProjectList, (projects) => {
          const env = setup();
          env.setActiveProjectId('__nonexistent_id__');
          env.renderExplorerProjects(projects);

          const activeHeaders = env.container.querySelectorAll('.pv-project-header.active');
          expect(activeHeaders.length).toBe(0);
        }),
        { numRuns: 100 },
      );
    });
  });

  /**
   * Property 4: Expanded projects have chat subtrees, collapsed ones do not
   *
   * For any project list and random expanded subset, expanded projects have
   * `.explorer-chat-subtree` children with ▼ chevron, collapsed ones don't
   * and show ▶ chevron.
   *
   * **Validates: Requirements 3.2, 3.3**
   */
  describe('Property 4: Expand/collapse state reflected in DOM', () => {
    it('expanded projects have subtree + ▼, collapsed have no subtree + ▶', () => {
      fc.assert(
        fc.property(
          arbProjectList,
          fc.func(fc.boolean()),
          (projects, shouldExpand) => {
            const env = setup();

            // Decide which projects to expand using the generated function
            const expandedIds = new Set();
            projects.forEach((p, i) => {
              if (shouldExpand(i)) {
                expandedIds.add(p.id);
                env.explorerExpandedProjects.add(p.id);
                // Put dummy chats in cache so subtree renders items
                env.explorerChatCache[p.id] = [];
              }
            });

            env.renderExplorerProjects(projects);

            const nodes = env.container.querySelectorAll('.pv-project-node');
            expect(nodes.length).toBe(projects.length);

            projects.forEach((project, i) => {
              const node = nodes[i];
              const subtree = node.querySelector('.explorer-chat-subtree');
              const chevron = node.querySelector('.pv-chevron');

              if (expandedIds.has(project.id)) {
                expect(subtree).not.toBeNull();
                expect(chevron.textContent).toBe('▼');
              } else {
                expect(subtree).toBeNull();
                expect(chevron.textContent).toBe('▶');
              }
            });
          },
        ),
        { numRuns: 100 },
      );
    });
  });

  /**
   * Property 5: Chat sub-list has N+1 children
   *
   * For any project with N chats, the rendered Chat_Sub_List should contain
   * exactly N chat items plus one "New Chat" button (N+1 children total).
   *
   * **Validates: Requirements 4.1, 4.2**
   */
  describe('Property 5: Chat sub-list child count', () => {
    it('subtree has exactly chats.length + 1 children (N items + New Chat btn)', () => {
      fc.assert(
        fc.property(arbChatList, (chats) => {
          const env = setup();
          const subtreeEl = document.createElement('div');
          document.body.appendChild(subtreeEl);

          env.renderChatSubList('test-project', chats, subtreeEl);

          const chatItems = subtreeEl.querySelectorAll('.explorer-chat-item');
          const newChatBtn = subtreeEl.querySelector('.explorer-new-chat-btn');

          expect(chatItems.length).toBe(chats.length);
          expect(newChatBtn).not.toBeNull();
          expect(subtreeEl.children.length).toBe(chats.length + 1);

          subtreeEl.remove();
        }),
        { numRuns: 100 },
      );
    });

    it('empty chats array → 1 child (New Chat button only)', () => {
      const env = setup();
      const subtreeEl = document.createElement('div');
      document.body.appendChild(subtreeEl);

      env.renderChatSubList('test-project', [], subtreeEl);

      expect(subtreeEl.children.length).toBe(1);
      expect(subtreeEl.querySelector('.explorer-new-chat-btn')).not.toBeNull();
      expect(subtreeEl.querySelectorAll('.explorer-chat-item').length).toBe(0);

      subtreeEl.remove();
    });
  });

  /**
   * Property 6: Null or empty chat names render as "Untitled"
   *
   * For any chat whose name is null, undefined, or empty string, the rendered
   * chat item should display "Untitled". Chats with valid names display their name.
   *
   * **Validates: Requirement 4.3**
   */
  describe('Property 6: Null/empty chat names render as "Untitled"', () => {
    it('falsy names display "Untitled", truthy names display the name', () => {
      fc.assert(
        fc.property(arbChatListMixed, (chats) => {
          const env = setup();
          const subtreeEl = document.createElement('div');
          document.body.appendChild(subtreeEl);

          env.renderChatSubList('test-project', chats, subtreeEl);

          const chatItems = subtreeEl.querySelectorAll('.explorer-chat-item');
          expect(chatItems.length).toBe(chats.length);

          // Build a map of chat id → expected display name
          // Chats are sorted by created_at descending, so we need to match by order
          const sorted = chats.slice().sort((a, b) =>
            (b.created_at || '').localeCompare(a.created_at || '')
          );

          sorted.forEach((chat, i) => {
            const nameEl = chatItems[i].querySelector('.explorer-chat-name');
            const expectedName = chat.name ? chat.name : 'Untitled';
            expect(nameEl.textContent).toBe(expectedName);
          });

          subtreeEl.remove();
        }),
        { numRuns: 100 },
      );
    });
  });

  /**
   * Property 7: Active chat is highlighted
   *
   * For any chat list where currentSessionId matches one chat, exactly one
   * `.explorer-chat-item.active` exists. If currentSessionId doesn't match,
   * zero active items.
   *
   * **Validates: Requirements 5.1, 5.2**
   */
  describe('Property 7: Active chat highlighting', () => {
    it('exactly one chat item is .active when currentSessionId matches', () => {
      fc.assert(
        fc.property(
          arbChatList,
          fc.nat(),
          (chats, idxSeed) => {
            const env = setup();
            const idx = idxSeed % chats.length;
            env.setCurrentSessionId(chats[idx].id);

            const subtreeEl = document.createElement('div');
            document.body.appendChild(subtreeEl);

            env.renderChatSubList('test-project', chats, subtreeEl);

            const activeItems = subtreeEl.querySelectorAll('.explorer-chat-item.active');
            expect(activeItems.length).toBe(1);
            expect(activeItems[0].dataset.chatId).toBe(chats[idx].id);

            subtreeEl.remove();
          },
        ),
        { numRuns: 100 },
      );
    });

    it('zero active items when currentSessionId is not in the list', () => {
      fc.assert(
        fc.property(arbChatList, (chats) => {
          const env = setup();
          env.setCurrentSessionId('__nonexistent_session__');

          const subtreeEl = document.createElement('div');
          document.body.appendChild(subtreeEl);

          env.renderChatSubList('test-project', chats, subtreeEl);

          const activeItems = subtreeEl.querySelectorAll('.explorer-chat-item.active');
          expect(activeItems.length).toBe(0);

          subtreeEl.remove();
        }),
        { numRuns: 100 },
      );
    });
  });

  /**
   * Property 11: Default project protection
   *
   * For any project list containing the default project (id === 'default'),
   * the default project's header has zero edit/delete buttons, while every
   * non-default project's header has exactly one of each.
   *
   * **Validates: Requirements 10.1, 10.2**
   */
  describe('Property 11: Default project protection', () => {
    it('default project has no edit/delete buttons; non-default projects have both', () => {
      // Generate a list that always includes the default project
      const arbListWithDefault = fc.tuple(
        arbProjectName,
        fc.uniqueArray(arbNonDefaultProject, {
          comparator: (a, b) => a.id === b.id,
          minLength: 0,
          maxLength: 10,
        }),
      ).map(([defaultName, others]) => {
        // Filter out any that accidentally got 'default' as id
        const filtered = others.filter(p => p.id !== 'default');
        return [{ id: 'default', name: defaultName }, ...filtered];
      });

      fc.assert(
        fc.property(arbListWithDefault, (projects) => {
          const env = setup();
          env.renderExplorerProjects(projects);

          const nodes = env.container.querySelectorAll('.pv-project-node');
          expect(nodes.length).toBe(projects.length);

          projects.forEach((project, i) => {
            const header = nodes[i].querySelector('.pv-project-header');
            const editBtns = header.querySelectorAll('.explorer-edit-btn');
            const deleteBtns = header.querySelectorAll('.explorer-delete-btn');

            if (project.id === 'default') {
              expect(editBtns.length).toBe(0);
              expect(deleteBtns.length).toBe(0);
            } else {
              expect(editBtns.length).toBe(1);
              expect(deleteBtns.length).toBe(1);
            }
          });
        }),
        { numRuns: 100 },
      );
    });
  });
});
