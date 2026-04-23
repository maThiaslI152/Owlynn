/**
 * WorkspaceState centralizes active project persistence/normalization.
 * It is intentionally small and framework-free so legacy script.js can adopt it gradually.
 */
(function initWorkspaceState(global) {
  "use strict";

  const STORAGE_KEY = "active_project_id";
  const state = {
    activeProjectId: null,
  };

  function normalizeProjectId(projectId) {
    const raw = String(projectId || "").trim();
    if (!raw || raw === "null" || raw === "undefined") return "default";
    return raw;
  }

  function getActiveProjectId() {
    if (state.activeProjectId) return state.activeProjectId;
    const saved = global.localStorage ? global.localStorage.getItem(STORAGE_KEY) : null;
    return normalizeProjectId(saved || "default");
  }

  function setActiveProject(projectId, options = {}) {
    const next = normalizeProjectId(projectId);
    const persist = options.persist !== false;
    state.activeProjectId = next;
    if (persist && global.localStorage) {
      global.localStorage.setItem(STORAGE_KEY, next);
    }
    return next;
  }

  function syncFromProjects(projects, preferredProjectId) {
    const all = Array.isArray(projects) ? projects : [];
    if (all.length === 0) return setActiveProject("default");
    const valid = new Set(all.map((p) => p.id));
    const saved = global.localStorage ? global.localStorage.getItem(STORAGE_KEY) : null;
    const candidate = normalizeProjectId(preferredProjectId || state.activeProjectId || saved || "default");
    const resolved = valid.has(candidate) ? candidate : (valid.has("default") ? "default" : all[0].id);
    return setActiveProject(resolved);
  }

  function hasProjectSelected() {
    return Boolean(getActiveProjectId());
  }

  global.WorkspaceState = {
    normalizeProjectId,
    getActiveProjectId,
    setActiveProject,
    syncFromProjects,
    hasProjectSelected,
    storageKey: STORAGE_KEY,
  };
})(window);
