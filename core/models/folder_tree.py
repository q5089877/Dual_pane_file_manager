"""
folder_tree.py — 遞迴產生資料夾樹狀圖（Markdown 格式，含 📁/📄 emoji）
純邏輯模組，無 Qt 依賴。
"""
import os


def count_items(root: str) -> int:
    """快速計算 root 下的總項目數（資料夾 + 檔案）。"""
    total = 0
    for _, dirs, files in os.walk(root):
        total += len(dirs) + len(files)
    return total


def generate_tree(root: str) -> str:
    """
    遞迴掃描 root，回傳 Markdown 格式的樹狀圖字串。

    格式範例：
        # Directory Structure: my_folder

        ## 📂 Directory Structure
        ```text
        📁 my_folder/
        ├── 📁 docs/
        │   └── 📄 report.pdf
        └── 📄 README.md
        ```

        ---

        ## 📊 Statistics
        - **Total Files in Tree:** 5
        - **Mode:** Directory Structure Only (Tree Map)
    """
    root_name = os.path.basename(root.rstrip("/\\")) or root
    tree_lines: list[str] = []
    file_count = [0]

    tree_lines.append(f"📁 {root_name}/")
    _build(root, "", tree_lines, file_count)

    tree_text = "\n".join(tree_lines)

    return (
        f"# Directory Structure: {root_name}\n\n"
        f"## 📂 Directory Structure\n"
        f"```text\n"
        f"{tree_text}\n"
        f"```\n\n"
        f"---\n\n"
        f"## 📊 Statistics\n"
        f"- **Total Files in Tree:** {file_count[0]}\n"
        f"- **Mode:** Directory Structure Only (Tree Map)\n"
    )


def _build(directory: str, prefix: str, lines: list[str], file_count: list[int]) -> None:
    """遞迴輔助函式，沿用 AIExporter 風格：資料夾用 ├──，檔案用 └──。"""
    try:
        entries = sorted(os.scandir(directory), key=lambda e: (not e.is_dir(), e.name.lower()))
    except PermissionError:
        lines.append(f"{prefix}└── [存取被拒]")
        return

    dirs = [e for e in entries if e.is_dir(follow_symlinks=False)]
    files = [e for e in entries if not e.is_dir(follow_symlinks=False)]

    for entry in dirs:
        lines.append(f"{prefix}├── 📁 {entry.name}/")
        _build(entry.path, prefix + "│   ", lines, file_count)

    for entry in files:
        lines.append(f"{prefix}└── 📄 {entry.name}")
        file_count[0] += 1
