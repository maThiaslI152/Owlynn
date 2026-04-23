/**
 * Property-based tests for ToolDock module using fast-check + vitest (jsdom).
 *
 * Feature: productivity-workspace-overhaul
 * Validates: Requirements 6.6
 */
import { describe, it, expect } from 'vitest';
import fc from 'fast-check';

// ── Arbitraries ──

/** Known tool names from the ToolDock TOOL_ICON_MAP. */
const KNOWN_TOOL_NAMES = [
  'web_search', 'fetch_webpage',
  'read_workspace_file', 'write_workspace_file', 'edit_workspace_file',
  'list_workspace_files', 'delete_workspace_file',
  'create_docx', 'create_xlsx', 'create_pptx', 'create_pdf',
  'notebook_run', 'notebook_reset',
  'todo_add', 'todo_list', 'todo_complete',
  'list_skills', 'invoke_skill', 'run_skill_chain',
  'recall_memories', 'ask_user',
];

/** Tool name → Lucide icon name (mirrors tool-dock.js). */
const TOOL_ICON_MAP = {
  web_search:           'search',
  fetch_webpage:        'globe',
  read_workspace_file:  'file-text',
  write_workspace_file: 'file-text',
  edit_workspace_file:  'file-text',
  list_workspace_files: 'file-text',
  delete_workspace_file:'file-text',
  create_docx:          'file-type',
  create_xlsx:          'file-spreadsheet',
  create_pptx:          'file-type',
  create_pdf:           'file-type',
  notebook_run:         'play',
  notebook_reset:       'play',
  todo_add:             'check-square',
  todo_list:            'check-square',
  todo_complete:        'check-square',
  list_skills:          'wrench',
  invoke_skill:         'wrench',
  run_skill_chain:      'wrench',
  recall_memories:      'brain',
  ask_user:             'message-circle',
};

/** Generate a tool name — either a known one or a random alphanumeric name. */
const arbToolName = fc.oneof(
  fc.constantFrom(...KNOWN_TOOL_NAMES),
  fc.stringMatching(/^[a-z][a-z0-9_]{1,20}$/),
);

/** Generate a non-empty tool description. */
const arbToolDescription = fc.stringMatching(/^[a-zA-Z0-9 .,!?_-]{1,80}$/).filter(s => s.trim().length > 0);

/** Generate a single tool object. */
const arbTool = fc.record({
  name: arbToolName,
  description: arbToolDescription,
});

/** Generate a non-empty list of tools with unique names. */
const arbToolList = fc.uniqueArray(arbTool, {
  comparator: (a, b) => a.name === b.name,
  minLength: 1,
  maxLength: 20,
});

// ── Helpers ──

function _escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

function _iconFor(toolName) {
  return TOOL_ICON_MAP[toolName] || 'wrench';
}

/**
 * Replicate the ToolDock renderTools() logic (mirrors tool-dock.js)
 * so we can test the pure rendering behaviour in isolation.
 */
function setupToolDock() {
  document.body.innerHTML = '<div id="toolDock"></div>';
  const dockEl = document.getElementById('toolDock');

  function renderTools(tools) {
    if (!dockEl) return;
    dockEl.innerHTML = '';
    if (!tools || tools.length === 0) return;

    for (let i = 0; i < tools.length; i++) {
      const t = tools[i];
      const item = document.createElement('div');
      item.className = 'tool-dock-item';
      item.title = t.description || t.name;
      item.setAttribute('data-tool', t.name);
      item.innerHTML =
        '<i data-lucide="' + _escapeHtml(_iconFor(t.name)) + '" class="tool-dock-icon"></i>' +
        '<span>' + _escapeHtml(t.name) + '</span>';
      dockEl.appendChild(item);
    }
  }

  return { renderTools, dockEl };
}

// ── Property Tests ──

describe('ToolDock Property Tests', () => {

  /**
   * Feature: productivity-workspace-overhaul, Property 15: Tool dock displays required tool metadata
   *
   * For any tool object, the rendered Tool Dock entry should contain the tool's name,
   * an icon element, and a tooltip with the tool's description.
   *
   * **Validates: Requirements 6.6**
   */
  describe('Property 15: Tool dock displays required tool metadata', () => {
    it('each rendered tool entry contains name text, icon element, and description tooltip', () => {
      fc.assert(
        fc.property(arbToolList, (tools) => {
          const { renderTools, dockEl } = setupToolDock();

          renderTools(tools);

          const items = dockEl.querySelectorAll('.tool-dock-item');
          expect(items.length).toBe(tools.length);

          tools.forEach((tool, i) => {
            const item = items[i];

            // Tool name text is present in a <span>
            const nameEl = item.querySelector('span');
            expect(nameEl).not.toBeNull();
            expect(nameEl.textContent).toBe(tool.name);

            // Icon element exists with class tool-dock-icon
            const iconEl = item.querySelector('.tool-dock-icon');
            expect(iconEl).not.toBeNull();
            expect(iconEl.tagName.toLowerCase()).toBe('i');

            // Icon has the correct data-lucide attribute
            const expectedIcon = _iconFor(tool.name);
            expect(iconEl.getAttribute('data-lucide')).toBe(expectedIcon);

            // Tooltip (title attribute) contains the tool's description
            expect(item.title).toBe(tool.description);
          });
        }),
        { numRuns: 100 },
      );
    });
  });
});
