# Dual Pane File Manager

> A keyboard-driven, dual-pane file explorer for Windows with built-in network search.  
> Built with Python 3.10+ and PyQt6.

**Platform:** Windows only &nbsp;·&nbsp; **Version:** 1.3.0 &nbsp;·&nbsp; **License:** MIT

---

## Why this exists

Windows Explorer works fine for casual use. But when you're constantly jumping between project folders, copying files across a NAS, or hunting for a file you touched last week — it falls short.

This tool was built to close three specific gaps:

- **No dual-pane** — switching between two folders requires alt-tabbing between windows
- **Network search is unreliable** — Windows Search doesn't index UNC paths or SMB drives consistently
- **Too mouse-heavy** — every rename, copy, and move requires reaching for the mouse

---

## Quick Start

```bash
# 1. Clone
git clone https://github.com/q5089877/Dual_pane_file_manager.git
cd Dual_pane_file_manager

# 2. Virtual environment (recommended)
python -m venv venv
venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure
copy config.example.json config.json

# 5. Run
python main.py
```

---

## Features

### Dual-Pane Navigation

- Left and right panes, each supporting up to **5 independent tabs**
- `Tab` cycles tabs within a pane · `` ` `` switches between left and right
- Full navigation history — `Alt+←` / `Alt+→`
- Editable address bar for direct path entry
- Home screen (`home://`) shows all drives and Windows Quick Access folders
- Three view modes per pane: **list**, **tree**, and **icon/thumbnail grid**

### File Operations

All primary operations are keyboard-accessible:

| Key | Action |
|-----|--------|
| `F2` | Rename (inline) |
| `Alt+F2` | Rename with date suffix (`_YYYYMMDD`) |
| `F3` / `X` | Move to opposite pane |
| `F4` / `C` | Copy to opposite pane |
| `F5` | Refresh |
| `F7` | New folder |
| `Del` | Send to Recycle Bin |
| `Shift+Del` | Permanently delete |
| `Ctrl+C / X / V` | System clipboard copy / cut / paste |
| `Ctrl+Z` | Undo last move, rename, or delete |
| `Ctrl+D` | Pin / unpin item |
| `Ctrl+F` | Open search panel |
| `Space` | Toggle file preview |

Additional operations via right-click context menu or toolbar:

- Duplicate file in place (auto-numbered suffix)
- Create `.zip` archive from a folder (date-stamped name)
- Extract `.zip` / `.tar.gz` / `.tar.bz2` / `.tar.xz` — smart target folder detection
- Paste clipboard image or text directly as a new file
- Export folder as ASCII tree (saved to `.txt`, opened in Notepad)
- Export folder contents as AI context (Markdown + source, for LLM prompts)

**Undo** covers the last 10 move, rename, and trash operations per session.  
**OneDrive-aware**: offline cloud placeholders are detected and skipped automatically.

### File Preview

Press `Space` to open the preview panel, or `Space` again for a full-screen Quick Look overlay.

| Format | How it renders |
|--------|---------------|
| Images (JPG, PNG, BMP, GIF…) | Decoded in background thread — no UI freeze |
| PDF / `.ai` | PyMuPDF · configurable page count · SD / HD quality toggle |
| Text / source code | Highlight.js syntax highlighting via WebEngine |
| CSV / XLSX | HTML table — first 15 rows |
| ZIP / 7z | File listing |
| DOCX | Plain text extraction |
| Markdown | Rendered HTML |
| SVG | Inline rendering |
| Audio (MP3, FLAC, OGG…) | Metadata tags via mutagen |
| Fonts (TTF, OTF) | Embedded character preview |

Preview loads with a 150 ms debounce on a background thread so navigating quickly never stalls the UI.

### Network Search

Full-text search across local and network drives, powered by **SQLite FTS5**.

The search panel opens inline (no modal dialog) via `Ctrl+F`.

**Master / Consumer architecture:**

```
[Master machine]
  Scans local drives + assigned network paths
  → Publishes index to a shared folder on the NAS

[Any machine with Consumer mode]
  Reads the shared index
  → Instant cross-drive search with no scanning delay
```

- Filters: size (`> 1 MB` → `> 1 GB`), date (today / this week / this month / custom), wildcard patterns (`*.pdf`, `report_?.docx`)
- Results stream in batches of 50 — navigating to a result opens its folder directly
- Personal index (`personal.db`) is built automatically when the system is idle
- Master index rotates between two database slots (`index_A` / `index_B`) for live hot-swap with no downtime

### Pins & Favorites

**Pins** (`Ctrl+D`): quick bookmarks that appear in the toolbar dropdown.
- Attach an optional note (5-second auto-confirm dialog)
- Mark as Important to preserve permanently; normal pins show a warning after 14 days of disuse
- Drag a folder onto the Pin button to add it silently

