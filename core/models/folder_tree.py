"""
folder_tree.py — 遞迴產生資料夾樹狀圖（Markdown 格式，含 📁/📄 emoji）
純邏輯模組，無 Qt 依賴。
"""
import os


def count_items(root: str, blacklist: list[str] | None = None, max_depth: int = 10) -> int:
    """快速計算 root 下的總項目數（資料夾 + 檔案），套用黑名單與深度限制。"""
    blacklist_lower = {b.lower() for b in (blacklist or [])}
    root_depth = root.count(os.sep)
    total = 0
    for dirpath, dirs, files in os.walk(root):
        current_depth = dirpath.count(os.sep) - root_depth
        if current_depth >= max_depth:
            dirs.clear()
            continue
        dirs[:] = [d for d in dirs if d.lower() not in blacklist_lower]
        total += len(dirs) + len(files)
    return total


def generate_tree(root: str, blacklist: list[str] | None = None, max_depth: int = 10) -> str:
    """
    遞迴掃描 root，回傳 Markdown 格式的樹狀圖字串。
    blacklist: 要略過的資料夾名稱（大小寫不分）。
    max_depth: 最大遞迴深度。
    """
    blacklist_lower = {b.lower() for b in (blacklist or [])}
    root_name = os.path.basename(root.rstrip("/\\")) or root
    tree_lines: list[str] = []
    file_count = [0]

    tree_lines.append(f"📁 {root_name}/")
    _build(root, "", tree_lines, file_count, blacklist_lower, max_depth, 0)

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


def _build(directory: str, prefix: str, lines: list[str], file_count: list[int],
           blacklist: set[str], max_depth: int, current_depth: int) -> None:
    if current_depth >= max_depth:
        return
    try:
        entries = sorted(os.scandir(directory), key=lambda e: (not e.is_dir(), e.name.lower()))
    except PermissionError:
        lines.append(f"{prefix}└── [存取被拒]")
        return

    dirs = [e for e in entries if e.is_dir(follow_symlinks=False) and e.name.lower() not in blacklist]
    files = [e for e in entries if not e.is_dir(follow_symlinks=False)]

    for entry in dirs:
        lines.append(f"{prefix}├── 📁 {entry.name}/")
        _build(entry.path, prefix + "│   ", lines, file_count, blacklist, max_depth, current_depth + 1)

    for entry in files:
        lines.append(f"{prefix}└── 📄 {entry.name}")
        file_count[0] += 1
