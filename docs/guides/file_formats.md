# File Format Support Guide

Owlynn can automatically understand and process a wide variety of file formats. When you upload files to the chat, they are automatically converted to readable formats and cached for fast retrieval.

## Overview

**Supported Categories:**
- 📄 Document Formats (PDF, Word, Markdown)
- 🗄️ Data Formats (JSON, CSV, XLSX, YAML, TOML)
- 🌐 Web Formats (HTML, XML)
- 💾 Database Formats (SQLite)
- 📦 Archive Formats (ZIP, TAR, GZ, RAR, 7Z)
- 💻 Code Formats (Python, JavaScript, TypeScript, Java, C++, Go, Rust, Ruby, PHP)
- 📋 Configuration Formats (INI, CONF, CONFIG)
- 📜 Log Files

---

## Document Formats

### PDF (`.pdf`)
**What it does:**
- Extracts all text from PDF pages
- Preserves page boundaries with "--- Page N ---" markers
- Maintains reading order

**Example output:**
```
--- Page 1 ---
Chapter 1: Introduction
This document explains...

--- Page 2 ---
[content continues]
```

**Requirements:** `PyMuPDF` (installed)
**Limitations:** 
- Text-only extraction (no OCR for scanned PDFs)
- Images within PDFs are not extracted

---

### Microsoft Word (`.docx`)
**What it does:**
- Extracts all paragraph text
- Preserves text content flow

**Example output:**
```
Executive Summary
This report examines key findings...
Key Points:
1. First point
2. Second point
```

**Requirements:** `python-docx` (installed)
**Limitations:**
- Formatting (bold, italic, etc.) is not preserved
- Tables are not specially handled
- Images and complex layouts are ignored

---

### Markdown (`.md`, `.markdown`)
**What it does:**
- Validates UTF-8 encoding
- Passes through directly for agent consumption
- Preserves all markdown syntax

**Example output:**
```
# Title
## Section
- Bullet list
- Another item

**Bold text** and *italic*.
```

**Requirements:** None (built-in)
**Features:**
- Full markdown support including tables and code blocks
- Syntax highlighting in chat display

---

## Data & Configuration Formats

### JSON (`.json`)
**What it does:**
- Parses JSON structure
- Pretty-prints with 2-space indentation
- Wraps in code block for clarity

**Example output:**
```json
{
  "name": "Owlynn",
  "version": "1.0.0",
  "features": [
    "agents",
    "chat"
  ]
}
```

**Requirements:** None (built-in)
**Error Handling:** If JSON is malformed, displays the parse error and falls back to raw text

---

### YAML (`.yaml`, `.yml`)
**What it does:**
- Parses YAML structure
- Re-formats with consistent indentation
- Preserves hierarchy

**Example output:**
```yaml
version: 3.0
services:
  database:
    image: postgres
    ports:
      - 5432:5432
```

**Requirements:** `PyYAML` (installed)
**Fallback:** If PyYAML not installed, treats as plain text

---

### TOML (`.toml`)
**What it does:**
- Parses TOML configuration
- Pretty-prints sections and values
- Validates syntax

**Example output:**
```toml
[package]
name = "myapp"
version = "0.1.0"

[dependencies]
requests = "~2.28.0"
```

**Requirements:** `tomli` (for reading), `tomli_w` (for writing - optional)
**Fallback:** If TOML libraries not installed, treats as plain text

---

### Configuration Files (`.ini`, `.conf`, `.config`)
**What it does:**
- Parses INI-style configuration
- Organizes by sections with markdown headers
- Lists each key-value pair

**Example output:**
```
# Configuration File

## [database]
- **host**: localhost
- **port**: 5432
- **username**: admin

## [cache]
- **enabled**: true
- **ttl**: 3600
```

**Requirements:** None (built-in via `configparser`)

---

### CSV & Excel (`.csv`, `.xlsx`)
**What it does:**
- Reads data into pandas DataFrame
- Converts to Markdown table format
- Preserves column names and data types

**Example output:**
```
| Name | Age | City |
|------|-----|------|
| Alice | 30 | NYC |
| Bob | 25 | LA |
```

**Requirements:** `pandas`, `openpyxl` (for XLSX)
**Features:**
- Tables render beautifully in chat
- Agent can reason about tabular data directly

---

## Structured Data Formats

### XML (`.xml`)
**What it does:**
- Parses XML structure
- Pretty-prints with indentation
- Validates XML syntax

**Example output:**
```xml
<?xml version="1.0"?>
<root>
  <item id="1">
    <name>First</name>
    <value>100</value>
  </item>
</root>
```

