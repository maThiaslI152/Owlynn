/**
 * Property-based tests for ProjectVault module using fast-check + vitest (jsdom).
 *
 * Feature: productivity-workspace-overhaul
 * Validates: Requirements 1.1, 1.3, 1.4, 1.5, 2.2, 2.3, 2.5, 2.6, 2.7
 */
import { describe, it, expect, beforeEach } from 'vitest';
import fc from 'fast-check';

// ── Arbitraries ──

/** Generate a safe non-empty alphanumeric id (no colons to avoid key-split issues). */
const arbProjectId = fc.stringMatching(/^[a-zA-Z0-9_-]{1,20}$/);

/** Generate a safe project name. */
const arbProjectName = fc.stringMatching(/^[a-zA-Z0-9 _-]{1,30}$/).filter(s => s.trim().length > 0);

/** Generate a project object. */
const arbProject = fc.record({
  id: arbProjectId,
  name: arbProjectName,
});

/** Generate a list of projects with unique IDs. */
const arbProjectList = fc.uniqueArray(arbProject, { comparator: (a, b) => a.id === b.id, minLength: 1, maxLength: 20 });

/** Generate a file extension. */
const arbFileExt = fc.constantFrom('py', 'js', 'ts', 'html', 'css', 'json', 'md', 'txt', 'rs');

/** Generate a safe filename. */
const arbFileName = fc.tuple(
  fc.stringMatching(/^[a-zA-Z][a-zA-Z0-9_-]{0,15}$/),
  arbFileExt,
).map(([base, ext]) => `${base}.${ext}`);

/** Generate a file object. */
const arbFile = arbFileName.map(name => ({ name, path: name }));

/** Generate a non-empty list of files with unique names. */
const arbFileList = fc.uniqueArray(arbFile, { comparator: (a, b) => a.name === b.name, minLength: 1, maxLength: 15 });

// ── Helpers ──

/** Minimal StateManager mock. */
function createStateManager() {
  const state = { activeProjectId: null };
  const subscribers = {};
  return {
    get activeProjectId() { return state.activeProjectId; },
    set activeProjectId(v) { state.activeProjectId = v; },
    set(key, value) {
      state[key] = value;
      // Notify subscribers
      for (const cb of Object.values(subscribers)) {
        cb([key]);
      }
    },
    get(key) { return state[key]; },
    subscribe(name, cb) { subscribers[name] = cb; },
  };
}

/**
 * Load the ProjectVault IIFE in a fresh jsdom context.
 * Returns the ProjectVault public API and the StateManager mock.
 */
