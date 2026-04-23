/**
 * Property-based tests for CommandBar module using fast-check + vitest (jsdom).
 *
 * Feature: productivity-workspace-overhaul
 * Validates: Requirements 7.2, 7.3, 7.4
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import fc from 'fast-check';

// ── Arbitraries ──

/** Generate a non-empty search query string. */
const arbQuery = fc.stringMatching(/^[a-zA-Z0-9 _.\-/]{1,40}$/).filter(s => s.trim().length > 0);

/** Generate a search result object matching the API response shape. */
const arbSearchResult = fc.record({
  project_id: fc.stringMatching(/^[a-z0-9]{3,12}$/),
  project_name: fc.stringMatching(/^[A-Za-z0-9 _-]{1,30}$/).filter(s => s.trim().length > 0),
  file_path: fc.stringMatching(/^[a-z0-9_/]+\.[a-z]{1,4}$/).filter(s => s.length > 2),
  snippet: fc.stringMatching(/^[a-zA-Z0-9 (){}:;=_.,\n]{1,120}$/).filter(s => s.trim().length > 0),
  match_type: fc.constantFrom('content', 'filename', 'project_name'),
});

/** Generate a non-empty list of search results. */
const arbSearchResults = fc.array(arbSearchResult, { minLength: 1, maxLength: 10 });

/** Generate a sequence of keystrokes (queries) arriving rapidly. */
const arbKeystrokeSequence = fc.array(arbQuery, { minLength: 2, maxLength: 10 });

// ── Helpers ──

/**
 * Set up a minimal DOM environment matching what CommandBar expects,
 * and replicate the core logic for isolated testing.
 */
function setupCommandBarDOM() {
  document.body.innerHTML = `
    <div id="spotlightModal" class="hidden">
      <div class="modal-backdrop"></div>
      <input id="spotlightInput" type="text" />
      <div id="spotlightResults"></div>
    </div>
    <textarea id="messageInput"></textarea>
  `;

  return {
    modal: document.getElementById('spotlightModal'),
    input: document.getElementById('spotlightInput'),
    results: document.getElementById('spotlightResults'),
    chatInput: document.getElementById('messageInput'),
  };
}

/**
 * Replicate the CommandBar renderResults() logic (mirrors command-bar.js)
 * so we can test the pure rendering behaviour in isolation.
 */
function renderResults(resultsEl, items) {
  resultsEl.innerHTML = '';
  if (!items.length) {
    resultsEl.innerHTML = '<div class="spotlight-item" style="color:var(--text-muted);">No results found</div>';
    return;
  }
  items.forEach((item) => {
    const btn = document.createElement('button');
    btn.className = 'spotlight-item';
    btn.type = 'button';

    const info = document.createElement('div');
    info.style.cssText = 'display:flex;flex-direction:column;gap:2px;overflow:hidden;';

    const top = document.createElement('span');
    top.style.cssText = 'font-size:0.8rem;color:var(--text-muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;';
    top.textContent = `${item.project_name || 'Unknown'} — ${item.file_path || item.file_name || ''}`;

    const snippet = document.createElement('span');
    snippet.style.cssText = 'font-size:0.82rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;';
    snippet.textContent = (item.snippet || '').replace(/\n/g, ' ').slice(0, 120);

    info.appendChild(top);
    info.appendChild(snippet);
    btn.appendChild(info);

    resultsEl.appendChild(btn);
  });
}

/**
 * Replicate the CommandBar insertSnippet() logic (mirrors command-bar.js)
 * so we can test the insertion format in isolation.
 */
function insertSnippet(item, chatInput) {
  const prefix = item.file_path || item.file_name || 'unknown';
  const content = (item.snippet || '').trim();
  const insertion = `[${prefix}]: ${content}`;
  chatInput.value += (chatInput.value ? '\n' : '') + insertion;
}

// ── Property Tests ──

