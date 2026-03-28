# Tools Reference

## Toolbox Categories (Dynamic Selection)

Tools are organized into 5 toolbox categories. The Router selects which categories are needed per turn, and only the relevant tools are bound to the LLM — saving ~2000 tokens of schema overhead.

### How It Works
1. The Router classifies the user request into one or more toolbox categories.
2. `resolve_tools(toolbox_names, web_search_enabled)` returns the union of tools from the selected categories + always-included tools.
3. The Complex_Node binds only the resolved tools to the LLM.
4. If the Router is uncertain, it selects `"all"` to fall back to the full tool set.

### Always Included
| Tool | Description |
|------|-------------|
| `ask_user` | Ask a clarifying question. Supports 1-3 choice buttons + free text. Always bound regardless of toolbox selection. |

### `web_search` Toolbox
| Tool | Description |
|------|-------------|
| `web_search` | Search via SearXNG/DDG/Bing. Supports `focus_query` for reranking. |
| `fetch_webpage` | Fetch URL content. Embedding-ranked excerpts with `focus_query`. |

### `file_ops` Toolbox
| Tool | Description |
|------|-------------|
| `read_workspace_file` | Read file content. Checks `.processed/` cache for PDFs. Fuzzy filename matching. |
| `write_workspace_file` | Create or overwrite a file. |
| `edit_workspace_file` | Search-and-replace in a file. Exact pattern match required. |
| `list_workspace_files` | List directory contents with file sizes. |
| `delete_workspace_file` | Delete a file. |

### `data_viz` Toolbox
| Tool | Description |
|------|-------------|
| `create_docx` | Word document with headings, bullets, numbered lists. |
| `create_xlsx` | Excel spreadsheet from CSV-like text. First row = headers. |
| `create_pptx` | PowerPoint with slides separated by `---`. |
| `create_pdf` | PDF from text content via PyMuPDF. |
| `notebook_run` | Stateful Python REPL. Variables persist between calls. |
| `notebook_reset` | Clear all notebook variables. |

### `productivity` Toolbox
| Tool | Description |
|------|-------------|
| `todo_add` | Add task with priority (low/medium/high). |
| `todo_list` | List tasks. Filter by status (all/pending/done). |
| `todo_complete` | Mark a task as done. |
| `list_skills` | List available skill templates from `skills/` directory. |
| `invoke_skill` | Load and return a skill's prompt template. |

### `memory` Toolbox
| Tool | Description |
|------|-------------|
| `recall_memories` | Search long-term memory (keyword overlap on recent 50 entries). |

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
3. Add to the appropriate `TOOLBOX_REGISTRY` category (or create a new category)
4. The tool will automatically be included when that toolbox is selected by the Router
5. Update guidance text in `src/agent/nodes/complex.py`
6. If sensitive, add to `SENSITIVE_TOOLS` in `security_proxy.py`
