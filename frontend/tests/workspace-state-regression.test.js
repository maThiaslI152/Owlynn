import { describe, it, expect, beforeEach } from "vitest";
import "../modules/workspace-state.js";

describe("WorkspaceState regressions", () => {
  beforeEach(() => {
    localStorage.clear();
    window.WorkspaceState.setActiveProject("default");
  });

  it("keeps general workspace when no prior selection", () => {
    const projects = [
      { id: "default", name: "General Workspace" },
      { id: "test-workspace", name: "Test Workspace" },
    ];
    const active = window.WorkspaceState.syncFromProjects(projects, null);
    expect(active).toBe("default");
    expect(window.WorkspaceState.getActiveProjectId()).toBe("default");
  });

  it("restores test workspace across refresh and does not disappear", () => {
    const projects = [
      { id: "default", name: "General Workspace" },
      { id: "test-workspace", name: "Test Workspace" },
    ];
    window.WorkspaceState.setActiveProject("test-workspace");
    const active = window.WorkspaceState.syncFromProjects(projects, null);
    expect(active).toBe("test-workspace");
    expect(localStorage.getItem("active_project_id")).toBe("test-workspace");
  });

  it("falls back to default if saved project was deleted", () => {
    window.WorkspaceState.setActiveProject("test-workspace");
    const projects = [{ id: "default", name: "General Workspace" }];
    const active = window.WorkspaceState.syncFromProjects(projects, null);
    expect(active).toBe("default");
  });
});
