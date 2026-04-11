import os
from typing import Callable, Optional

class AIExporterLogic:
    """
    Logic for AI Context Export.
    Handles recursive scanning, filtering, and Markdown generation.
    Does NOT depend on PyQt.
    """
    def __init__(self, root_path: str, config: dict, include_contents: bool = True):
        self.root_path = os.path.normpath(root_path)
        self.config = config
        self.include_contents = include_contents
        self.is_cancelled = False

    def run(self, 
            on_progress: Optional[Callable[[str, int, int], None]] = None,
            on_finished: Optional[Callable[[str], None]] = None,
            on_error: Optional[Callable[[str], None]] = None):
        try:
            # 1. Load settings (with defaults)
            whitelist = self.config.get("whitelist_exts", [".py", ".txt", ".md", ".json"])
            blacklist = self.config.get("blacklist_dirs", [".git", "node_modules", "__pycache__"])
            max_depth = self.config.get("max_depth", 5)
            size_limit_bytes = self.config.get("file_size_limit_kb", 100) * 1024
            total_limit_bytes = self.config.get("total_size_limit_mb", 2) * 1024 * 1024

            valid_files = []
            tree_lines = []
            
            # 2. First Pass: Build tree structure and collect files
            root_depth = self.root_path.count(os.sep)
            total_files_in_tree = 0
            
            for current_dir, dirnames, filenames in os.walk(self.root_path):
                if self.is_cancelled:
                    return

                # Calculate relative depth
                current_depth = current_dir.count(os.sep) - root_depth
                
                # Apply depth limit
                if current_depth >= max_depth:
                    dirnames.clear()
                
                # Filter blacklisted directories (in-place, case-insensitive)
                blacklist_lower = [b.lower() for b in blacklist]
                dirnames[:] = [d for d in dirnames if d.lower() not in blacklist_lower]

                # Add folder to tree
                indent = "│   " * (current_depth - 1) + "├── " if current_depth > 0 else ""
                folder_name = os.path.basename(current_dir) or self.root_path
                tree_lines.append(f"{indent}📁 {folder_name}/")

                # Add ALL files to the tree
                file_indent = "│   " * current_depth + "└── "
                for f in sorted(filenames):
                    tree_lines.append(f"{file_indent}📄 {f}")
                    total_files_in_tree += 1
                    # Only collect whitelisted files for content reading
                    if self.include_contents:
                        ext = os.path.splitext(f)[1].lower()
                        if ext in whitelist:
                            valid_files.append(os.path.join(current_dir, f))

            # 3. Assemble Markdown header and tree
            md_output = [
                f"# Directory Structure: {os.path.basename(self.root_path)}\n\n",
                "## 📂 Directory Structure\n",
                "```text\n" + "\n".join(tree_lines) + "\n```\n\n",
                "--- \n\n"
            ]

            # 4. Second Pass: Read file contents (Only if requested)
            total_whitelisted = len(valid_files)
            included_count = 0
            skipped_size_count = 0
            skipped_limit_count = 0
            error_count = 0

            if self.include_contents:
                md_output.append("## 💻 File Contents\n\n")
                current_total_size = 0

                for index, file_path in enumerate(valid_files, 1):
                    if self.is_cancelled:
                        return
                    
                    filename = os.path.basename(file_path)
                    rel_path = os.path.relpath(file_path, self.root_path)
                    if on_progress:
                        on_progress(filename, index, total_whitelisted)

                    # Check file size limit
                    try:
                        file_size = os.path.getsize(file_path)
                        if file_size > size_limit_bytes:
                            skipped_size_count += 1
                            continue

                        # Read content
                        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                            content = f.read()
                            
                            # Add to total size counter
                            content_bytes = content.encode('utf-8')
                            if current_total_size + len(content_bytes) > total_limit_bytes:
                                skipped_limit_count = total_whitelisted - index + 1
                                break
                            
                            current_total_size += len(content_bytes)
                            included_count += 1

                            # Detect language for Markdown block
                            ext_tag = os.path.splitext(filename)[1].replace(".", "") or ""
                            md_output.append(f"### File: {rel_path}\n```{ext_tag}\n{content}\n```\n\n")
                    except Exception:
                        error_count += 1
                        continue
            else:
                if on_progress:
                    on_progress("完成", 100, 100)

            # 5. Add Statistics Summary
            md_output.append("---\n\n## 📊 Statistics\n")
            md_output.append(f"- **Total Files in Tree:** {total_files_in_tree}\n")
            if self.include_contents:
                md_output.append(f"- **Whitelisted for Content:** {total_whitelisted}\n")
                md_output.append(f"- **Files Included in Report:** {included_count}\n")
                if skipped_size_count > 0:
                    md_output.append(f"- **Files Skipped (too large):** {skipped_size_count}\n")
                if skipped_limit_count > 0:
                    md_output.append(f"- **Files Skipped (total limit reached):** {skipped_limit_count}\n")
                if error_count > 0:
                    md_output.append(f"- **Errors (read failed):** {error_count}\n")
            else:
                md_output.append(f"- **Mode:** Directory Structure Only (Tree Map)\n")
            
            # 6. Success
            if on_finished:
                on_finished("".join(md_output))

        except Exception as e:
            if on_error:
                on_error(str(e))

    def cancel(self):
        """Request execution to stop."""
        self.is_cancelled = True
