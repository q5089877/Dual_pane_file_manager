# Dual Pane File Manager

A dual-pane file explorer for Windows, built with Python and PyQt6.  
Designed for engineers and power users who work with deep project directories and network drives.

> **Platform:** Windows only · **Python:** 3.10+

---

## Motivation

Windows Explorer is fine for casual use. But when you're constantly jumping between project folders, copying files across network drives, or searching a 500GB NAS for a file you modified last week — it falls short.

**Double File Explorer** was built to solve three specific pain points:

- **No dual-pane**: switching between two folders requires alt-tabbing between windows
- **Network search is slow**: Windows Search doesn't index UNC paths or network drives reliably
- **No keyboard flow**: every operation requires reaching for the mouse

---

## Features

### Dual-Pane Navigation
- Left and right panes, each with multiple tabs
- Tab key cycles tabs · `` ` `` switches between panes
- Full navigation history (Alt+Left / Alt+Right)
- Address bar with path autocomplete

### File Operations (keyboard-first)
| Key | Action |
|-----|--------|
| `F2` | Rename |
| `Alt+F2` | Rename with timestamp |
| `F3` / `X` | Move to opposite pane |
| `F4` / `C` | Copy to opposite pane |
| `F5` | Refresh |
| `F6` | Duplicate in place |
| `F7` | New folder |
| `Del` | Send to Recycle Bin |
| `Ctrl+Z` | Undo last move / rename |
| `Space` | Toggle preview panel |
| `Ctrl+D` | Pin / unpin item |
| `Ctrl+F` | Advanced search |

### File Preview (no extra app needed)
- **Images** — loaded in background thread, no UI freeze
- **PDF** — rendered via PyMuPDF, first N pages as images
- **Text / Source code** — syntax highlighting via Highlight.js
- **CSV / XLSX** — table preview (first 15 rows)
- **ZIP / 7z** — file listing without extraction
- **DOCX** — plain text extraction

### Network Search
Full-text search across local and network drives using SQLite FTS5.

- **Master node**: builds and publishes the search index to a shared network folder
- **Consumer node**: reads the shared index for instant search without scanning
- Background indexing — never blocks the UI
- Filters by size, date modified, file extension

### Pin System
Pin files and folders for quick access, with automatic TTL expiry:
- Normal pins expire after 7 days
- Important pins degrade after 30 days of no access
- Done pins auto-clear on next startup

### Additional Tools
- **Folder Compare** — diff two directories, sync with one click
- **AI Context Export** — export a folder's source files as a single text for LLM context
- **Paste as File** — paste clipboard image or text directly as a new file
- **Drop Zone** — drag files to a temporary staging area, then batch-move or zip

### Themes
Three built-in themes switchable from Settings:
- 調光護眼 (default dark)
- 深色 Dracula
- 亮色清爽 (light)

### Languages
- 繁體中文 (`zh_TW`)
- English (`en_US`)

---

## Installation

```bash
# 1. Clone the repo
git clone https://github.com/<username>/double-file-explorer.git
cd double-file-explorer

# 2. Create a virtual environment (recommended)
python -m venv venv
venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Copy and configure settings
copy config.example.json config.json

# 5. Run
python main.py
```

> **Note:** `winshell` and `pywin32` are Windows-only packages.  
> This application does not run on macOS or Linux.

---

## Configuration

Copy `config.example.json` to `config.json` and edit as needed.

| Key | Description | Default |
|-----|-------------|---------|
| `language` | UI language (`zh_TW` / `en_US`) | `zh_TW` |
| `left_tabs` | Paths to open in left pane on startup | `["C:\\"]` |
| `right_tabs` | Paths to open in right pane on startup | `["C:\\"]` |
| `remote_index_root` | Path to the shared search index folder on network drive | `""` |
| `remote_index_suffix` | Suffix used to auto-discover the index folder across drive letters | `""` |
| `update_source_suffix` | Suffix used to auto-discover the update source folder | `""` |
| `is_master_node` | `true` = this machine builds and publishes the index | `false` |
| `default_scan_root` | Root path for personal index scanning | `""` |
| `pdf_preview_max_pages` | Max pages rendered in PDF preview | `3` |
| `confirm_before_delete` | Show confirmation dialog before delete | `true` |
| `preview_font_size` | Font size in text preview panel | `13` |

### Portable Mode

If `config.json` exists in the same folder as `main.py` (or the `.exe`), the app runs in **portable mode** — all settings are stored next to the executable instead of `%LOCALAPPDATA%`.

---

## Network Search Setup

The network search feature uses a **Master / Consumer** model:

```
[Master Machine]                    [Shared Network Drive]
  Scans local + assigned paths  →   Publishes index to shared folder
  
[Consumer Machines]
  Reads shared index  →  Instant search without scanning
```

**To set up Master node:**
1. Set `"is_master_node": true` in `config.json`
2. Set `"default_scan_root"` to the path you want indexed
3. Set `"remote_index_root"` to a shared network folder all machines can access
4. The app will scan and publish the index automatically in the background

**To set up Consumer node:**
1. Leave `"is_master_node": false` (default)
2. Set `"remote_index_root"` to the same shared network folder
3. Search results will include the master's published index

---

## Build Standalone Executable

```bash
build_portable.bat
```

Requires PyInstaller. The output is a single-folder portable build in `dist/`.

---

## Project Structure

```
double_file_explorer/
├── core/               # Business logic (no PyQt)
│   ├── config_manager.py
│   ├── file_ops.py
│   ├── interfaces.py   # ABC contracts for all Views
│   └── models/
├── ui/
│   ├── panes/          # Composite view components
│   ├── presenters/     # MVP Presenters
│   ├── widgets/        # Reusable UI widgets
│   └── windows/        # Main window
├── network_search/     # Search engine and indexer
├── tests/              # pytest unit tests
├── langs/              # i18n JSON files
├── styles.qss          # Qt stylesheet
├── theme.json          # Active colour theme
└── config.json         # User config (not tracked in git)
```

Architecture follows **MVP (Model-View-Presenter)**:
- `core/` contains zero PyQt imports
- Views implement `abc.ABC` interfaces defined in `core/interfaces.py`
- Presenters receive View and Model via dependency injection

---

## Running Tests

```bash
pytest tests/
```

---

## Requirements

```
PyQt6==6.10.2
PyQt6-WebEngine==6.10.0
pymupdf==1.27.2.2
send2trash==2.1.0
winshell==0.6
pywin32==311
openpyxl==3.1.5
python-docx==1.2.0
```

---

## License

MIT License — see [LICENSE](LICENSE)
