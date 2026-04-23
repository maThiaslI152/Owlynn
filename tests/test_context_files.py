"""
Tests for context file loading in WebSocket payload handling (task 1.3).

Tests the helper functions:
- _load_context_file_content()
- build_context_files_prompt()

Requirements: 8.6, 2.2, 2.3
"""

import unittest
import os
import sys
import tempfile
import shutil

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.api.server import (
    _load_context_file_content,
    build_context_files_prompt,
    _CONTEXT_FILE_MAX_BYTES,
    _CONTEXT_TOTAL_MAX_BYTES,
)


class TestLoadContextFileContent(unittest.TestCase):
    """Tests for _load_context_file_content()."""

    def setUp(self):
        self.workspace = tempfile.mkdtemp()
        self.processed_dir = os.path.join(self.workspace, ".processed")
        os.makedirs(self.processed_dir, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.workspace)

    def test_reads_processed_txt_cache(self):
        """Processed .txt cache is preferred over raw file."""
        # Create both raw and processed
        with open(os.path.join(self.workspace, "notes.md"), "w") as f:
            f.write("raw content")
        with open(os.path.join(self.processed_dir, "notes.md.txt"), "w") as f:
            f.write("processed content")

        result = _load_context_file_content(self.workspace, "notes.md")
        self.assertEqual(result, "processed content")

    def test_reads_processed_md_cache(self):
        """Processed .md cache is used when .txt doesn't exist."""
        with open(os.path.join(self.processed_dir, "data.csv.md"), "w") as f:
            f.write("markdown processed")

        result = _load_context_file_content(self.workspace, "data.csv")
        self.assertEqual(result, "markdown processed")

    def test_falls_back_to_raw_file(self):
        """Raw file is read when no processed cache exists."""
        with open(os.path.join(self.workspace, "script.py"), "w") as f:
            f.write("print('hello')")

        result = _load_context_file_content(self.workspace, "script.py")
        self.assertEqual(result, "print('hello')")

    def test_returns_none_for_missing_file(self):
        """Returns None when file doesn't exist anywhere."""
        result = _load_context_file_content(self.workspace, "nonexistent.txt")
        self.assertIsNone(result)

    def test_truncates_oversized_file(self):
        """Files exceeding 50KB are truncated with a notice."""
        large_content = "x" * (_CONTEXT_FILE_MAX_BYTES + 500)
        with open(os.path.join(self.workspace, "big.txt"), "w") as f:
            f.write(large_content)

        result = _load_context_file_content(self.workspace, "big.txt")
        self.assertIn("[… truncated", result)
        # Content before truncation marker should be exactly the limit
        self.assertTrue(result.startswith("x" * _CONTEXT_FILE_MAX_BYTES))

    def test_rejects_path_traversal(self):
        """Paths containing '..' are rejected."""
        result = _load_context_file_content(self.workspace, "../etc/passwd")
        self.assertIsNone(result)

    def test_rejects_path_escaping_workspace(self):
        """Absolute-ish paths that escape workspace are rejected."""
        result = _load_context_file_content(self.workspace, "/etc/passwd")
        # Leading slash is stripped, so this becomes "etc/passwd" which won't exist
        self.assertIsNone(result)

    def test_reads_file_in_subdirectory(self):
        """Files in subdirectories can be read via raw fallback."""
        subdir = os.path.join(self.workspace, "src")
        os.makedirs(subdir)
        with open(os.path.join(subdir, "main.py"), "w") as f:
            f.write("import os")

        result = _load_context_file_content(self.workspace, "src/main.py")
        self.assertEqual(result, "import os")


class TestBuildContextFilesPrompt(unittest.TestCase):
    """Tests for build_context_files_prompt()."""

    def setUp(self):
        self.workspace = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.workspace)

    def test_empty_list_returns_empty_string(self):
        result = build_context_files_prompt(self.workspace, [])
        self.assertEqual(result, "")

    def test_single_file_produces_prompt(self):
        with open(os.path.join(self.workspace, "readme.md"), "w") as f:
            f.write("# Hello")

        result = build_context_files_prompt(self.workspace, ["readme.md"])
        self.assertIn("### File: readme.md", result)
        self.assertIn("# Hello", result)
        self.assertIn("loaded the following project files", result)

    def test_multiple_files_all_included(self):
        for name, content in [("a.py", "print(1)"), ("b.py", "print(2)")]:
            with open(os.path.join(self.workspace, name), "w") as f:
                f.write(content)

        result = build_context_files_prompt(self.workspace, ["a.py", "b.py"])
        self.assertIn("### File: a.py", result)
        self.assertIn("### File: b.py", result)

    def test_missing_files_skipped(self):
        with open(os.path.join(self.workspace, "exists.py"), "w") as f:
            f.write("ok")

        result = build_context_files_prompt(self.workspace, ["exists.py", "missing.py"])
        self.assertIn("### File: exists.py", result)
        self.assertNotIn("missing.py", result)

    def test_total_limit_enforced(self):
        """When total content exceeds 200KB, later files are truncated or skipped."""
        # Create files that together exceed the total limit
        file_count = 6  # 6 * 50KB = 300KB > 200KB limit
        for i in range(file_count):
            name = f"file{i}.txt"
            with open(os.path.join(self.workspace, name), "w") as f:
                f.write("a" * (_CONTEXT_FILE_MAX_BYTES - 100))

        paths = [f"file{i}.txt" for i in range(file_count)]
        result = build_context_files_prompt(self.workspace, paths)

        # Should contain some files but not all (total limit kicks in)
        included = sum(1 for i in range(file_count) if f"### File: file{i}.txt" in result)
        self.assertGreater(included, 0)
        self.assertLess(included, file_count)

    def test_skips_empty_and_non_string_entries(self):
        with open(os.path.join(self.workspace, "ok.txt"), "w") as f:
            f.write("content")

        result = build_context_files_prompt(self.workspace, ["", None, 123, "ok.txt"])
        self.assertIn("### File: ok.txt", result)

    def test_all_missing_returns_empty(self):
        result = build_context_files_prompt(self.workspace, ["nope.txt", "also_nope.py"])
        self.assertEqual(result, "")


if __name__ == "__main__":
    unittest.main()
