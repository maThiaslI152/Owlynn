/**
 * CodeMirror Loader — Placeholder / Shim
 *
 * This file provides a textarea-based fallback editor that mimics the API
 * surface the Stage module (frontend/modules/stage.js) expects from
 * CodeMirror 6.  It should be replaced with the actual CodeMirror 6 ESM
 * bundle (core editor + language modes for Python, JavaScript, HTML, CSS,
 * JSON, Markdown + basic dark theme) when the vendored bundle is available.
 *
 * Usage:
 *   const editor = CodeMirrorLoader.createEditor(container, {
 *     content: '...',
 *     language: 'javascript',   // python | javascript | html | css | json | markdown | plain
 *     readOnly: false,
 *     onChange: (newContent) => { ... }
 *   });
 *
 *   editor.getContent()          → current text
 *   editor.setContent(str)       → replace text
 *   editor.setLanguage(lang)     → switch syntax class
 *   editor.setReadOnly(bool)     → toggle editing
 *   editor.destroy()             → clean up DOM
 */

/* global window */
(function () {
  'use strict';

  // ── Language → CSS class mapping ──────────────────────────────────────
  const LANG_CLASS_MAP = {
    python:     'cm-lang-python',
    javascript: 'cm-lang-javascript',
    html:       'cm-lang-html',
    css:        'cm-lang-css',
    json:       'cm-lang-json',
    markdown:   'cm-lang-markdown',
    plain:      'cm-lang-plain',
  };

  // ── Inject editor styles once ─────────────────────────────────────────
  const STYLE_ID = 'codemirror-loader-styles';
  function injectStyles() {
    if (document.getElementById(STYLE_ID)) return;
    const style = document.createElement('style');
    style.id = STYLE_ID;
    style.textContent = `
/* CodeMirror Loader — Fallback Editor Styles */
.cm-editor-wrapper {
  position: relative;
  display: flex;
  width: 100%;
  height: 100%;
  background: var(--bg, #080c14);
  border: 1px solid var(--border, #232e48);
  border-radius: 6px;
  overflow: hidden;
  font-family: 'JetBrains Mono', 'Fira Code', 'Cascadia Code', 'Consolas', monospace;
  font-size: 13px;
  line-height: 1.6;
}

/* Line-number gutter */
.cm-line-numbers {
  flex-shrink: 0;
  width: 48px;
  padding: 10px 8px 10px 0;
  text-align: right;
  color: var(--text-muted, #7a879e);
  background: var(--bg-soft, #0d1321);
  border-right: 1px solid var(--border, #232e48);
  user-select: none;
  overflow: hidden;
  white-space: pre;
  font: inherit;
}

/* Textarea editor area */
.cm-editor-textarea {
  flex: 1;
  resize: none;
  border: none;
  outline: none;
  padding: 10px 12px;
  margin: 0;
  background: transparent;
  color: var(--text, #d4dae8);
  font: inherit;
  line-height: inherit;
  tab-size: 4;
  white-space: pre;
  overflow: auto;
}

.cm-editor-textarea::placeholder {
  color: var(--text-muted, #7a879e);
}

.cm-editor-textarea:read-only {
  opacity: 0.7;
  cursor: default;
}

/* Language-specific accent on the left border */
.cm-editor-wrapper.cm-lang-python   { border-left: 3px solid #3572A5; }
.cm-editor-wrapper.cm-lang-javascript { border-left: 3px solid #f1e05a; }
.cm-editor-wrapper.cm-lang-html     { border-left: 3px solid #e34c26; }
.cm-editor-wrapper.cm-lang-css      { border-left: 3px solid #563d7c; }
.cm-editor-wrapper.cm-lang-json     { border-left: 3px solid #40b5a4; }
.cm-editor-wrapper.cm-lang-markdown { border-left: 3px solid #083fa1; }
.cm-editor-wrapper.cm-lang-plain    { border-left: 3px solid var(--border, #232e48); }
`;
    document.head.appendChild(style);
  }

  // ── Line-number helper ────────────────────────────────────────────────
  function buildLineNumbers(text) {
    const count = (text.match(/\n/g) || []).length + 1;
    const lines = [];
    for (let i = 1; i <= count; i++) lines.push(i);
    return lines.join('\n');
  }

  // ── Public API ────────────────────────────────────────────────────────

  /**
   * Create a fallback editor inside `container`.
   *
   * @param {HTMLElement} container  — DOM element to mount into
   * @param {Object}      opts
   * @param {string}      [opts.content='']       — initial text
   * @param {string}      [opts.language='plain']  — language key
   * @param {boolean}     [opts.readOnly=false]
   * @param {Function}    [opts.onChange]           — called with new content string
   * @returns {{ getContent, setContent, setLanguage, setReadOnly, destroy }}
   */
  function createEditor(container, opts) {
    opts = opts || {};
    const content   = opts.content  || '';
    const language  = opts.language || 'plain';
    const readOnly  = !!opts.readOnly;
    const onChange   = typeof opts.onChange === 'function' ? opts.onChange : null;

    injectStyles();

    // Build DOM
    const wrapper = document.createElement('div');
    wrapper.className = 'cm-editor-wrapper ' + (LANG_CLASS_MAP[language] || LANG_CLASS_MAP.plain);

    const gutter = document.createElement('pre');
    gutter.className = 'cm-line-numbers';
    gutter.setAttribute('aria-hidden', 'true');

    const textarea = document.createElement('textarea');
    textarea.className = 'cm-editor-textarea';
    textarea.spellcheck = false;
    textarea.autocomplete = 'off';
    textarea.autocapitalize = 'off';
    textarea.value = content;
    textarea.readOnly = readOnly;
    textarea.placeholder = 'Open a file to start editing…';

    wrapper.appendChild(gutter);
    wrapper.appendChild(textarea);
    container.innerHTML = '';
    container.appendChild(wrapper);

    // Sync line numbers
    function syncGutter() {
      gutter.textContent = buildLineNumbers(textarea.value);
    }
    syncGutter();

    // Sync scroll between gutter and textarea
    textarea.addEventListener('scroll', function () {
      gutter.scrollTop = textarea.scrollTop;
    });

    // Input handler
    textarea.addEventListener('input', function () {
      syncGutter();
      if (onChange) onChange(textarea.value);
    });

    // ── Returned editor instance ──────────────────────────────────────
    return {
      /** @returns {string} current editor content */
      getContent: function () {
        return textarea.value;
      },

      /** Replace editor content */
      setContent: function (text) {
        textarea.value = text;
        syncGutter();
      },

      /** Switch the language class on the wrapper */
      setLanguage: function (lang) {
        Object.values(LANG_CLASS_MAP).forEach(function (cls) {
          wrapper.classList.remove(cls);
        });
        wrapper.classList.add(LANG_CLASS_MAP[lang] || LANG_CLASS_MAP.plain);
      },

      /** Toggle read-only mode */
      setReadOnly: function (flag) {
        textarea.readOnly = !!flag;
      },

      /** Remove the editor from the DOM */
      destroy: function () {
        wrapper.remove();
      },
    };
  }

  // ── Expose global ─────────────────────────────────────────────────────
  window.CodeMirrorLoader = {
    createEditor: createEditor,
  };
})();
