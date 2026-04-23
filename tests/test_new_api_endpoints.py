"""
Tests for new API endpoints added in task 1.2:
- PUT /api/projects/{project_id} (update project fields)
- DELETE /api/projects/{project_id}/knowledge/{name}
- GET /api/search?q={query}&project_id={optional}

Requirements: 6.3, 9.6, 7.6
"""

import unittest
import os
import sys
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.memory.project import ProjectManager


class TestUpdateProjectEndpoint(unittest.TestCase):
    """Tests for PUT /api/projects/{project_id} logic (Requirement 6.3)."""

    def setUp(self):
        self.pm = ProjectManager()
        self.project = self.pm.create_project("Update Test Project")

    def tearDown(self):
        if hasattr(self, 'project') and self.project:
            self.pm.delete_project(self.project["id"])

    def test_update_category(self):
        """Updating category via update_project persists correctly."""
        updated = self.pm.update_project(self.project["id"], category="cybersec")
        self.assertIsNotNone(updated)
        self.assertEqual(updated["category"], "cybersec")

    def test_update_name(self):
        """Updating name via update_project persists correctly."""
        updated = self.pm.update_project(self.project["id"], name="Renamed Project")
        self.assertIsNotNone(updated)
        self.assertEqual(updated["name"], "Renamed Project")

    def test_update_multiple_fields(self):
        """Updating multiple fields at once works."""
        updated = self.pm.update_project(
            self.project["id"], name="Multi Update", category="research"
        )
        self.assertEqual(updated["name"], "Multi Update")
        self.assertEqual(updated["category"], "research")

    def test_update_nonexistent_project_returns_none(self):
        """Updating a non-existent project returns None."""
        result = self.pm.update_project("nonexistent_id", category="writing")
        self.assertIsNone(result)

    def test_update_ignores_unknown_fields(self):
        """Fields not in the project schema are ignored."""
        updated = self.pm.update_project(self.project["id"], unknown_field="value")
        self.assertNotIn("unknown_field", updated)


class TestDeleteKnowledgeEndpoint(unittest.TestCase):
    """Tests for DELETE /api/projects/{project_id}/knowledge/{name} logic (Requirement 9.6)."""

    def setUp(self):
        self.pm = ProjectManager()
        self.project = self.pm.create_project("Knowledge Test Project")
        # Add a knowledge file entry to the project
        self.pm.add_file_to_project(self.project["id"], {
            "name": "test_doc.md",
            "type": "knowledge",
            "added_at": 1700000000,
        })

    def tearDown(self):
        if hasattr(self, 'project') and self.project:
            self.pm.delete_project(self.project["id"])

    def test_remove_knowledge_removes_from_files(self):
        """remove_knowledge removes the entry from the project's files list."""
        project = self.pm.get_project(self.project["id"])
        self.assertEqual(len(project["files"]), 1)

        self.pm.remove_knowledge(self.project["id"], "test_doc.md")

        project = self.pm.get_project(self.project["id"])
        self.assertEqual(len(project["files"]), 0)

    def test_remove_knowledge_nonexistent_name_is_safe(self):
        """Removing a knowledge entry that doesn't exist doesn't error."""
        self.pm.remove_knowledge(self.project["id"], "nonexistent.md")
        project = self.pm.get_project(self.project["id"])
        # Original file should still be there
        self.assertEqual(len(project["files"]), 1)

    def test_remove_knowledge_nonexistent_project_is_safe(self):
        """Removing knowledge from a non-existent project doesn't error."""
        # Should not raise
        self.pm.remove_knowledge("nonexistent_project", "test_doc.md")


class TestSearchEndpoint(unittest.TestCase):
    """Tests for GET /api/search logic (Requirement 7.6)."""

    def setUp(self):
        self.pm = ProjectManager()
        self.project = self.pm.create_project("Search Test Project")
        self.pid = self.project["id"]

        # Create workspace files for searching
        from src.config.settings import get_project_workspace
        self.workspace = get_project_workspace(self.pid)
        os.makedirs(self.workspace, exist_ok=True)

        # Create test files
        with open(os.path.join(self.workspace, "hello.py"), "w") as f:
            f.write("def hello_world():\n    print('Hello, World!')\n")

        with open(os.path.join(self.workspace, "readme.md"), "w") as f:
            f.write("# My Project\nThis is a test project for searching.\n")

        subdir = os.path.join(self.workspace, "src")
        os.makedirs(subdir, exist_ok=True)
        with open(os.path.join(subdir, "utils.py"), "w") as f:
            f.write("def calculate_sum(a, b):\n    return a + b\n")

    def tearDown(self):
        if hasattr(self, 'project') and self.project:
            self.pm.delete_project(self.project["id"])

    def test_search_by_filename(self):
        """Search matches filenames case-insensitively."""
        results = self._run_search("hello", self.pid)
        filenames = [r["file_name"] for r in results]
        self.assertIn("hello.py", filenames)

    def test_search_by_content(self):
        """Search matches file content."""
        results = self._run_search("calculate_sum", self.pid)
        matches = [r for r in results if r["match_type"] == "content"]
        self.assertTrue(len(matches) > 0)
        self.assertEqual(matches[0]["file_name"], "utils.py")

    def test_search_returns_required_fields(self):
        """Each result contains project_id, project_name, file_path, snippet, match_type."""
        results = self._run_search("hello", self.pid)
        self.assertTrue(len(results) > 0)
        for r in results:
            self.assertIn("project_id", r)
            self.assertIn("project_name", r)
            self.assertIn("file_path", r)
            self.assertIn("snippet", r)
            self.assertIn("match_type", r)

    def test_search_empty_query_returns_empty(self):
        """Empty query returns no results."""
        results = self._run_search("", self.pid)
        self.assertEqual(len(results), 0)

    def test_search_no_match_returns_empty(self):
        """Query with no matches returns empty results."""
        results = self._run_search("zzz_nonexistent_zzz", self.pid)
        self.assertEqual(len(results), 0)

    def test_search_across_subdirectories(self):
        """Search finds files in subdirectories."""
        results = self._run_search("utils", self.pid)
        file_paths = [r["file_path"] for r in results]
        matching = [p for p in file_paths if "utils" in p]
        self.assertTrue(len(matching) > 0)

    def test_search_skips_hidden_files(self):
        """Hidden files (starting with .) are not searched."""
        hidden_path = os.path.join(self.workspace, ".hidden_file.txt")
        with open(hidden_path, "w") as f:
            f.write("secret content\n")

        results = self._run_search(".hidden_file", self.pid)
        filenames = [r["file_name"] for r in results]
        self.assertNotIn(".hidden_file.txt", filenames)

    def _run_search(self, query: str, project_id: str = "") -> list:
        """Helper that mimics the search endpoint logic."""
        from src.config.settings import get_project_workspace, normalize_project_id

        query = query.strip()
        if not query:
            return []

        results = []
        query_lower = query.lower()

        if project_id:
            pid = normalize_project_id(project_id)
            project = self.pm.get_project(pid)
            projects_to_search = [(pid, project)] if project else []
        else:
            projects_to_search = [
                (p["id"], p) for p in self.pm.list_projects()
            ]

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


if __name__ == '__main__':
    unittest.main()
