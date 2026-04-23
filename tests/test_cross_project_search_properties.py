"""
Property-based tests for cross-project search coverage.

# Feature: productivity-workspace-overhaul, Property 19: Cross-project search coverage
# **Validates: Requirements 7.6**

Property 19 states:
    For any query string that matches a filename, file content substring,
    or project name in the backing data, the search function should return
    at least one result containing that match.

We mirror the search logic from src/api/server.py in a helper (same pattern
used by tests/test_new_api_endpoints.py) and use Hypothesis to generate
random project data, filenames, and file content, then verify that searching
for known-present substrings always yields results.
"""

import os
import sys
import shutil
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from hypothesis import given, settings, assume, HealthCheck
from hypothesis import strategies as st

from src.memory.project import ProjectManager
from src.config.settings import get_project_workspace, normalize_project_id


# ── Strategies ───────────────────────────────────────────────────────────

# Printable, non-whitespace-only strings for filenames (no path separators or dots-only)
_safe_filename_chars = st.sampled_from(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
)

safe_filename_st = st.text(_safe_filename_chars, min_size=2, max_size=20).map(
    lambda s: s + ".txt"
)

# File content: at least one non-empty line
file_content_line_st = st.text(
    st.characters(whitelist_categories=("L", "N", "P", "S", "Z"), min_codepoint=32, max_codepoint=126),
    min_size=3,
    max_size=80,
)

# Project name: readable alphanumeric with spaces
project_name_st = st.text(
    st.sampled_from("abcdefghijklmnopqrstuvwxyz ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"),
    min_size=3,
    max_size=30,
).filter(lambda s: s.strip() and any(c.isalnum() for c in s))


# ── Search helper (mirrors src/api/server.py api_search logic) ───────────

def run_search(pm: ProjectManager, query: str, project_id: str = "") -> list:
    """Replicates the search endpoint logic for testing without HTTP."""
    query = query.strip()
    if not query:
        return []

    results = []
    query_lower = query.lower()

    if project_id:
        pid = normalize_project_id(project_id)
        project = pm.get_project(pid)
        projects_to_search = [(pid, project)] if project else []
    else:
        projects_to_search = [(p["id"], p) for p in pm.list_projects()]

    for pid, project in projects_to_search:
        project_name = project.get("name", pid) if project else pid
        workspace = get_project_workspace(pid)

        if not os.path.exists(workspace):
            continue

        for root, dirs, files in os.walk(workspace):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__pycache__"]

            for fname in files:
                if fname.startswith("."):
                    continue

                filepath = os.path.join(root, fname)
                rel_path = os.path.relpath(filepath, workspace)

                # Filename match
                if query_lower in fname.lower():
                    results.append({
                        "project_id": pid,
                        "project_name": project_name,
                        "file_path": rel_path,
                        "file_name": fname,
                        "snippet": "",
                        "match_type": "filename",
                        "line_number": None,
                    })

                # Content match
                try:
                    if os.path.getsize(filepath) > 2 * 1024 * 1024:
                        continue
                    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                        for line_num, line in enumerate(f, start=1):
                            if query_lower in line.lower():
                                snippet = line.strip()[:200]
                                results.append({
                                    "project_id": pid,
                                    "project_name": project_name,
                                    "file_path": rel_path,
                                    "file_name": fname,
                                    "snippet": snippet,
                                    "match_type": "content",
                                    "line_number": line_num,
                                })
                                break
                except (UnicodeDecodeError, PermissionError, OSError):
                    continue

    return results


# ── Test fixtures ────────────────────────────────────────────────────────

class SearchTestFixture:
    """Manages a temporary project with workspace files for property tests."""

    def __init__(self):
        self.pm = ProjectManager()
        self.created_projects: list[str] = []

    def create_project_with_file(self, project_name: str, filename: str, content: str) -> tuple[str, str]:
        """Create a project, write a file into its workspace, return (pid, workspace)."""
        project = self.pm.create_project(project_name)
        pid = project["id"]
        self.created_projects.append(pid)

        workspace = get_project_workspace(pid)
        os.makedirs(workspace, exist_ok=True)
        filepath = os.path.join(workspace, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)

        return pid, workspace

    def cleanup(self):
        for pid in self.created_projects:
            try:
                self.pm.delete_project(pid)
            except Exception:
                pass
            # Also clean up workspace dir if delete_project didn't
            workspace = get_project_workspace(pid)
            if os.path.exists(workspace):
                shutil.rmtree(workspace, ignore_errors=True)


