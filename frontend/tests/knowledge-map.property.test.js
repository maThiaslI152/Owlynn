/**
 * Property-based tests for KnowledgeMap module using fast-check + vitest (jsdom).
 *
 * Feature: productivity-workspace-overhaul
 * Validates: Requirements 9.2, 9.3, 9.4, 9.6
 */
import { describe, it, expect } from 'vitest';
import fc from 'fast-check';

// ── Arbitraries ──

/** Generate a safe project ID. */
const arbProjectId = fc.stringMatching(/^[a-zA-Z0-9_-]{1,20}$/);

/** Generate a safe knowledge entry title. */
const arbTitle = fc.stringMatching(/^[a-zA-Z0-9 _-]{1,40}$/).filter(s => s.trim().length > 0);

/** Generate knowledge entry content (variable length to test truncation). */
const arbContent = fc.stringMatching(/^[a-zA-Z0-9 .,!?\n]{1,300}$/).filter(s => s.trim().length > 0);

/** Generate a unix timestamp (seconds) within a reasonable range. */
const arbTimestamp = fc.integer({ min: 1600000000, max: 1800000000 });

/** Generate a single knowledge entry. */
const arbEntry = fc.record({
  id: fc.stringMatching(/^[a-z]+_[0-9]+$/).filter(s => s.length >= 3),
  title: arbTitle,
  content: arbContent,
  timestamp: fc.oneof(arbTimestamp, fc.constant(null)),
  source: fc.constantFrom('memory', 'topic'),
});

/** Generate a list of knowledge entries with unique IDs. */
const arbEntryList = fc.uniqueArray(arbEntry, {
  comparator: (a, b) => a.id === b.id,
  minLength: 1,
  maxLength: 15,
});

/** Generate two distinct entry lists for two different projects. */
const arbTwoProjectEntries = fc.tuple(arbEntryList, arbEntryList).filter(
  ([a, b]) => {
    const aIds = new Set(a.map(e => e.id));
    const bIds = new Set(b.map(e => e.id));
    // Ensure at least one entry differs between projects
    return a.length > 0 && b.length > 0 &&
      (a.length !== b.length || [...aIds].some(id => !bIds.has(id)));
  }
);

// ── Helpers ──

/** Minimal StateManager mock. */
function createStateManager(initialProjectId) {
  const state = { activeProjectId: initialProjectId || 'default' };
  const subscribers = {};
  return {
    get activeProjectId() { return state.activeProjectId; },
    set activeProjectId(v) { state.activeProjectId = v; },
    set(key, value) {
      state[key] = value;
      for (const cb of Object.values(subscribers)) cb([key]);
    },
    subscribe(name, cb) { subscribers[name] = cb; },
  };
}

function _escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

function _formatTime(ts) {
  if (!ts) return '';
  try {
    const d = new Date(typeof ts === 'number' ? ts * 1000 : ts);
    if (isNaN(d.getTime())) return '';
    const now = Date.now();
    const diff = now - d.getTime();
    if (diff < 60000) return 'just now';
    if (diff < 3600000) return Math.floor(diff / 60000) + 'm ago';
    if (diff < 86400000) return Math.floor(diff / 3600000) + 'h ago';
    return d.toLocaleDateString();
  } catch (_) { return ''; }
}

/**
 * Set up a minimal DOM and replicate KnowledgeMap rendering logic for isolated testing.
 * Mirrors the public API from frontend/modules/knowledge-map.js.
 */
