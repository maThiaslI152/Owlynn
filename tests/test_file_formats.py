"""
Test suite for extended file format processing.
Tests all newly supported file formats.
"""

import os
import json
import tempfile
import shutil
from pathlib import Path

# Add src to path
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from api.file_processor import FileWatcherHandler


def create_test_file(temp_dir, filename, content):
    """Helper to create test files."""
    filepath = os.path.join(temp_dir, filename)
    if isinstance(content, bytes):
        with open(filepath, 'wb') as f:
            f.write(content)
    else:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
    return filepath


def test_json_processing():
    """Test JSON file processing."""
    print("\n=== Testing JSON Processing ===")
    with tempfile.TemporaryDirectory() as temp_dir:
        json_content = {
            "name": "Test App",
            "version": "1.0.0",
            "features": ["api", "cli", "web"]
        }
        filepath = create_test_file(temp_dir, "config.json", json.dumps(json_content))
        
        handler = FileWatcherHandler(temp_dir)
        handler.process_file(filepath)
        
        # Verify output
        output_path = os.path.join(temp_dir, ".processed", "config.json.txt")
        assert os.path.exists(output_path), "JSON output not created"
        
        with open(output_path, 'r') as f:
            content = f.read()
        
        assert "# JSON File" in content, "JSON header missing"
        assert "Test App" in content, "JSON content missing"
        print("✓ JSON processing works")


def test_yaml_processing():
    """Test YAML file processing."""
    print("\n=== Testing YAML Processing ===")
    with tempfile.TemporaryDirectory() as temp_dir:
        yaml_content = """
version: 3
services:
  db:
    image: postgres
    ports:
      - 5432:5432
"""
        filepath = create_test_file(temp_dir, "config.yaml", yaml_content)
        
        handler = FileWatcherHandler(temp_dir)
        handler.process_file(filepath)
        
        output_path = os.path.join(temp_dir, ".processed", "config.yaml.txt")
        if os.path.exists(output_path):
            with open(output_path, 'r') as f:
                content = f.read()
            assert "# YAML File" in content or "version" in content, "YAML not processed"
            print("✓ YAML processing works")
        else:
            print("⚠ YAML processing skipped (PyYAML not installed)")


def test_xml_processing():
    """Test XML file processing."""
    print("\n=== Testing XML Processing ===")
    with tempfile.TemporaryDirectory() as temp_dir:
        xml_content = """<?xml version="1.0"?>
<root>
    <item id="1">
        <name>First</name>
        <value>100</value>
    </item>
</root>"""
        filepath = create_test_file(temp_dir, "data.xml", xml_content)
        
        handler = FileWatcherHandler(temp_dir)
        handler.process_file(filepath)
        
        output_path = os.path.join(temp_dir, ".processed", "data.xml.txt")
        assert os.path.exists(output_path), "XML output not created"
        
        with open(output_path, 'r') as f:
            content = f.read()
        
        assert "# XML File" in content, "XML header missing"
        assert "First" in content, "XML content missing"
        print("✓ XML processing works")


def test_html_processing():
    """Test HTML file processing."""
    print("\n=== Testing HTML Processing ===")
    with tempfile.TemporaryDirectory() as temp_dir:
        html_content = """
<!DOCTYPE html>
<html>
<head>
    <title>Test Page</title>
    <script>alert('test');</script>
</head>
<body>
    <h1>Welcome</h1>
    <p>This is a test page.</p>
</body>
</html>
"""
        filepath = create_test_file(temp_dir, "page.html", html_content)
        
        handler = FileWatcherHandler(temp_dir)
        handler.process_file(filepath)
        
        output_path = os.path.join(temp_dir, ".processed", "page.html.txt")
        assert os.path.exists(output_path), "HTML output not created"
        
        with open(output_path, 'r') as f:
            content = f.read()
        
        assert "Test Page" in content, "HTML title missing"
        assert "Welcome" in content, "HTML content missing"
        assert "alert" not in content, "Script not removed"
        print("✓ HTML processing works")


def test_markdown_processing():
    """Test Markdown file processing."""
    print("\n=== Testing Markdown Processing ===")
    with tempfile.TemporaryDirectory() as temp_dir:
        md_content = """# Title

## Section
- Bullet 1
- Bullet 2

**Bold** and *italic*.
"""
        filepath = create_test_file(temp_dir, "doc.md", md_content)
        
        handler = FileWatcherHandler(temp_dir)
        handler.process_file(filepath)
        
        output_path = os.path.join(temp_dir, ".processed", "doc.md.txt")
        assert os.path.exists(output_path), "Markdown output not created"
        
        with open(output_path, 'r') as f:
            content = f.read()
        
        assert "# Title" in content, "Markdown not preserved"
        print("✓ Markdown processing works")


def test_config_processing():
    """Test INI/CONF file processing."""
    print("\n=== Testing Config Processing ===")
    with tempfile.TemporaryDirectory() as temp_dir:
        ini_content = """[database]
host=localhost
port=5432

[features]
auth=true
logging=true
"""
        filepath = create_test_file(temp_dir, "app.ini", ini_content)
        
        handler = FileWatcherHandler(temp_dir)
        handler.process_file(filepath)
        
        output_path = os.path.join(temp_dir, ".processed", "app.ini.txt")
        assert os.path.exists(output_path), "Config output not created"
        
        with open(output_path, 'r') as f:
            content = f.read()
        
        assert "database" in content, "Config section missing"
        assert "localhost" in content, "Config value missing"
        print("✓ Config processing works")