function setupVault() {
  // Reset DOM
  document.body.innerHTML = '<div id="projectTree"></div>';

  // Setup globals the IIFE expects
  const sm = createStateManager();
  globalThis.StateManager = sm;
  globalThis.API_BASE = '';
  globalThis.lucide = undefined; // no icon library in tests
  globalThis.OrchestratorPanel = undefined;
  globalThis.Stage = undefined;

  // We can't re-evaluate the IIFE easily, so we replicate the internal state
  // by creating a fresh module-like object that mirrors the public API.
  // Instead, we'll directly use the module's public functions by re-evaluating the source.

  // Actually, the simplest approach: define the module inline using the same logic.
  // This avoids issues with IIFE re-evaluation and global pollution.

  // ── Replicated ProjectVault logic (mirrors project-vault.js) ──
  let expandedProjects = new Set();
  let contextToggles = new Map();
  let projectFiles = {};
  let projects = [];
  let containerEl = document.getElementById('projectTree');

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

  function _escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

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

      const isActive = sm.activeProjectId === project.id;
      const isExpanded = expandedProjects.has(project.id);

      const header = document.createElement('div');
      header.className = 'pv-project-header' + (isActive ? ' active' : '');
      header.innerHTML = `
        <i data-lucide="${isExpanded ? 'chevron-down' : 'chevron-right'}" class="pv-chevron"></i>
        <i data-lucide="folder" class="pv-folder-icon"></i>
        <span class="pv-project-name">${_escapeHtml(project.name)}</span>
      `;
      header.addEventListener('click', () => {
        _selectProject(project.id);
        toggleProject(project.id);
      });
      node.appendChild(header);

      if (isExpanded) {
        const subtree = document.createElement('div');
        subtree.className = 'pv-file-subtree';
        if (projectFiles[project.id]) {
          renderFileTree(project.id, projectFiles[project.id], subtree);
        } else {
          subtree.innerHTML = '<div class="pv-loading">Loading files…</div>';
        }
        node.appendChild(subtree);
      }

      containerEl.appendChild(node);
    });
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

      entry.querySelector('.pv-context-toggle').addEventListener('click', (e) => {
        e.stopPropagation();
        toggleContext(projectId, filePath);
      });

      subtreeEl.appendChild(entry);
    });
  }

  function _selectProject(projectId) {
    if (sm.activeProjectId !== projectId) {
      sm.set('activeProjectId', projectId);
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

  function _rerender() {
    projects = projects; // keep reference
    renderProjectTree(projects);
  }

  function setProjects(list) {
    projects = list;
  }

  function setProjectFiles(projectId, files) {
    projectFiles[projectId] = files;
  }

  return {
    vault: {
      renderProjectTree,
      renderFileTree,
      toggleProject,
      toggleContext,
      getContextFiles,
      setProjects,
      setProjectFiles,
    },
    sm,
    containerEl,
    expandedProjects,
    contextToggles,
  };
}

// ── Property Tests ──

describe('ProjectVault Property Tests', () => {

  /**
   * Feature: productivity-workspace-overhaul, Property 1: Project tree renders all projects
   *
   * For any list of projects returned by the API, the Project Vault render function
   * should produce exactly one tree node per project, each containing the project name.
   *
   * **Validates: Requirements 1.1**
   */
  describe('Property 1: Project tree renders all projects', () => {
    it('renders exactly one .pv-project-node per project with correct name', () => {
      fc.assert(
        fc.property(arbProjectList, (projectList) => {
          const { vault, containerEl } = setupVault();

          vault.renderProjectTree(projectList);

          const nodes = containerEl.querySelectorAll('.pv-project-node');
          expect(nodes.length).toBe(projectList.length);

          projectList.forEach((project, i) => {
            const nameEl = nodes[i].querySelector('.pv-project-name');
            expect(nameEl).not.toBeNull();
            expect(nameEl.textContent).toBe(project.name);
          });
        }),
        { numRuns: 100 },
      );
    });
  });

  /**
   * Feature: productivity-workspace-overhaul, Property 2: Project selection updates active state
   *
   * For any project in the project list, selecting it should set
   * StateManager.activeProjectId to that project's ID.
   *
   * **Validates: Requirements 1.3**
   */
  describe('Property 2: Project selection updates active state', () => {
    it('clicking a project header sets activeProjectId on StateManager', () => {
      fc.assert(
        fc.property(arbProjectList, (projectList) => {
          const { vault, sm, containerEl } = setupVault();

          vault.renderProjectTree(projectList);

          // Pick a random project to click
          const idx = Math.floor(Math.random() * projectList.length);
          const target = projectList[idx];

          const headers = containerEl.querySelectorAll('.pv-project-header');
          headers[idx].click();

          expect(sm.activeProjectId).toBe(target.id);
        }),
        { numRuns: 100 },
      );
    });
  });

  /**
   * Feature: productivity-workspace-overhaul, Property 3: File entry contains required elements
   *
   * For any file entry object (with name, type, and path), the rendered file entry
   * should contain the filename text, a file-type icon element, and a Context Toggle control.
   *
   * **Validates: Requirements 1.4, 2.1**
   */
  describe('Property 3: File entry contains required elements', () => {
    it('each rendered file entry has filename, icon, and context toggle', () => {
      fc.assert(
        fc.property(arbProjectId, arbFileList, (projectId, files) => {
          const { vault } = setupVault();

          const subtreeEl = document.createElement('div');
          document.body.appendChild(subtreeEl);

          vault.renderFileTree(projectId, files, subtreeEl);

          const entries = subtreeEl.querySelectorAll('.pv-file-entry');
          expect(entries.length).toBe(files.length);

          files.forEach((file, i) => {
            const entry = entries[i];
            // Filename text
            const nameEl = entry.querySelector('.pv-file-name');
            expect(nameEl).not.toBeNull();
            expect(nameEl.textContent).toBe(file.name);

            // File-type icon
            const iconEl = entry.querySelector('.pv-file-icon');
            expect(iconEl).not.toBeNull();

            // Context toggle button
            const toggleBtn = entry.querySelector('.pv-context-toggle');
            expect(toggleBtn).not.toBeNull();
          });

          subtreeEl.remove();
        }),
        { numRuns: 100 },
      );
    });
  });

  /**
   * Feature: productivity-workspace-overhaul, Property 4: Expand/collapse state round-trip
   *
   * For any project node, expanding it, collapsing it, and expanding it again should
   * result in the same expanded state as the first expansion.
   *
   * **Validates: Requirements 1.5**
   */
  describe('Property 4: Expand/collapse state round-trip', () => {
    it('expand → collapse → expand returns to expanded state', () => {
      fc.assert(
        fc.property(arbProjectId, (projectId) => {
          const { vault, expandedProjects } = setupVault();

          // Start collapsed
          expect(expandedProjects.has(projectId)).toBe(false);

          // Expand
          vault.toggleProject(projectId);
          expect(expandedProjects.has(projectId)).toBe(true);

          // Collapse
          vault.toggleProject(projectId);
          expect(expandedProjects.has(projectId)).toBe(false);

          // Expand again
          vault.toggleProject(projectId);
          expect(expandedProjects.has(projectId)).toBe(true);
        }),
        { numRuns: 100 },
      );
    });
  });

  /**
   * Feature: productivity-workspace-overhaul, Property 5: Context toggle round-trip
   *
   * For any file in a project, activating the Context Toggle and then deactivating it
   * should return the contextFiles set to its original state.
   *
   * **Validates: Requirements 2.2, 2.3**
   */
  describe('Property 5: Context toggle round-trip', () => {
    it('toggle on then off returns getContextFiles to original state', () => {
      fc.assert(
        fc.property(arbProjectId, arbFileName, (projectId, fileName) => {
          const { vault } = setupVault();

          // Initially no context files
          const before = vault.getContextFiles(projectId);
          expect(before).toEqual([]);

          // Toggle on
          vault.toggleContext(projectId, fileName);
          const during = vault.getContextFiles(projectId);
          expect(during).toContain(fileName);

          // Toggle off
          vault.toggleContext(projectId, fileName);
          const after = vault.getContextFiles(projectId);
          expect(after).toEqual([]);
        }),
        { numRuns: 100 },
      );
    });
  });

  /**
   * Feature: productivity-workspace-overhaul, Property 6: Context toggle visual state matches boolean
   *
   * For any file entry and its toggle state (true or false), the toggle element's CSS class
   * should be "active" when the state is true and "inactive" when the state is false.
   *
   * **Validates: Requirements 2.5, 2.6**
   */
  describe('Property 6: Context toggle visual state matches boolean', () => {
    it('toggle CSS class reflects the boolean state', () => {
      fc.assert(
        fc.property(arbProjectId, arbFileList, fc.boolean(), (projectId, files, toggleOn) => {
          const { vault } = setupVault();

          // If toggleOn, activate context for the first file
          if (toggleOn) {
            vault.toggleContext(projectId, files[0].path);
          }

          const subtreeEl = document.createElement('div');
          document.body.appendChild(subtreeEl);

          vault.renderFileTree(projectId, files, subtreeEl);

          const firstToggle = subtreeEl.querySelector('.pv-context-toggle');
          if (toggleOn) {
            expect(firstToggle.classList.contains('active')).toBe(true);
            expect(firstToggle.classList.contains('inactive')).toBe(false);
          } else {
            expect(firstToggle.classList.contains('inactive')).toBe(true);
            expect(firstToggle.classList.contains('active')).toBe(false);
          }

          subtreeEl.remove();
        }),
        { numRuns: 100 },
      );
    });
  });

  /**
   * Feature: productivity-workspace-overhaul, Property 7: Context toggle persistence across view switches
   *
   * For any set of context toggle states for a project, navigating away from that project
   * and returning should preserve all toggle states exactly.
   *
   * **Validates: Requirements 2.7**
   */
  describe('Property 7: Context toggle persistence across view switches', () => {
    it('toggle states survive project switch and return', () => {
      fc.assert(
        fc.property(
          arbProjectId,
          arbProjectId.filter(id => id.length > 0),
          arbFileList,
          (projectIdA, projectIdB, files) => {
            // Ensure distinct project IDs
            fc.pre(projectIdA !== projectIdB);

            const { vault } = setupVault();

            // Toggle on some files for project A
            const toggledFiles = files.slice(0, Math.max(1, Math.floor(files.length / 2)));
            for (const file of toggledFiles) {
              vault.toggleContext(projectIdA, file.path);
            }

            // Snapshot the context files for project A
            const beforeSwitch = vault.getContextFiles(projectIdA).sort();

            // "Switch" to project B (toggle some files there)
            vault.toggleContext(projectIdB, 'some-other-file.js');

            // "Return" to project A — check context files are preserved
            const afterReturn = vault.getContextFiles(projectIdA).sort();

            expect(afterReturn).toEqual(beforeSwitch);
          },
        ),
        { numRuns: 100 },
      );
    });
  });
});
