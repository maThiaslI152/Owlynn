# Tools Reference

## LLM-Bound Tools (20)

These tools are bound to the Qwen3.5-9B model via `src/agent/tool_sets.py`.

### Web
| Tool | Description |
|------|-------------|
| `web_search` | Search via SearXNG/DDG/Bing. Supports `focus_query` for reranking. |
| `fetch_webpage` | Fetch URL content. Embedding-ranked excerpts with `focus_query`. |

### File Management
| Tool | Description |
|------|-------------|
| `read_workspace_file` | Read file content. Checks `.processed/` cache for PDFs. Fuzzy filename matching. |
| `write_workspace_file` | Create or overwrite a file. |
| `edit_workspace_file` | Search-and-replace in a file. Exact pattern match required. |
| `list_workspace_files` | List directory contents with file sizes. |
| `delete_workspace_file` | Delete a file. |

### Document Generation
| Tool | Description |
|------|-------------|
| `create_docx` | Word document with headings, bullets, numbered lists. |
| `create_xlsx` | Excel spreadsheet from CSV-like text. First row = headers. |
| `create_pptx` | PowerPoint with slides separated by `---`. |
| `create_pdf` | PDF from text content via PyMuPDF. |

### Computation
| Tool | Description |
|------|-------------|
| `notebook_run` | Stateful Python REPL. Variables persist between calls. |
| `notebook_reset` | Clear all notebook variables. |

### Memory
| Tool | Description |
|------|-------------|
| `recall_memories` | Search long-term memory (keyword overlap on recent 50 entries). |

### Task Management
| Tool | Description |
|------|-------------|
| `todo_add` | Add task with priority (low/medium/high). |
| `todo_list` | List tasks. Filter by status (all/pending/done). |
| `todo_complete` | Mark a task as done. |

### Skills
| Tool | Description |
|------|-------------|
| `list_skills` | List available skill templates from `skills/` directory. |
| `invoke_skill` | Load and return a skill's prompt template. |

### Human-in-the-Loop
| Tool | Description |
|------|-------------|
| `ask_user` | Ask a clarifying question. Supports 1-3 choice buttons + free text. |

## Security Policy

Sensitive tools require approval via `security_proxy`:
- `write_workspace_file`
- `edit_workspace_file`
- `delete_workspace_file`
- `notebook_run`

All other tools auto-approve. Dangerous shell patterns (rm -rf, sudo, etc.) are blocked.

## Adding a New Tool

1. Create `@tool` function in `src/tools/`
2. Import in `src/agent/tool_sets.py`
3. Add to `COMPLEX_TOOLS_WITH_WEB` and/or `COMPLEX_TOOLS_NO_WEB`
4. Update guidance text in `src/agent/nodes/complex.py`
5. If sensitive, add to `SENSITIVE_TOOLS` in `security_proxy.py`