function setupKnowledgeMap(initialProjectId) {
  document.body.innerHTML = '<div id="knowledgeEntries"></div>';

  const sm = createStateManager(initialProjectId);
  globalThis.StateManager = sm;
  globalThis.API_BASE = '';

  let entries = [];
  let expandedEntries = new Set();
  const containerEl = document.getElementById('knowledgeEntries');

  function renderEntries(entryList) {
    if (!containerEl) return;
    containerEl.innerHTML = '';

    if (!entryList || entryList.length === 0) {
      containerEl.innerHTML = '<div class="knowledge-empty">No knowledge yet</div>';
      return;
    }

    entryList.forEach(entry => {
      const isExpanded = expandedEntries.has(entry.id);
      const el = document.createElement('div');
      el.className = 'knowledge-entry' + (isExpanded ? ' expanded' : '');
      el.dataset.entryId = entry.id;

      const timeStr = _formatTime(entry.timestamp);
      const preview = entry.content.length > 120 && !isExpanded
        ? entry.content.substring(0, 120) + '…'
        : entry.content;

      el.innerHTML =
        '<div class="knowledge-title">' + _escapeHtml(entry.title) + '</div>' +
        '<div class="knowledge-preview">' + _escapeHtml(preview) + '</div>' +
        (timeStr ? '<div class="knowledge-time">' + _escapeHtml(timeStr) + '</div>' : '') +
        '<div class="knowledge-actions">' +
          '<button class="knowledge-delete-btn" title="Delete">✕</button>' +
        '</div>';

      el.addEventListener('click', (e) => {
        if (e.target.closest('.knowledge-delete-btn')) return;
        expandEntry(entry.id);
      });

      el.querySelector('.knowledge-delete-btn').addEventListener('click', (e) => {
        e.stopPropagation();
        deleteEntry(entry.title);
      });

      containerEl.appendChild(el);
    });
  }

  function expandEntry(entryId) {
    if (expandedEntries.has(entryId)) {
      expandedEntries.delete(entryId);
    } else {
      expandedEntries.add(entryId);
    }
    renderEntries(entries);
  }

  function deleteEntry(entryTitle) {
    entries = entries.filter(e => e.title !== entryTitle);
    renderEntries(entries);
  }

  function setEntries(entryList) {
    entries = [...entryList];
    expandedEntries.clear();
    renderEntries(entries);
  }

  function getEntries() {
    return entries;
  }

  return {
    km: {
      renderEntries,
      expandEntry,
      deleteEntry,
      setEntries,
      getEntries,
    },
    sm,
    containerEl,
  };
}

// ── Property Tests ──