def test_plaintext_processing():
    """Test plain text fallback."""
    print("\n=== Testing Plain Text Processing ===")
    with tempfile.TemporaryDirectory() as temp_dir:
        text_content = "This is a simple text file.\nWith multiple lines.\n"
        filepath = create_test_file(temp_dir, "notes.txt", text_content)
        
        handler = FileWatcherHandler(temp_dir)
        handler.process_file(filepath)
        
        output_path = os.path.join(temp_dir, ".processed", "notes.txt.txt")
        assert os.path.exists(output_path), "Text output not created"
        
        with open(output_path, 'r') as f:
            content = f.read()
        
        assert "simple text" in content, "Text not processed"
        print("✓ Plain text processing works")


def test_source_code_processing():
    """Test source code file processing."""
    print("\n=== Testing Source Code Processing ===")
    with tempfile.TemporaryDirectory() as temp_dir:
        py_content = '''"""Module docstring."""

def hello_world():
    """Greet the world."""
    print("Hello")

class MyClass:
    """A simple class."""
    def method(self):
        pass
'''
        filepath = create_test_file(temp_dir, "script.py", py_content)
        
        handler = FileWatcherHandler(temp_dir)
        handler.process_file(filepath)
        
        output_path = os.path.join(temp_dir, ".processed", "script.py.txt")
        assert os.path.exists(output_path), "Python output not created"
        
        with open(output_path, 'r') as f:
            content = f.read()
        
        assert "# Source Code (PY)" in content, "Code header missing"
        assert "script.py" in content or "Lines:" in content, "Code metadata missing"
        print("✓ Source code processing works")


def test_log_processing():
    """Test log file processing."""
    print("\n=== Testing Log Processing ===")
    with tempfile.TemporaryDirectory() as temp_dir:
        log_content = "\n".join([f"[2024-01-15 10:{i:02d}:00] Starting task {i}" for i in range(50)])
        filepath = create_test_file(temp_dir, "app.log", log_content)
        
        handler = FileWatcherHandler(temp_dir)
        handler.process_file(filepath)
        
        output_path = os.path.join(temp_dir, ".processed", "app.log.txt")
        assert os.path.exists(output_path), "Log output not created"
        
        with open(output_path, 'r') as f:
            content = f.read()
        
        assert "# Log File" in content, "Log header missing"
        assert "Total lines" in content, "Log metadata missing"
        print("✓ Log file processing works")


def test_archive_processing():
    """Test archive file listing."""
    print("\n=== Testing Archive Processing ===")
    try:
        import zipfile
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create a zip file
            zip_path = os.path.join(temp_dir, "archive.zip")
            with zipfile.ZipFile(zip_path, 'w') as zf:
                zf.writestr("file1.txt", "content1")
                zf.writestr("dir/file2.txt", "content2")
            
            handler = FileWatcherHandler(temp_dir)
            handler.process_file(zip_path)
            
            output_path = os.path.join(temp_dir, ".processed", "archive.zip.txt")
            assert os.path.exists(output_path), "Archive output not created"
            
            with open(output_path, 'r') as f:
                content = f.read()
            
            assert "# Archive Contents" in content, "Archive header missing"
            assert "file1.txt" in content, "Archive files missing"
            print("✓ Archive processing works")
    except ImportError:
        print("⚠ Archive processing skipped (zipfile not available)")


def test_sqlite_processing():
    """Test SQLite database processing."""
    print("\n=== Testing SQLite Processing ===")
    try:
        import sqlite3
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create a test database
            db_path = os.path.join(temp_dir, "test.db")
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, age INTEGER)")
            cursor.execute("INSERT INTO users (name, age) VALUES ('Alice', 30)")
            cursor.execute("INSERT INTO users (name, age) VALUES ('Bob', 25)")
            conn.commit()
            conn.close()
            
            handler = FileWatcherHandler(temp_dir)
            handler.process_file(db_path)
            
            output_path = os.path.join(temp_dir, ".processed", "test.db.txt")
            assert os.path.exists(output_path), "Database output not created"
            
            with open(output_path, 'r') as f:
                content = f.read()
            
            assert "# SQLite Database" in content, "DB header missing"
            assert "users" in content, "Table name missing"
            assert "Alice" in content or "Rows:" in content, "DB data missing"
            print("✓ SQLite processing works")
    except ImportError:
        print("⚠ SQLite processing skipped (sqlite3 not available)")


def run_all_tests():
    """Run all format processing tests."""
    print("🧪 Starting File Format Processing Tests")
    print("=" * 50)
    
    tests = [
        test_json_processing,
        test_yaml_processing,
        test_xml_processing,
        test_html_processing,
        test_markdown_processing,
        test_config_processing,
        test_plaintext_processing,
        test_source_code_processing,
        test_log_processing,
        test_archive_processing,
        test_sqlite_processing,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"✗ {test.__name__} failed: {e}")
            failed += 1
        except Exception as e:
            print(f"✗ {test.__name__} error: {e}")
            failed += 1
    
    print("\n" + "=" * 50)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 50)
    
    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
