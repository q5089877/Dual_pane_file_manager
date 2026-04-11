"""
undo_stack.py — 記錄最近 N 次可復原的檔案操作。
純邏輯模組，無 Qt 依賴。
"""
from dataclasses import dataclass, field


@dataclass
class UndoEntry:
    kind: str          # "move" | "rename" | "copy"
    pairs: list        # [(src_path, dst_path), ...]


class UndoStack:
    MAX = 10

    def __init__(self) -> None:
        self._stack: list[UndoEntry] = []

    def push(self, entry: UndoEntry) -> None:
        self._stack.append(entry)
        if len(self._stack) > self.MAX:
            self._stack.pop(0)

    def pop(self) -> UndoEntry | None:
        return self._stack.pop() if self._stack else None

    def is_empty(self) -> bool:
        return not self._stack

    def peek_kind(self) -> str | None:
        return self._stack[-1].kind if self._stack else None