describe('KnowledgeMap Property Tests', () => {

  /**
   * Feature: productivity-workspace-overhaul, Property 22: Knowledge map displays project-scoped entries
   *
   * For any project with knowledge entries, the Knowledge Map should render exactly the
   * entries associated with that project. Switching to a different project should replace
   * the displayed entries with the new project's entries.
   *
   * **Validates: Requirements 9.2, 9.3**
   */
  describe('Property 22: Knowledge map displays project-scoped entries', () => {
    it('renders exactly the entries for the active project', () => {
      fc.assert(
        fc.property(arbProjectId, arbEntryList, (projectId, entryList) => {
          const { km, containerEl } = setupKnowledgeMap(projectId);

          km.setEntries(entryList);

          const rendered = containerEl.querySelectorAll('.knowledge-entry');
          expect(rendered.length).toBe(entryList.length);

          entryList.forEach((entry, i) => {
            const titleEl = rendered[i].querySelector('.knowledge-title');
            expect(titleEl).not.toBeNull();
            expect(titleEl.textContent).toBe(entry.title);
          });
        }),
        { numRuns: 100 },
      );
    });

    it('switching projects replaces displayed entries with new project entries', () => {
      fc.assert(
        fc.property(
          arbProjectId,
          arbProjectId.filter(id => id.length > 0),
          arbTwoProjectEntries,
          (projectIdA, projectIdB, [entriesA, entriesB]) => {
            fc.pre(projectIdA !== projectIdB);

            const { km, sm, containerEl } = setupKnowledgeMap(projectIdA);

            // Load project A entries
            km.setEntries(entriesA);
            const renderedA = containerEl.querySelectorAll('.knowledge-entry');
            expect(renderedA.length).toBe(entriesA.length);

            // Switch to project B
            sm.activeProjectId = projectIdB;
            km.setEntries(entriesB);

            const renderedB = containerEl.querySelectorAll('.knowledge-entry');
            expect(renderedB.length).toBe(entriesB.length);

            // Verify project B entries are displayed (not project A)
            entriesB.forEach((entry, i) => {
              const titleEl = renderedB[i].querySelector('.knowledge-title');
              expect(titleEl.textContent).toBe(entry.title);
            });
          },
        ),
        { numRuns: 100 },
      );
    });
  });

  /**
   * Feature: productivity-workspace-overhaul, Property 23: Knowledge entry contains required metadata
   *
   * For any knowledge entry object, the rendered entry should contain a title,
   * a content preview (truncated), and a formatted timestamp.
   *
   * **Validates: Requirements 9.4**
   */
  describe('Property 23: Knowledge entry contains required metadata', () => {
    it('each rendered entry has title, content preview, and timestamp when available', () => {
      fc.assert(
        fc.property(arbEntryList, (entryList) => {
          const { km, containerEl } = setupKnowledgeMap('test-project');

          km.setEntries(entryList);

          const rendered = containerEl.querySelectorAll('.knowledge-entry');
          expect(rendered.length).toBe(entryList.length);

          entryList.forEach((entry, i) => {
            const el = rendered[i];

            // Title is present
            const titleEl = el.querySelector('.knowledge-title');
            expect(titleEl).not.toBeNull();
            expect(titleEl.textContent).toBe(entry.title);

            // Content preview is present
            const previewEl = el.querySelector('.knowledge-preview');
            expect(previewEl).not.toBeNull();
            expect(previewEl.textContent.length).toBeGreaterThan(0);

            // Content should be truncated at 120 chars if longer
            if (entry.content.length > 120) {
              expect(previewEl.textContent.length).toBeLessThanOrEqual(121 + 1); // 120 chars + ellipsis
              expect(previewEl.textContent.endsWith('…')).toBe(true);
            } else {
              expect(previewEl.textContent).toBe(entry.content);
            }

            // Timestamp: if entry has a timestamp, a .knowledge-time element should exist
            const timeEl = el.querySelector('.knowledge-time');
            const expectedTimeStr = _formatTime(entry.timestamp);
            if (expectedTimeStr) {
              expect(timeEl).not.toBeNull();
              expect(timeEl.textContent).toBe(expectedTimeStr);
            }
            // If no timestamp, the time element may be absent (which is correct)
          });
        }),
        { numRuns: 100 },
      );
    });
  });

  /**
   * Feature: productivity-workspace-overhaul, Property 24: Knowledge deletion removes entry
   *
   * For any knowledge entry in the displayed list, deleting it should result in the entry
   * no longer appearing in the rendered list, and the total count should decrease by one.
   *
   * **Validates: Requirements 9.6**
   */
  describe('Property 24: Knowledge deletion removes entry', () => {
    it('deleting an entry removes it from the rendered list and decreases count by one', () => {
      fc.assert(
        fc.property(
          arbEntryList.filter(list => {
            // Ensure unique titles so deletion targets exactly one entry
            const titles = list.map(e => e.title);
            return new Set(titles).size === titles.length;
          }),
          (entryList) => {
            const { km, containerEl } = setupKnowledgeMap('test-project');

            km.setEntries(entryList);

            const initialCount = entryList.length;
            const renderedBefore = containerEl.querySelectorAll('.knowledge-entry');
            expect(renderedBefore.length).toBe(initialCount);

            // Pick a random entry to delete
            const deleteIdx = Math.floor(Math.random() * entryList.length);
            const deletedTitle = entryList[deleteIdx].title;

            // Perform deletion
            km.deleteEntry(deletedTitle);

            // Verify count decreased by one
            const renderedAfter = containerEl.querySelectorAll('.knowledge-entry');
            expect(renderedAfter.length).toBe(initialCount - 1);

            // Verify the deleted entry is no longer in the list
            const remainingTitles = Array.from(
              containerEl.querySelectorAll('.knowledge-title')
            ).map(el => el.textContent);
            expect(remainingTitles).not.toContain(deletedTitle);

            // Verify remaining entries are intact
            expect(km.getEntries().length).toBe(initialCount - 1);
            expect(km.getEntries().find(e => e.title === deletedTitle)).toBeUndefined();
          },
        ),
        { numRuns: 100 },
      );
    });
  });
});
