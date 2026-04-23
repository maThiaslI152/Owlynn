/**
 * Stage — IIFE module for the central file editor.
 * Uses the vendored CodeMirror loader shim for syntax highlighting.
 *
 * Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7
 */
window.Stage = (() => {
  'use strict';

  // ── State ──
  let currentFile = null;   // { projectId, path, name, type, content }
  let isModified = false;
  let editorInstance = null; // CodeMirror editor returned by CodeMirrorLoader.createEditor

  // ── DOM refs ──
  let headerEl = null;
  let containerEl = null;

  // ── Language mapping: extension → CodeMirror language key ──
  const EXT_LANG_MAP = {
    py: 'python',
    js: 'javascript',
    html: 'html',
    css: 'css',
    json: 'json',
    md: 'markdown',
  };

  /**
   * Map a filename or extension to a CodeMirror language string.
   * @param {string} filenameOrExt
   * @returns {string}
   */
  function getLanguageExtension(filenameOrExt) {
    const ext = (filenameOrExt.includes('.')
      ? filenameOrExt.split('.').pop()
      : filenameOrExt
    ).toLowerCase();
    return EXT_LANG_MAP[ext] || 'plain';
  }

  // ── Rendering helpers ──

  function _renderHeader() {
    if (!headerEl) return;
    if (!currentFile) {
      headerEl.innerHTML = '';
      return;
    }
    const lang = getLanguageExtension(currentFile.name);
    headerEl.innerHTML =
      '<span class="stage-filename">' + _escapeHtml(currentFile.name) + '</span>' +
      '<span class="stage-filetype">' + _escapeHtml(lang) + '</span>' +
      '<span class="stage-modified' + (isModified ? ' visible' : '') + '">●</span>';
  }

  function _setModified(flag) {
    isModified = flag;
    const dot = headerEl && headerEl.querySelector('.stage-modified');
    if (dot) {
      dot.classList.toggle('visible', flag);
    }
  }

  // ── Editor lifecycle ──

  function _destroyEditor() {
    if (editorInstance) {
      editorInstance.destroy();
      editorInstance = null;
    }
  }

  function _createEditor(content, language) {
    _destroyEditor();
    if (!containerEl) return;

    editorInstance = window.CodeMirrorLoader.createEditor(containerEl, {
      content: content || '',
      language: language || 'plain',
      readOnly: false,
      onChange: function () {
        if (!isModified) {
          _setModified(true);
        }
      },
    });
  }

  // ── API helpers ──

  /**
   * Load file content from the backend.
   * @param {string} projectId
   * @param {string} filePath
   */
  async function loadFile(projectId, filePath) {
    // Prompt save if current file has unsaved changes
    if (currentFile && isModified) {
      promptSaveIfModified();
    }

    const fileName = filePath.split('/').pop();
    const subPath = filePath.includes('/') ? filePath.substring(0, filePath.lastIndexOf('/')) : '';

    try {
      const url = API_BASE + '/api/files/' + encodeURIComponent(fileName) +
        '?project_id=' + encodeURIComponent(projectId) +
        '&sub_path=' + encodeURIComponent(subPath) +
        '&mode=text';

      const res = await fetch(url);
      if (!res.ok) throw new Error('Failed to load file (' + res.status + ')');

      const text = await res.text();
      const lang = getLanguageExtension(fileName);

      currentFile = {
        projectId: projectId,
        path: filePath,
        name: fileName,
        type: lang,
        content: text,
      };

      isModified = false;
      _renderHeader();
      _createEditor(text, lang);
    } catch (err) {
      handleError(err, function () { loadFile(projectId, filePath); });
    }
  }

  /**
   * Save current file content back to the server via POST /api/upload.
   */
  async function save() {
    if (!currentFile || !editorInstance) return;

    const content = editorInstance.getContent();
    const formData = new FormData();
    const blob = new Blob([content], { type: 'text/plain' });
    formData.append('file', blob, currentFile.name);

    const url = API_BASE + '/api/upload' +
      '?project_id=' + encodeURIComponent(currentFile.projectId) +
      '&sub_path=' + encodeURIComponent(
        currentFile.path.includes('/')
          ? currentFile.path.substring(0, currentFile.path.lastIndexOf('/'))
          : ''
      );

    try {
      const res = await fetch(url, { method: 'POST', body: formData });
      if (!res.ok) throw new Error('Save failed (' + res.status + ')');
      currentFile.content = content;
      _setModified(false);
    } catch (err) {
      handleError(err);
    }
  }

  /**
   * If the current file has unsaved changes, prompt the user to save.
   * Returns true if the user chose to save or discard, false if cancelled.
   * @returns {boolean}
   */
  function promptSaveIfModified() {
    if (!isModified) return true;
    var shouldSave = confirm('You have unsaved changes in "' + (currentFile ? currentFile.name : 'file') + '". Save before switching?');
    if (shouldSave) {
      save();
    }
    // Always allow the switch (save or discard)
    return true;
  }

  // ── Error handling ──

  /**
   * Show an error overlay inside the editor container with an optional retry callback.
   * @param {Error} error
   * @param {Function} [retryCb]
   */
  function handleError(error, retryCb) {
    _destroyEditor();
    if (!containerEl) return;

    var msg = (error && error.message) ? error.message : 'An error occurred';
    containerEl.innerHTML =
      '<div class="stage-error-overlay">' +
        '<p>' + _escapeHtml(msg) + '</p>' +
        (retryCb ? '<button class="stage-retry-btn">Retry</button>' : '') +
      '</div>';

    if (retryCb) {
      var btn = containerEl.querySelector('.stage-retry-btn');
      if (btn) btn.addEventListener('click', retryCb);
    }
  }

  // ── Utilities ──

  function _escapeHtml(str) {
    var div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  // ── Init ──

  function init() {
    headerEl = document.getElementById('stageHeader');
    containerEl = document.getElementById('editorContainer');

    if (!headerEl || !containerEl) {
      // DOM elements not found — Stage will be non-functional
    }

    // Show placeholder when no file is loaded
    if (containerEl && !currentFile) {
      containerEl.innerHTML =
        '<div class="stage-placeholder">' +
          '<p>No file open</p>' +
          '<span>Select a file from the Explorer to start editing</span>' +
        '</div>';
    }
  }

  // ── Public API ──
  return {
    init: init,
    loadFile: loadFile,
    save: save,
    promptSaveIfModified: promptSaveIfModified,
    getLanguageExtension: getLanguageExtension,
    handleError: handleError,
    getCurrentFile: function () { return currentFile; },
    isModified: function () { return isModified; },
  };
})();
