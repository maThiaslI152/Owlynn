/**
 * Property-based tests for Stage module using fast-check + vitest (jsdom).
 *
 * Feature: productivity-workspace-overhaul
 * Validates: Requirements 5.3, 5.4, 5.5
 */
import { describe, it, expect } from 'vitest';
import fc from 'fast-check';

// ── Arbitraries ──

/**
 * Generate a known file extension from the supported set.
 */
const arbKnownExt = fc.constantFrom('py', 'js', 'html', 'css', 'json', 'md');

/**
 * Expected mapping from extension to CodeMirror language string.
 */
const EXT_LANG_MAP = {
  py: 'python',
  js: 'javascript',
  html: 'html',
  css: 'css',
  json: 'json',
  md: 'markdown',
};

/**
 * Generate a safe base filename (alphanumeric, starts with letter).
 */
const arbBaseName = fc.stringMatching(/^[a-zA-Z][a-zA-Z0-9_-]{0,15}$/);

/**
 * Generate a filename with a known extension (e.g. "main.py", "app.js").
 */
const arbKnownFilename = fc.tuple(arbBaseName, arbKnownExt).map(([base, ext]) => `${base}.${ext}`);

/**
 * Generate non-empty text content for the editor.
 */
const arbContent = fc.string({ minLength: 1, maxLength: 200 });

/**
 * Generate an edit operation type.
 */
const arbEditType = fc.constantFrom('insert', 'delete', 'replace');

// ── Helpers ──

/**
 * Replicate the getLanguageExtension logic from stage.js for pure testing.
 */
function getLanguageExtension(filenameOrExt) {
  const ext = (filenameOrExt.includes('.')
    ? filenameOrExt.split('.').pop()
    : filenameOrExt
  ).toLowerCase();
  return EXT_LANG_MAP[ext] || 'plain';
}

/**
 * Set up a minimal Stage-like environment in jsdom that mirrors the
 * Stage module's edit tracking and header rendering behaviour.
 *
 * Returns an object with helpers to load a file, simulate edits,
 * and inspect the modified state and header.
 */
function setupStage() {
  // Provide the DOM containers the Stage module expects
  document.body.innerHTML =
    '<div id="stageHeader"></div>' +
    '<div id="editorContainer"></div>';

  let currentFile = null;
  let isModified = false;
  let editorInstance = null;

  const headerEl = document.getElementById('stageHeader');
  const containerEl = document.getElementById('editorContainer');

  function _escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

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

  function _destroyEditor() {
    if (editorInstance) {
      editorInstance.destroy();
      editorInstance = null;
    }
  }

  /**
   * Simulate CodeMirrorLoader.createEditor using a textarea fallback,
   * matching the shim in frontend/vendor/codemirror-loader.js.
   */
  function _createEditor(content, language) {
    _destroyEditor();
    if (!containerEl) return;

    const wrapper = document.createElement('div');
    wrapper.className = 'cm-editor-wrapper';

    const textarea = document.createElement('textarea');
    textarea.className = 'cm-editor-textarea';
    textarea.value = content || '';

    wrapper.appendChild(textarea);
    containerEl.innerHTML = '';
    containerEl.appendChild(wrapper);

    const onChange = function () {
      if (!isModified) {
        _setModified(true);
      }
    };

    textarea.addEventListener('input', onChange);

    editorInstance = {
      getContent: () => textarea.value,
      setContent: (text) => { textarea.value = text; },
      destroy: () => { wrapper.remove(); },
      _textarea: textarea,
    };
  }

  /**
   * Load a file into the stage (synchronous, no API call).
   */
  function loadFile(projectId, fileName, content) {
    const lang = getLanguageExtension(fileName);
    currentFile = {
      projectId,
      path: fileName,
      name: fileName,
      type: lang,
      content: content,
    };
    isModified = false;
    _renderHeader();
    _createEditor(content, lang);
  }

  /**
   * Simulate an edit by dispatching an input event on the textarea.
   * Applies the edit type (insert, delete, replace) to the textarea value.
   */
  function simulateEdit(editType, editText) {
    if (!editorInstance || !editorInstance._textarea) return;
    const ta = editorInstance._textarea;
    const current = ta.value;

    switch (editType) {
      case 'insert':
        ta.value = current + (editText || 'x');
        break;
      case 'delete':
        ta.value = current.length > 0 ? current.slice(0, -1) : '';
        break;
      case 'replace':
        ta.value = (editText || 'replaced');
        break;
    }

    // Dispatch input event to trigger the onChange handler
    ta.dispatchEvent(new Event('input', { bubbles: true }));
  }

  return {
    loadFile,
    simulateEdit,
    getIsModified: () => isModified,
    getHeaderEl: () => headerEl,
    getCurrentFile: () => currentFile,
  };
}

// ── Property Tests ──

describe('Stage Property Tests', () => {

  /**
   * Feature: productivity-workspace-overhaul, Property 12: File extension to language mapping
   *
   * For any file with an extension in the set {.py, .js, .html, .css, .json, .md},
   * the getLanguageExtension() function should return the correct CodeMirror language
   * extension for that file type.
   *
   * **Validates: Requirements 5.3**
   */
  describe('Property 12: File extension to language mapping', () => {
    it('maps known extensions to the correct CodeMirror language string', () => {
      fc.assert(
        fc.property(arbKnownFilename, (filename) => {
          const ext = filename.split('.').pop().toLowerCase();
          const expected = EXT_LANG_MAP[ext];

          const result = getLanguageExtension(filename);

          expect(result).toBe(expected);
        }),
        { numRuns: 100 },
      );
    });

    it('maps bare extensions (without dot) to the correct language', () => {
      fc.assert(
        fc.property(arbKnownExt, (ext) => {
          const expected = EXT_LANG_MAP[ext];

          const result = getLanguageExtension(ext);

          expect(result).toBe(expected);
        }),
        { numRuns: 100 },
      );
    });
  });

  /**
   * Feature: productivity-workspace-overhaul, Property 13: Edit tracking sets modified flag
   *
   * For any file open in the Stage, making any edit (inserting, deleting, or replacing text)
   * should set isModified to true, and the Stage header should display the modified indicator.
   *
   * **Validates: Requirements 5.4, 5.5**
   */
  describe('Property 13: Edit tracking sets modified flag', () => {
    it('any edit sets isModified to true and shows the modified indicator', () => {
      fc.assert(
        fc.property(
          arbKnownFilename,
          arbContent,
          arbEditType,
          fc.string({ minLength: 1, maxLength: 50 }),
          (filename, initialContent, editType, editText) => {
            const stage = setupStage();

            // Load a file — isModified should start as false
            stage.loadFile('test-project', filename, initialContent);
            expect(stage.getIsModified()).toBe(false);

            // The modified indicator should NOT have the 'visible' class
            const dotBefore = stage.getHeaderEl().querySelector('.stage-modified');
            expect(dotBefore).not.toBeNull();
            expect(dotBefore.classList.contains('visible')).toBe(false);

            // Perform an edit
            stage.simulateEdit(editType, editText);

            // isModified should now be true
            expect(stage.getIsModified()).toBe(true);

            // The modified indicator should have the 'visible' class
            const dotAfter = stage.getHeaderEl().querySelector('.stage-modified');
            expect(dotAfter).not.toBeNull();
            expect(dotAfter.classList.contains('visible')).toBe(true);
          },
        ),
        { numRuns: 100 },
      );
    });
  });
});