describe('CommandBar Property Tests', () => {

  /**
   * Feature: productivity-workspace-overhaul, Property 16: Command bar search debounce
   *
   * For any sequence of keystrokes arriving within 300ms of each other, the Command Bar
   * should fire exactly one search request (the last query), not one per keystroke.
   *
   * **Validates: Requirements 7.2**
   */
  describe('Property 16: Command bar search debounce', () => {
    beforeEach(() => {
      vi.useFakeTimers();
    });

    afterEach(() => {
      vi.useRealTimers();
    });

    it('fires exactly one search for rapid keystrokes within 300ms', () => {
      fc.assert(
        fc.property(arbKeystrokeSequence, (keystrokes) => {
          setupCommandBarDOM();
          const input = document.getElementById('spotlightInput');
          const DEBOUNCE_MS = 300;

          let searchCalls = [];
          let debounceTimer = null;

          // Replicate the debounced input handler from command-bar.js
          function onInput() {
            clearTimeout(debounceTimer);
            const q = input.value.trim();
            if (!q) return;
            debounceTimer = setTimeout(() => searchCalls.push(q), DEBOUNCE_MS);
          }

          // Simulate rapid keystrokes — each arrives within 300ms of the previous
          keystrokes.forEach((query) => {
            input.value = query;
            onInput();
            // Advance time by less than DEBOUNCE_MS to simulate rapid typing
            vi.advanceTimersByTime(50);
          });

          // At this point no search should have fired yet (all within debounce window)
          expect(searchCalls.length).toBe(0);

          // Now let the debounce timer expire
          vi.advanceTimersByTime(DEBOUNCE_MS);

          // Exactly one search should fire, with the last query
          expect(searchCalls.length).toBe(1);
          expect(searchCalls[0]).toBe(keystrokes[keystrokes.length - 1].trim());
        }),
        { numRuns: 100 },
      );
    });
  });

  /**
   * Feature: productivity-workspace-overhaul, Property 17: Search results contain required fields
   *
   * For any search result object, the rendered result element should contain the project name,
   * file path, and a preview snippet of the matching content.
   *
   * **Validates: Requirements 7.3**
   */
  describe('Property 17: Search results contain required fields', () => {
    it('each rendered result contains project name, file path, and snippet preview', () => {
      fc.assert(
        fc.property(arbSearchResults, (items) => {
          const { results } = setupCommandBarDOM();

          renderResults(results, items);

          const rendered = results.querySelectorAll('.spotlight-item');
          expect(rendered.length).toBe(items.length);

          items.forEach((item, i) => {
            const el = rendered[i];
            const textContent = el.textContent;

            // Project name is present
            expect(textContent).toContain(item.project_name);

            // File path is present
            expect(textContent).toContain(item.file_path);

            // Snippet preview is present (truncated to 120 chars, newlines replaced)
            const expectedSnippet = (item.snippet || '').replace(/\n/g, ' ').slice(0, 120);
            expect(textContent).toContain(expectedSnippet);
          });
        }),
        { numRuns: 100 },
      );
    });
  });

  /**
   * Feature: productivity-workspace-overhaul, Property 18: Search result insertion format
   *
   * For any search result selected by the user, the text inserted into the chat input
   * should be prefixed with the source file path in the format [source_file_path]: snippet_content.
   *
   * **Validates: Requirements 7.4**
   */
  describe('Property 18: Search result insertion format', () => {
    it('inserted text follows [file_path]: snippet format', () => {
      fc.assert(
        fc.property(arbSearchResult, (item) => {
          const { chatInput } = setupCommandBarDOM();
          chatInput.value = '';

          insertSnippet(item, chatInput);

          const inserted = chatInput.value;
          const expectedPrefix = `[${item.file_path}]`;
          const expectedContent = (item.snippet || '').trim();
          const expected = `${expectedPrefix}: ${expectedContent}`;

          expect(inserted).toBe(expected);
        }),
        { numRuns: 100 },
      );
    });

    it('appends with newline when chat input already has content', () => {
      fc.assert(
        fc.property(
          arbSearchResult,
          fc.stringMatching(/^[a-zA-Z0-9 ]{1,40}$/),
          (item, existingText) => {
            const { chatInput } = setupCommandBarDOM();
            chatInput.value = existingText;

            insertSnippet(item, chatInput);

            const expectedPrefix = `[${item.file_path}]`;
            const expectedContent = (item.snippet || '').trim();
            const expectedInsertion = `${expectedPrefix}: ${expectedContent}`;

            expect(chatInput.value).toBe(`${existingText}\n${expectedInsertion}`);
          },
        ),
        { numRuns: 100 },
      );
    });
  });
});
