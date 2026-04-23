/**
 * ToolDock — IIFE module for the project-specific tool toolbar.
 * Renders tool icons in #toolDock filtered by the active project's category.
 *
 * Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6
 */
window.ToolDock = (() => {
  'use strict';

  // ── State ──
  let allTools = [];
  let filteredTools = [];
  let dockEl = null;

  // ── Category → toolbox registry keys ──
  const CATEGORY_TOOLBOX_MAP = {
    cybersec:    ['web_search', 'file_ops'],
    writing:     ['data_viz', 'productivity'],
    research:    ['web_search', 'memory'],
    development: ['file_ops', 'data_viz', 'productivity'],
    data:        ['data_viz', 'file_ops'],
    general:     ['all'],
  };

  // ── Toolbox key → tool names that belong to it ──
  const TOOLBOX_TOOLS = {
    web_search:   ['web_search', 'fetch_webpage'],
    file_ops:     ['read_workspace_file', 'write_workspace_file', 'edit_workspace_file', 'list_workspace_files', 'delete_workspace_file'],
    data_viz:     ['create_docx', 'create_xlsx', 'create_pptx', 'create_pdf', 'notebook_run', 'notebook_reset'],
    productivity: ['todo_add', 'todo_list', 'todo_complete', 'list_skills', 'invoke_skill', 'run_skill_chain'],
    memory:       ['recall_memories'],
  };

  // ── Tool name → Lucide icon name ──
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

  // ── Helpers ──

  function _escapeHtml(str) {
    var div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  /**
   * Resolve which tool names are allowed for a given category.
   * Returns null to indicate "all tools".
   */
  function _resolveToolNames(category) {
    var cat = (category || 'general').toLowerCase();
    var keys = CATEGORY_TOOLBOX_MAP[cat] || CATEGORY_TOOLBOX_MAP.general;
    if (keys.indexOf('all') !== -1) return null; // all tools
    var allowed = [];
    for (var i = 0; i < keys.length; i++) {
      var toolbox = TOOLBOX_TOOLS[keys[i]];
      if (toolbox) {
        for (var j = 0; j < toolbox.length; j++) {
          if (allowed.indexOf(toolbox[j]) === -1) allowed.push(toolbox[j]);
        }
      }
    }
    return allowed;
  }

  /**
   * Get the Lucide icon name for a tool.
   */
  function _iconFor(toolName) {
    return TOOL_ICON_MAP[toolName] || 'wrench';
  }

  // ── Core functions ──

  /**
   * Fetch all tools from the backend.
   */
  async function _fetchTools() {
    try {
      var res = await fetch(API_BASE + '/api/tools');
      if (!res.ok) throw new Error('Failed to fetch tools');
      var data = await res.json();
      allTools = Array.isArray(data) ? data : (data.tools || []);
    } catch (err) {
      allTools = [];
    }
  }

  /**
   * Update the dock for the active project's category.
   * @param {string} [projectId]
   */
  function updateForProject(projectId) {
    var category = 'general';
    var projects = (typeof StateManager !== 'undefined' && StateManager.cachedProjects) || [];
    for (var i = 0; i < projects.length; i++) {
      if (projects[i].id === projectId) {
        category = projects[i].category || 'general';
        break;
      }
    }

    var allowed = _resolveToolNames(category);
    if (allowed === null) {
      filteredTools = allTools.slice();
    } else {
      filteredTools = allTools.filter(function (t) {
        return allowed.indexOf(t.name) !== -1;
      });
    }
    renderTools(filteredTools);
  }

  /**
   * Render tool icons into #toolDock.
   * @param {Array} tools
   */
  function renderTools(tools) {
    if (!dockEl) return;
    dockEl.innerHTML = '';
    if (!tools || tools.length === 0) return;

    for (var i = 0; i < tools.length; i++) {
      var t = tools[i];
      var item = document.createElement('div');
      item.className = 'tool-dock-item';
      item.title = t.description || t.name;
      item.setAttribute('data-tool', t.name);
      item.innerHTML =
        '<i data-lucide="' + _escapeHtml(_iconFor(t.name)) + '" class="tool-dock-icon"></i>' +
        '<span>' + _escapeHtml(t.name) + '</span>';
      item.addEventListener('click', (function (name) {
        return function () { triggerTool(name); };
      })(t.name));
      dockEl.appendChild(item);
    }

    // Re-render Lucide icons for the new elements
    if (window.lucide) lucide.createIcons({ nodes: [dockEl] });
  }

  /**
   * Insert a tool invocation into the chat input.
   * @param {string} toolName
   */
  function triggerTool(toolName) {
    var input = document.getElementById('messageInput');
    if (!input) return;
    var prefix = input.value ? input.value.trimEnd() + ' ' : '';
    input.value = prefix + '@' + toolName + ' ';
    input.focus();
    // Trigger auto-resize if available
    input.dispatchEvent(new Event('input', { bubbles: true }));
  }

  // ── Init ──

  async function init() {
    dockEl = document.getElementById('toolDock');
    if (!dockEl) {
      return;
    }
    await _fetchTools();
    // Render with current project
    var pid = (typeof StateManager !== 'undefined' && StateManager.activeProjectId) || 'default';
    updateForProject(pid);
  }

  // ── Public API ──
  return {
    init: init,
    updateForProject: updateForProject,
    renderTools: renderTools,
    triggerTool: triggerTool,
    CATEGORY_TOOLBOX_MAP: CATEGORY_TOOLBOX_MAP,
  };
})();
