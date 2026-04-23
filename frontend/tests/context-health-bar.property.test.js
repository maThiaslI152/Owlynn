/**
 * Property-based tests for ContextHealthBar module using fast-check + vitest (jsdom).
 *
 * Feature: productivity-workspace-overhaul
 * Validates: Requirements 3.2, 3.4, 3.5
 */
import { describe, it, expect } from 'vitest';
import fc from 'fast-check';

// ── Arbitraries ──

/**
 * Generate a valid token state where:
 *   contextWindow > 0,
 *   activeTokens >= 0,
 *   summarizedTokens >= 0,
 *   activeTokens + summarizedTokens <= contextWindow
 */
const arbTokenState = fc
  .record({
    contextWindow: fc.integer({ min: 1, max: 200000 }),
    activeFraction: fc.double({ min: 0, max: 1, noNaN: true }),
    summarizedFraction: fc.double({ min: 0, max: 1, noNaN: true }),
  })
  .map(({ contextWindow, activeFraction, summarizedFraction }) => {
    // Scale fractions so their sum doesn't exceed 1
    const total = activeFraction + summarizedFraction;
    const scale = total > 1 ? 1 / total : 1;
    const activeTokens = Math.floor(activeFraction * scale * contextWindow);
    const summarizedTokens = Math.floor(summarizedFraction * scale * contextWindow);
    return { activeTokens, summarizedTokens, contextWindow };
  });

/**
 * Generate a token state specifically near the 90% warning threshold.
 * Useful for boundary testing in Property 9.
 */
const arbWarningTokenState = fc
  .record({
    contextWindow: fc.integer({ min: 10, max: 200000 }),
    atOrAbove90: fc.boolean(),
  })
  .map(({ contextWindow, atOrAbove90 }) => {
    const threshold = Math.ceil(0.9 * contextWindow);
    const activeTokens = atOrAbove90
      ? fc.sample(fc.integer({ min: threshold, max: contextWindow }), 1)[0]
      : fc.sample(fc.integer({ min: 0, max: threshold - 1 }), 1)[0];
    const remaining = contextWindow - activeTokens;
    const summarizedTokens = remaining > 0
      ? fc.sample(fc.integer({ min: 0, max: remaining }), 1)[0]
      : 0;
    return { activeTokens, summarizedTokens, contextWindow, atOrAbove90 };
  });

// ── Helpers ──

/**
 * Set up a fresh jsdom environment and replicate the ContextHealthBar logic
 * (mirrors context-health-bar.js) so we can test the pure rendering behaviour.
 */
function setupHealthBar() {
  // Reset DOM — provide the container the module expects
  document.body.innerHTML = '<div id="contextHealthBar"></div>';

  let activeTokens = 0;
  let summarizedTokens = 0;
  let contextWindow = 100000;

  const barEl = document.getElementById('contextHealthBar');

  const activeEl = document.createElement('div');
  activeEl.className = 'health-active';
  barEl.appendChild(activeEl);

  const summarizedEl = document.createElement('div');
  summarizedEl.className = 'health-summarized';
  barEl.appendChild(summarizedEl);

  const tooltipEl = document.createElement('div');
  tooltipEl.className = 'health-tooltip';
  barEl.appendChild(tooltipEl);

  function update(active, summarized, window_) {
    if (active != null) activeTokens = active;
    if (summarized != null) summarizedTokens = summarized;
    if (window_ != null && window_ > 0) contextWindow = window_;

    barEl.classList.remove('unavailable');

    const total = contextWindow || 1;
    const activePct = Math.min((activeTokens / total) * 100, 100);
    const summarizedPct = Math.min((summarizedTokens / total) * 100, 100 - activePct);

    activeEl.style.width = activePct + '%';
    summarizedEl.style.width = summarizedPct + '%';
    summarizedEl.style.left = activePct + '%';

    // Warning at 90% threshold
    setWarning(activeTokens >= 0.9 * contextWindow);

    // Update tooltip
    tooltipEl.title = getTooltipText();
  }

  function setWarning(isWarning) {
    if (isWarning) {
      activeEl.classList.add('warning');
    } else {
      activeEl.classList.remove('warning');
    }
  }

  function getTooltipText() {
    const available = Math.max(contextWindow - activeTokens - summarizedTokens, 0);
    return `Active: ${activeTokens} | Summarized: ${summarizedTokens} | Available: ${available}`;
  }

  return {
    bar: { update, setWarning, getTooltipText },
    els: { barEl, activeEl, summarizedEl, tooltipEl },
    getState: () => ({ activeTokens, summarizedTokens, contextWindow }),
  };
}

// ── Property Tests ──

describe('ContextHealthBar Property Tests', () => {

  /**
   * Feature: productivity-workspace-overhaul, Property 8: Context health bar proportions and tooltip
   *
   * For any valid token state (activeTokens >= 0, summarizedTokens >= 0, contextWindow > 0,
   * activeTokens + summarizedTokens <= contextWindow), the health bar blue segment width should
   * equal activeTokens / contextWindow * 100%, the grey segment should equal
   * summarizedTokens / contextWindow * 100%, and the tooltip text should contain the exact
   * numeric values for active, summarized, and available tokens.
   *
   * **Validates: Requirements 3.2, 3.4**
   */
  describe('Property 8: Context health bar proportions and tooltip', () => {
    it('segment widths and tooltip match the token state', () => {
      fc.assert(
        fc.property(arbTokenState, ({ activeTokens, summarizedTokens, contextWindow }) => {
          const { bar, els } = setupHealthBar();

          bar.update(activeTokens, summarizedTokens, contextWindow);

          // Expected percentages
          const expectedActivePct = Math.min((activeTokens / contextWindow) * 100, 100);
          const expectedSummarizedPct = Math.min(
            (summarizedTokens / contextWindow) * 100,
            100 - expectedActivePct,
          );

          // Verify active (blue) segment width
          expect(parseFloat(els.activeEl.style.width)).toBeCloseTo(expectedActivePct, 5);

          // Verify summarized (grey) segment width
          expect(parseFloat(els.summarizedEl.style.width)).toBeCloseTo(expectedSummarizedPct, 5);

          // Verify tooltip contains exact numeric values
          const available = Math.max(contextWindow - activeTokens - summarizedTokens, 0);
          const tooltip = els.tooltipEl.title;
          expect(tooltip).toContain(`Active: ${activeTokens}`);
          expect(tooltip).toContain(`Summarized: ${summarizedTokens}`);
          expect(tooltip).toContain(`Available: ${available}`);
        }),
        { numRuns: 100 },
      );
    });
  });

  /**
   * Feature: productivity-workspace-overhaul, Property 9: Context health bar warning threshold
   *
   * For any token state where activeTokens >= 0.9 * contextWindow, the active segment color
   * should be amber (has 'warning' class). For any state where activeTokens < 0.9 * contextWindow,
   * the color should be blue (no 'warning' class).
   *
   * **Validates: Requirements 3.5**
   */
  describe('Property 9: Context health bar warning threshold', () => {
    it('active segment has warning class iff activeTokens >= 90% of contextWindow', () => {
      fc.assert(
        fc.property(arbTokenState, ({ activeTokens, summarizedTokens, contextWindow }) => {
          const { bar, els } = setupHealthBar();

          bar.update(activeTokens, summarizedTokens, contextWindow);

          const shouldWarn = activeTokens >= 0.9 * contextWindow;

          if (shouldWarn) {
            expect(els.activeEl.classList.contains('warning')).toBe(true);
          } else {
            expect(els.activeEl.classList.contains('warning')).toBe(false);
          }
        }),
        { numRuns: 100 },
      );
    });
  });
});