**Requirements:** None (built-in via `xml.etree`)
**Error Handling:** Displays parse errors and attempts fallback to raw text

---

### SQLite Database (`.db`, `.sqlite`, `.sqlite3`)
**What it does:**
- Lists all tables in database
- Shows table schema (columns and types)
- Displays row counts
- Shows sample data (first 5 rows per table)

**Example output:**
```
# SQLite Database

## Tables (3)

### users
**Columns:**
- id (INTEGER)
- name (TEXT)
- email (TEXT)

Rows: 42

**Sample Data:**
(1, 'Alice', 'alice@example.com')
(2, 'Bob', 'bob@example.com')
```

**Requirements:** None (Python built-in sqlite3)
**Features:**
- Agent understands database schema without direct SQL access
- Safe read-only exploration
- Useful for understanding data structure

---

## Web & Markup

### HTML (`.html`, `.htm`)
**What it does:**
- Extracts page title
- Removes script and style tags
- Converts HTML to readable text
- Cleans up excess whitespace

**Example output:**
```
# My Website

## Extracted Content

Welcome to our site!
Here are the main features:
- Feature 1
- Feature 2
```

**Requirements:** None (built-in via regex)
**Features:**
- Removes script/style noise
- Preserves text structure
- Safe - doesn't execute JavaScript

---

## Archive Formats

### ZIP (`.zip`)
**What it does:**
- Lists all file names and structure
- Shows total item count
- Limits display to first 100 items

**Example output:**
```
# Archive Contents (.zip)

**Total items:** 247

## File List

- src/main.py
- src/utils.py
- tests/test_main.py
- README.md
... and 243 more items
```

**Requirements:** None (built-in via `zipfile`)

---

### TAR/GZ (`.tar`, `.gz`)
**What it does:**
- Lists all files in archive
- Maintains directory structure
- Shows total item count

**Example output:**
```
# Archive Contents (.tar)

**Total items:** 52

## File List

- project/src/main.rs
- project/src/lib.rs
- project/Cargo.toml
```

**Requirements:** None (built-in via `tarfile`)

---

### RAR/7Z (`.rar`, `.7z`)
**What it does:**
- Notes that format is recognized but requires external tools
- Provides guidance on additional setup

**Example output:**
```
# 7Z Archive

Supported but requires additional libraries for detailed extraction.
```

**Note:** These formats need external utilities for full support

---

## Code & Text Formats

### Source Code (`.py`, `.js`, `.ts`, `.java`, `.cpp`, `.c`, `.go`, `.rs`, `.rb`, `.php`)
**What it does:**
- Counts total lines
- Estimates function/method count
- Estimates class count
- Extracts docstring/module description
- Displays full source with syntax highlighting

**Example output:**
```
# Source Code (PYTHON)

**Lines:** 342
**Functions/Methods:** 18
**Classes:** 5
**Description:** Main agent orchestrator for LangGraph...

## Code

[Full source code with syntax highlighting]
```

**Requirements:** None (built-in with regex analysis)
**Features:**
- Agent can understand code structure without parsing
- Useful for code review and explanation
- Works with any programming language extension

---

### Log Files (`.log`)
**What it does:**
- Shows total line count
- Displays last 500 lines (or all if smaller)
- Provides recent context

**Example output:**
```
# Log File

**Total lines:** 10,543
**Showing:** Last 500 lines

## Content

[2024-01-15 10:30:45] INFO Starting agent...
[2024-01-15 10:30:46] DEBUG Loaded model...
...
```

**Requirements:** None (built-in)
**Features:**
- Perfect for debugging recent events
- Avoids overwhelming display with massive logs

---

### Plain Text (`.txt`)
**What it does:**
- Reads file directly
- Attempts to detect if it's code-like
- Handles encoding issues gracefully

**Supported:** Any `.txt` file

---

## Processing Pipeline

### Automatic Processing
1. **File Upload**: User loads file via chat interface
2. **Detection**: File extension determines format
3. **Processing**: Appropriate handler converts to readable text
4. **Caching**: Result stored in `.processed/` directory
5. **Display**: Chat shows formatted content
6. **Agent Access**: LLM can reason about content

### File Cache
- Location: `workspace/.processed/`
- Each file creates a corresponding `.txt` file
- Cache is preserved between sessions
- Re-uploading same file uses cached version

### Error Handling
- Failed parsing falls back to raw text
- Encoding issues handled with UTF-8 replacement
- Malformed files display error message with raw content fallback
- Graceful degradation for optional dependencies

---

## Limitations & Notes

