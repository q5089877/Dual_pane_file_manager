import os
import shutil
import time
from core.interfaces import ICompareView
from ui.workers.threads import CompareThread

class ComparePresenter:
    """MVP Presenter for CompareDialog. Handles folder comparison logic and sync operations."""
    def __init__(self, view: ICompareView, left_path: str, right_path: str):
        self.view = view
        self.left_path = left_path
        self.right_path = right_path
        self.thread = None

    def start_compare(self):
        """Starts the CompareThread to calculate differences in background."""
        if self.thread and self.thread.isRunning():
            self.thread.stop()
            self.thread.wait()
            
        self.thread = CompareThread(self.left_path, self.right_path)
        self.thread.progress.connect(self.view.show_progress)
        self.thread.finished_signal.connect(self.view.show_differences)
        self.thread.start()

    def run_sync(self, mode: str, selected_diffs: list):
        """Executes synchronization operations on selected differences."""
        if not selected_diffs:
            return
            
        if not self.view.ask_confirmation("確認同步", "確定要開始同步嗎？"):
            return
            
        trash_dir = os.path.join(self.right_path, ".sync_trash")
        success = 0
        errors = 0
        
        for d in selected_diffs:
            try:
                rel = d['rel_path']
                l_path = os.path.join(self.left_path, rel)
                r_path = os.path.join(self.right_path, rel)
                
                if mode == "L2R_UPDATE" and d['status'] in ['L_ONLY', 'DIFF']:
                    self._copy_item(l_path, r_path)
                    success += 1
                elif mode == "R2L_UPDATE" and d['status'] in ['R_ONLY', 'DIFF']:
                    self._copy_item(r_path, l_path)
                    success += 1
                elif mode == "L2R_MIRROR":
                    if d['status'] in ['L_ONLY', 'DIFF']:
                        self._copy_item(l_path, r_path)
                        success += 1
                    elif d['status'] == 'R_ONLY':
                        os.makedirs(trash_dir, exist_ok=True)
                        tp = os.path.join(trash_dir, os.path.basename(rel))
                        if os.path.exists(tp):
                            tp += f"_{int(time.time())}"
                        os.rename(r_path, tp)
                        success += 1
                elif mode == "R2L_MIRROR":
                    l_trash = os.path.join(self.left_path, ".sync_trash")
                    if d['status'] in ['R_ONLY', 'DIFF']:
                        self._copy_item(r_path, l_path)
                        success += 1
                    elif d['status'] == 'L_ONLY':
                        os.makedirs(l_trash, exist_ok=True)
                        tp = os.path.join(l_trash, os.path.basename(rel))
                        if os.path.exists(tp):
                            tp += f"_{int(time.time())}"
                        os.rename(l_path, tp)
                        success += 1
            except Exception:
                errors += 1
                
        self.view.show_sync_result(success, errors)

    def _copy_item(self, src, dst):
        """Internal helper to copy files or directories"""
        if os.path.isdir(src):
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)

    def cleanup(self):
        """Cleans up active threads."""
        if self.thread and self.thread.isRunning():
            self.thread.stop()
            self.thread.wait()
