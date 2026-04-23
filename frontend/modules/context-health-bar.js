/**
 * ContextHealthBar — IIFE module for the context window usage indicator.
 * Renders a slim horizontal bar at the top of the chat area showing
 * active (blue) vs summarized (grey) token usage.
 *
 * Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6
 */
window.ContextHealthBar = (() => {
  // ── State ──
  let activeTokens = 0;
  let summarizedTokens = 0;
  let contextWindow = 100000; // default Medium_Default

  let barEl = null;
  let activeEl = null;
  let summarizedEl = null;
  let tooltipEl = null;

  // ── Rendering ──
  function _ensureDOM() {
    barEl = document.getElementById('contextHealthBar');
    if (!barEl) return false;

    if (!activeEl) {
      activeEl = document.createElement('div');
      activeEl.className = 'health-active';
      barEl.appendChild(activeEl);
    }
    if (!summarizedEl) {
      summarizedEl = document.createElement('div');
      summarizedEl.className = 'health-summarized';
      barEl.appendChild(summarizedEl);
    }
    if (!tooltipEl) {
      tooltipEl = document.createElement('div');
      tooltipEl.className = 'health-tooltip';
      tooltipEl.title = getTooltipText();
      barEl.appendChild(tooltipEl);
    }
    return true;
  }

  function update(active, summarized, window_) {
    if (active != null) activeTokens = active;
    if (summarized != null) summarizedTokens = summarized;
    if (window_ != null && window_ > 0) contextWindow = window_;

    if (!_ensureDOM()) return;

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
    if (tooltipEl) tooltipEl.title = getTooltipText();
  }

  function setWarning(isWarning) {
    if (!activeEl) return;
    if (isWarning) {
      activeEl.classList.add('warning');
    } else {
      activeEl.classList.remove('warning');
    }
  }

  function setUnavailable() {
    if (!_ensureDOM()) return;
    barEl.classList.add('unavailable');
    if (tooltipEl) tooltipEl.title = 'Context status unavailable';
  }

  function getTooltipText() {
    const available = Math.max(contextWindow - activeTokens - summarizedTokens, 0);
    return `Active: ${activeTokens} | Summarized: ${summarizedTokens} | Available: ${available}`;
  }

  // ── Init ──
  function init() {
    if (!_ensureDOM()) {
      return;
    }

    StateManager.subscribe('ContextHealthBar', (changedKeys) => {
      if (changedKeys.includes('connectionStatus')) {
        if (StateManager.connectionStatus === 'offline') {
          setUnavailable();
        }
      }
    });
  }

  // ── Public API ──
  return { init, update, setWarning, setUnavailable, getTooltipText };
})();