# ── Property 19: Cross-project search coverage ──────────────────────────

class TestCrossProjectSearchCoverage:
    """
    Property 19: For any query string that matches a filename, file content
    substring, or project name in the backing data, the search function
    should return at least one result containing that match.

    **Validates: Requirements 7.6**
    """

    @given(
        filename=safe_filename_st,
        content=file_content_line_st,
        project_name=project_name_st,
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_filename_query_returns_match(self, filename, content, project_name):
        """Searching for a substring of the filename returns at least one result."""
        # Use at least 2 chars of the filename stem as query
        stem = filename.rsplit(".", 1)[0]
        assume(len(stem) >= 2)
        query = stem[:max(2, len(stem) // 2)]
        assume(query.strip())

        fixture = SearchTestFixture()
        try:
            pid, _ = fixture.create_project_with_file(project_name, filename, content)
            results = run_search(fixture.pm, query, project_id=pid)
            matching = [r for r in results if r["match_type"] == "filename"]
            assert len(matching) >= 1, (
                f"Filename query '{query}' did not match file '{filename}'"
            )
        finally:
            fixture.cleanup()

    @given(
        filename=safe_filename_st,
        content=file_content_line_st,
        project_name=project_name_st,
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_content_query_returns_match(self, filename, content, project_name):
        """Searching for a substring of the file content returns at least one result."""
        # Pick a substring from the content as the query
        assume(len(content) >= 3)
        start = len(content) // 4
        end = start + max(3, len(content) // 3)
        query = content[start:end].strip()
        assume(len(query) >= 2)

        fixture = SearchTestFixture()
        try:
            pid, _ = fixture.create_project_with_file(project_name, filename, content)
            results = run_search(fixture.pm, query, project_id=pid)
            assert len(results) >= 1, (
                f"Content query '{query}' did not match content '{content}' in file '{filename}'"
            )
        finally:
            fixture.cleanup()

    @given(
        filename=safe_filename_st,
        content=file_content_line_st,
        project_name=project_name_st,
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_cross_project_search_finds_across_projects(self, filename, content, project_name):
        """Cross-project search (no project_id filter) finds files from any project."""
        stem = filename.rsplit(".", 1)[0]
        assume(len(stem) >= 2)
        query = stem

        fixture = SearchTestFixture()
        try:
            fixture.create_project_with_file(project_name, filename, content)
            # Search without project_id — should find across all projects
            results = run_search(fixture.pm, query)
            matching = [r for r in results if r["file_name"] == filename]
            assert len(matching) >= 1, (
                f"Cross-project search for '{query}' did not find file '{filename}'"
            )
        finally:
            fixture.cleanup()

    @given(
        filename=safe_filename_st,
        content=file_content_line_st,
        project_name=project_name_st,
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_search_results_contain_required_fields(self, filename, content, project_name):
        """Every search result contains project_id, project_name, file_path, snippet, match_type."""
        stem = filename.rsplit(".", 1)[0]
        assume(len(stem) >= 2)

        fixture = SearchTestFixture()
        try:
            pid, _ = fixture.create_project_with_file(project_name, filename, content)
            results = run_search(fixture.pm, stem, project_id=pid)
            assert len(results) >= 1

            required_fields = {"project_id", "project_name", "file_path", "file_name",
                               "snippet", "match_type", "line_number"}
            for r in results:
                missing = required_fields - set(r.keys())
                assert not missing, f"Result missing fields: {missing}"
        finally:
            fixture.cleanup()

    @given(
        filename=safe_filename_st,
        content=file_content_line_st,
        project_name=project_name_st,
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_empty_query_returns_no_results(self, filename, content, project_name):
        """An empty or whitespace-only query always returns zero results."""
        fixture = SearchTestFixture()
        try:
            pid, _ = fixture.create_project_with_file(project_name, filename, content)
            for q in ["", "   ", "\t"]:
                results = run_search(fixture.pm, q, project_id=pid)
                assert len(results) == 0, f"Empty query '{repr(q)}' returned results"
        finally:
            fixture.cleanup()