### General Limitations
- **Large Files**: Very large files (>100MB) may impact performance
- **Binary Files**: Non-text binary formats cannot be processed
- **Character Encoding**: Expects UTF-8 (with fallback for other encodings)
- **Media**: Images and audio are not processed as content (only visual models can interpret images directly)

### Format-Specific Limitations
- **PDF**: No OCR for scanned documents; images not extracted
- **XLSX**: Only data extracted; formulas shown as values
- **Word**: Formatting lost; complex layouts may not render correctly
- **HTML**: JavaScript not executed; only static text extracted
- **Archives**: RAR/7Z require external utilities for full support
- **SQLite**: Read-only exploration; no data modification

### Performance Notes
- **First Upload**: Slight delay while file is processed and cached
- **Subsequent Uploads**: Instant retrieval from cache
- **Large Tables**: CSV/XLSX with 10k+ rows may be truncated for readability
- **Archive Listing**: Limited to first 100 items display

---

## Install Additional Formats Support

Some formats require optional dependencies. Install them with:

```bash
# All file format support
pip install PyYAML tomli tomli_w pymupdf

# Or from requirements.txt
pip install -r requirements.txt
```

### Optional Dependencies
- `PyYAML` (3.6 MB) - YAML parsing
- `tomli` (18 KB) - TOML reading
- `tomli_w` (17 KB) - TOML writing
- `pymupdf` (50 MB) - PDF text extraction (usually already installed)

---

## Examples

### Example 1: Configuration File
```ini
# Upload: config.ini

[database]
host=localhost
port=5432
username=admin

[features]
auth=enabled
logging=enabled
```

**Agent sees:**
```
# Configuration File

## [database]
- **host**: localhost
- **port**: 5432
- **username**: admin

## [features]
- **auth**: enabled
- **logging**: enabled
```

Agent can now reason: "The database is on localhost at port 5432 with admin user..."

---

### Example 2: Python Script
```python
# Upload: process.py

def calculate_sum(numbers):
    """Sum a list of numbers."""
    return sum(numbers)

def calculate_avg(numbers):
    """Average of a list."""
    return sum(numbers) / len(numbers)

class Calculator:
    def __init__(self, values):
        self.values = values
```

**Agent sees:**
```
# Source Code (PYTHON)

**Lines:** 14
**Functions/Methods:** 2
**Classes:** 1
**Description:** Sum a list of numbers.

## Code

[Full source with syntax highlighting]
```

Agent can now understand: "This module has calculation utilities with 1 class and 2 functions..."

---

### Example 3: Data CSV
```csv
product,price,stock
Widget,9.99,150
Gadget,24.99,75
Component,4.50,1000
```

**Agent sees:**
```
| product | price | stock |
|---------|-------|-------|
| Widget | 9.99 | 150 |
| Gadget | 24.99 | 75 |
| Component | 4.50 | 1000 |
```

Agent can now analyze: "Products sorted by stock levels..." or "Average price calculation..."

---

## Adding New Formats

To add support for a new file format, edit `src/api/file_processor.py`:

1. Add format extension to `process_file()` method
2. Create `_process_format()` method
3. Return formatted text output
4. Add error handling and logging
5. Update `requirements.txt` with new dependencies
6. Test with sample files

Example:
```python
def _process_custom_format(self, filepath, output_path):
    """Parse custom format."""
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Process content...
    processed = do_something(content)
    
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(processed)
```

---

## Troubleshooting

### File Not Processed
- Check file extension is recognized (see list above)
- Verify file is in workspace directory
- Check `.processed/` directory for error logs
- File may need to be re-uploaded

### Encoding Error
- FileProcessor will attempt UTF-8 with error replacement
- Try converting file to UTF-8 explicitly: `iconv -f ISO-8859-1 -t UTF-8 file.txt > file-utf8.txt`

### Large File Truncation
- Very large files are automatically truncated for display
- Agent can still work with full content if needed
- Consider splitting very large files

### Missing Dependencies
- Install optional format libraries: `pip install -r requirements.txt`
- Or install individual packages for specific formats

---

## Architecture Notes

### Cache System
- Files are processed once and cached
- Cache survives agent restarts
- Cache located in `workspace/.processed/`
- Use `rm -rf .processed/*` to clear cache

### Processing Thread
- File processing happens in background daemon thread
- Watchdog observer monitors workspace directory  
- Files processed after 1-second delay (allows upload to complete)
- Non-blocking - doesn't interrupt chat

### Integration with Agent
- Chat interface displays `.processed/` file content
- LLM accesses via message building with tool calls
- Special multimodal handling for images
- Full text available for reasoning

---

For questions or issues with file format support, check the main [README.md](../../README.md) or explore the `src/api/file_processor.py` implementation.