**Favorites**: named groups of saved paths managed through a dedicated dialog.
- Create, rename, and delete groups
- Add the current folder to any group with one click

### Themes & Language

Two built-in UI languages, auto-detected from your Windows locale:
- `zh_TW` — Traditional Chinese
- `en_US` — English

Theme colors are defined in `theme.json` and applied via `styles.qss` — no hard-coded colors in Python. The default theme ("調光護眼") uses a dark blue palette optimized for long sessions.

### Auto-Update

The app checks GitHub Releases 10 seconds after startup. If a new version is available, a button appears in the status bar. Clicking it downloads the installer in the background and launches it automatically.

---

## Configuration

Copy `config.example.json` to `config.json` and edit as needed.

| Key | Description | Default |
|-----|-------------|---------|
| `language` | UI language: `zh_TW` or `en_US` | `zh_TW` |
| `left_tabs` | Startup paths for the left pane | `["C:\\"]` |
| `right_tabs` | Startup paths for the right pane | `["C:\\"]` |
| `restore_last_session` | Restore last open tabs on startup | `true` |
| `confirm_before_delete` | Ask before sending to Recycle Bin | `true` |
| `preview_font_size` | Font size in text preview | `14` |
| `pdf_preview_max_pages` | Pages rendered in PDF preview | `3` |
| `search_limit` | Max results returned by search | `1000` |
| `remote_index_root` | Path to the shared search index folder (network drive) | `""` |
| `is_master_node` | `true` = this machine builds and publishes the index | `false` |
| `monitored_paths` | Paths the master node scans | `[]` |
| `exclude_exts` | File extensions to skip during indexing | `[]` |
| `exclude_dirs` | Folder names to skip during indexing | `[]` |

### Portable Mode

If `config.json` exists next to `main.py` (or the `.exe`), the app runs in **portable mode** — all settings and logs stay in the same folder instead of `%LOCALAPPDATA%`.

---

## Network Search Setup

### Master node (the machine that builds the index)

```jsonc
// config.json
{
  "is_master_node": true,
  "monitored_paths": ["C:\\Projects", "K:\\SharedWork"],
  "remote_index_root": "K:\\SearchIndex",
  "max_depth": 7
}
```

The master scans `monitored_paths` on a nightly schedule (default 02:00) and writes the result to `remote_index_root`. All consumers read from there.

### Consumer node (everyone else)

```jsonc
{
  "is_master_node": false,
  "remote_index_root": "K:\\SearchIndex"
}
```

Set `remote_index_root` to the same shared folder. Search results will include the master's published index with no configuration beyond that.

> **Security note:** The admin backdoor (`Ctrl+Shift+Alt+A`) uses the password stored in `master_node_password`. Change the default (`"1235"`) before deploying in a shared environment.

---

## Build a Standalone Executable

```bash
build_portable.bat
```

Requires PyInstaller. Output lands in `dist/DualPaneFileManager/` as a portable folder build.  
The installer script (`installer.iss`) packages it with Inno Setup.

---

## Project Structure

```
Dual_pane_file_manager/
├── core/                   # Business logic — zero PyQt imports
│   ├── config_manager.py   # config.json + theme.json read/write
│   ├── file_ops.py         # All disk I/O (copy, move, archive, trash)
│   ├── interfaces.py       # abc.ABC contracts for all Views
│   └── models/             # Data structures
├── ui/
│   ├── panes/              # ExplorerPane — composite view
│   ├── presenters/         # MVP Presenters
│   ├── widgets/            # Reusable widgets (preview, search, dialogs)
│   └── windows/            # MainWindow
├── network_search/         # SQLite FTS5 indexer and search engine
├── tests/                  # pytest unit tests
├── langs/                  # i18n — zh_TW.json, en_US.json
├── styles.qss              # Qt stylesheet (no colors in Python)
├── theme.json              # Active color theme
├── config.example.json     # Configuration template
└── main.py                 # Entry point
```

Architecture follows strict **MVP (Model-View-Presenter)**:
- `core/` has no PyQt imports
- All Views implement `abc.ABC` interfaces from `core/interfaces.py`
- Presenters receive View and Model instances via constructor injection

---

## Requirements

```
Python        3.10+
PyQt6         6.10+
PyQt6-WebEngine 6.10+   (preview panel)
PyMuPDF                 (PDF preview)
Send2Trash              (recycle bin)
winshell + pywin32      (Windows shell integration)
openpyxl                (XLSX preview)
python-docx             (DOCX preview)
mutagen                 (audio metadata)
Markdown                (Markdown preview)
Pillow                  (image processing)
py7zr                   (7z extraction)
```

Install everything at once:

```bash
pip install -r requirements.txt
```

> This application requires Windows. `winshell` and `pywin32` have no macOS / Linux equivalent.

---

## Running Tests

```bash
pytest tests/
```

---

## License

MIT — see [LICENSE](LICENSE)
