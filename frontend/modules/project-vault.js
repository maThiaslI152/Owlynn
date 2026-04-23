/**
 * ProjectVault — IIFE module for the left-column project explorer.
 * Renders a collapsible tree of projects and their files with context toggles.
 *
 * Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 2.1, 2.2, 2.3, 2.5, 2.6, 2.7
 */
window.ProjectVault = (() => {
  // ── State ──
  let expandedProjects = new Set();
  let contextToggles = new Map(); // Map<"projectId:filePath", boolean>
  let projectFiles = {};           // Map<projectId, files[]>
  let projects = [];
  let containerEl = null;

  // ── File-type icon mapping ──
  const FILE_ICON_MAP = {
    py: 'file-code', js: 'file-code', ts: 'file-code',
    html: 'file-type', css: 'file-type',
    json: 'database',
    md: 'file-text',
  };

  function _getFileIcon(filename) {
    const ext = (filename.split('.').pop() || '').toLowerCase();
    return FILE_ICON_MAP[ext] || 'file-text';
  }

  // ── API helpers ──
  async function _fetchProjects() {
    var base = (typeof API_BASE !== 'undefined') ? API_BASE : (window.API_BASE || 'http://127.0.0.1:8000');
    var res = await fetch(base + '/api/projects');
    if (!res.ok) throw new Error('Failed to load projects (' + res.status + ')');
    return res.json();
  }

  async function _fetchFiles(projectId) {
    var base = (typeof API_BASE !== 'undefined') ? API_BASE : (window.API_BASE || 'http://127.0.0.1:8000');
    var res = await fetch(base + '/api/files?project_id=' + encodeURIComponent(projectId));
    if (!res.ok) throw new Error('Failed to load files (' + res.status + ')');
    return res.json();
  }

  // ── Rendering ──
  function renderProjectTree(projectList) {
    if (!containerEl) return;
    containerEl.innerHTML = '';

    if (!projectList || projectList.length === 0) {
      containerEl.innerHTML = '<div class="pv-empty">No projects found</div>';
      return;
    }

    projectList.forEach(project => {
      const node = document.createElement('div');
      node.className = 'pv-project-node';
      node.dataset.projectId = project.id;

      const isActive = StateManager.activeProjectId === project.id;
      const isExpanded = expandedProjects.has(project.id);

      // Project header row
      const header = document.createElement('div');
      header.className = 'pv-project-header' + (isActive ? ' active' : '');
      header.innerHTML = `
        <i data-lucide="${isExpanded ? 'chevron-down' : 'chevron-right'}" class="pv-chevron"></i>
        <i data-lucide="folder" class="pv-folder-icon"></i>
        <span class="pv-project-name">${_escapeHtml(project.name)}</span>
        <button class="pv-upload-btn" title="Upload file to project">
          <i data-lucide="upload"></i>
        </button>
      `;
      header.addEventListener('click', (e) => {
        if (e.target.closest('.pv-upload-btn')) return;
        _selectProject(project.id);
        toggleProject(project.id);
      });
      header.querySelector('.pv-upload-btn').addEventListener('click', (e) => {
        e.stopPropagation();
        uploadFileToProject(project.id);
      });
      node.appendChild(header);

      // File subtree (only if expanded)
      if (isExpanded) {
        const subtree = document.createElement('div');
        subtree.className = 'pv-file-subtree';
        if (projectFiles[project.id]) {
          renderFileTree(project.id, projectFiles[project.id], subtree);
        } else {
          subtree.innerHTML = '<div class="pv-loading">Loading files…</div>';
          _loadFilesForProject(project.id, subtree);
        }
        node.appendChild(subtree);
      }

      containerEl.appendChild(node);
    });

    if (window.lucide) lucide.createIcons({ root: containerEl });
  }

  function renderFileTree(projectId, files, subtreeEl) {
    if (!subtreeEl) return;
    subtreeEl.innerHTML = '';

    if (!files || files.length === 0) {
      subtreeEl.innerHTML = '<div class="pv-empty-files">No files</div>';
      return;
    }

    files.forEach(file => {
      const fileName = file.name || file;
      const filePath = file.path || fileName;
      const toggleKey = `${projectId}:${filePath}`;
      const isActive = !!contextToggles.get(toggleKey);
      const iconName = _getFileIcon(fileName);

      const entry = document.createElement('div');
      entry.className = 'pv-file-entry';
      entry.innerHTML = `
        <i data-lucide="${iconName}" class="pv-file-icon"></i>
        <span class="pv-file-name">${_escapeHtml(fileName)}</span>
        <button class="pv-context-toggle ${isActive ? 'active' : 'inactive'}"
                title="${isActive ? 'Remove from context' : 'Add to context'}"
                data-project="${projectId}" data-path="${_escapeHtml(filePath)}">
          <i data-lucide="brain"></i>
        </button>
      `;

      // File click → open in Stage
      entry.querySelector('.pv-file-name').addEventListener('click', () => {
        StateManager.set('activeProjectId', projectId);
        if (window.OrchestratorPanel && typeof OrchestratorPanel.setActiveTab === 'function') {
          OrchestratorPanel.setActiveTab('stage');
        }
        if (window.Stage && typeof Stage.loadFile === 'function') {
          Stage.loadFile(projectId, filePath);
        }
      });

      // Context toggle click
      entry.querySelector('.pv-context-toggle').addEventListener('click', (e) => {
        e.stopPropagation();
        toggleContext(projectId, filePath);
      });

      subtreeEl.appendChild(entry);
    });

    if (window.lucide) lucide.createIcons({ root: subtreeEl });
  }

  // ── Actions ──
  function _selectProject(projectId) {
    if (StateManager.activeProjectId !== projectId) {
      StateManager.browseProject(projectId);
    }
    _rerender();
  }

  function toggleProject(projectId) {
    if (expandedProjects.has(projectId)) {
      expandedProjects.delete(projectId);
    } else {
      expandedProjects.add(projectId);
    }
    _rerender();
  }

  function toggleContext(projectId, filePath) {
    const key = `${projectId}:${filePath}`;
    const current = !!contextToggles.get(key);
    contextToggles.set(key, !current);
    _emitContextFiles();
    _rerender();
  }

  function getContextFiles(projectId) {
    const result = [];
    for (const [key, active] of contextToggles.entries()) {
      if (!active) continue;
      const [pid, ...pathParts] = key.split(':');
      if (pid === projectId) {
        result.push(pathParts.join(':'));
      }
    }
    return result;
  }

  function _emitContextFiles() {
    // Build Map<projectId, Set<filePath>> for StateManager
    const contextMap = new Map();
    for (const [key, active] of contextToggles.entries()) {
      if (!active) continue;
      const [pid, ...pathParts] = key.split(':');
      if (!contextMap.has(pid)) contextMap.set(pid, new Set());
      contextMap.get(pid).add(pathParts.join(':'));
    }
    StateManager.set('contextFiles', contextMap);
  }

  async function _loadFilesForProject(projectId, subtreeEl) {
    try {
      const files = await _fetchFiles(projectId);
      projectFiles[projectId] = files;
      renderFileTree(projectId, files, subtreeEl);
    } catch (err) {
      subtreeEl.innerHTML = `
        <div class="pv-error">
          <span>Failed to load files</span>
          <button class="pv-retry-btn">Retry</button>
        </div>`;
      subtreeEl.querySelector('.pv-retry-btn').addEventListener('click', () => {
        subtreeEl.innerHTML = '<div class="pv-loading">Loading files…</div>';
        _loadFilesForProject(projectId, subtreeEl);
      });
    }
  }

  function _rerender() {
    renderProjectTree(projects);
  }

  // ── Error handling ──
  function handleError(error) {
    if (!containerEl) return;
    containerEl.innerHTML = `
      <div class="pv-error">
        <span>${_escapeHtml(error.message || 'Failed to load projects')}</span>
        <button class="pv-retry-btn">Retry</button>
      </div>`;
    containerEl.querySelector('.pv-retry-btn').addEventListener('click', () => {
      init();
    });
  }

  function _escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  // ── Init ──
  async function init() {
    containerEl = document.getElementById('projectTree');
    if (!containerEl) {
      return;
    }

    // Wire up "New Project" button
    const newProjectBtn = document.getElementById('newProjectBtn');
    if (newProjectBtn) {
      newProjectBtn.addEventListener('click', createProject);
    }

    // Subscribe to project changes from other modules
    StateManager.subscribe('ProjectVault', (changedKeys) => {
      if (changedKeys.includes('activeProjectId')) {
        _rerender();
      }
    });

    // Fetch and render
    try {
      projects = await _fetchProjects();
      renderProjectTree(projects);
    } catch (err) {
      handleError(err);
      // Show error visually in case console isn't visible
      if (containerEl) {
        containerEl.innerHTML = '<div class="pv-error" style="color:red;padding:8px;font-size:12px;">Error: ' + (err.message || err) + '</div>';
      }
    }
  }

  // ── Project & file management ──
  async function createProject() {
    try {
      var name;
      if (typeof showCustomInput === 'function') {
        name = await showCustomInput('New Project', 'Project Name');
      } else {
        name = window.prompt('Project name:');
      }
      if (!name || !name.trim()) return;

      var base = (typeof API_BASE !== 'undefined') ? API_BASE : (window.API_BASE || 'http://127.0.0.1:8000');
      var res = await fetch(base + '/api/projects', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: name.trim() }),
      });
      if (!res.ok) throw new Error('Failed to create project (' + res.status + ')');
      var newProject = await res.json();
      projects.push(newProject);
      StateManager.set('activeProjectId', newProject.id);
      expandedProjects.add(newProject.id);
      _rerender();
    } catch (err) {
      // createProject error silenced
    }
  }

  async function uploadFileToProject(projectId) {
    var input = document.createElement('input');
    input.type = 'file';
    input.multiple = true;
    input.onchange = async function() {
      if (!input.files || input.files.length === 0) return;
      for (var i = 0; i < input.files.length; i++) {
        var file = input.files[i];
        try {
          var formData = new FormData();
          formData.append('file', file);
          var base = (typeof API_BASE !== 'undefined') ? API_BASE : (window.API_BASE || 'http://127.0.0.1:8000');
          var url = base + '/api/upload?project_id=' + encodeURIComponent(projectId);
          var res = await fetch(url, { method: 'POST', body: formData });
          if (!res.ok) throw new Error('Upload failed (' + res.status + ')');
        } catch (err) {
          // upload error silenced
        }
      }
      // Refresh file list for this project
      delete projectFiles[projectId];
      _rerender();
    };
    input.click();
  }

  // ── Public API ──
  return {
    init,
    renderProjectTree,
    renderFileTree,
    toggleProject,
    toggleContext,
    getContextFiles,
    createProject,
    uploadFileToProject,
    handleError,
  };
})();
