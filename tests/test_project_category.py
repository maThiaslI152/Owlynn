import unittest
import json
import os
import sys
import tempfile
from unittest.mock import patch
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.memory.project import ProjectManager, _DEFAULT_PROJECT


class TestProjectCategoryField(unittest.TestCase):
    """Tests for the category field on projects (Requirement 6.3)."""

    def setUp(self):
        self.pm = ProjectManager()
        self.project = self.pm.create_project("Category Test Project")

    def tearDown(self):
        if hasattr(self, 'project') and self.project:
            self.pm.delete_project(self.project["id"])

    def test_default_project_has_category(self):
        """_DEFAULT_PROJECT includes category field set to 'general'."""
        self.assertIn("category", _DEFAULT_PROJECT)
        self.assertEqual(_DEFAULT_PROJECT["category"], "general")

    def test_new_project_has_category(self):
        """Newly created projects have category='general' by default."""
        self.assertIn("category", self.project)
        self.assertEqual(self.project["category"], "general")

    def test_update_project_category(self):
        """update_project() accepts and persists category changes."""
        updated = self.pm.update_project(self.project["id"], category="cybersec")
        self.assertEqual(updated["category"], "cybersec")

        # Verify persistence by re-reading
        fetched = self.pm.get_project(self.project["id"])
        self.assertEqual(fetched["category"], "cybersec")

    def test_update_category_to_various_values(self):
        """Category can be set to any valid category string."""
        for cat in ["cybersec", "writing", "research", "development", "data", "general"]:
            updated = self.pm.update_project(self.project["id"], category=cat)
            self.assertEqual(updated["category"], cat)

    def test_migration_backfills_category(self):
        """_load_projects() backfills missing category on existing projects."""
        # Simulate a legacy project without category
        pid = self.project["id"]
        del self.pm.projects[pid]["category"]
        self.assertNotIn("category", self.pm.projects[pid])

        # Trigger migration
        self.pm._load()

        # After migration, category should be backfilled
        self.assertIn("category", self.pm.projects[pid])
        self.assertEqual(self.pm.projects[pid]["category"], "general")


if __name__ == '__main__':
    unittest.main()
