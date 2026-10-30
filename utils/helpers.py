import os
import re
from pathlib import Path

def _rel_posix(path: str, root: str) -> str:
    return os.path.relpath(path, root).replace("\\", "/")

def safe_file_path(root, filename):
    if not filename:
        return None
    root_resolved = Path(root).resolve()
    # Normalize slashes and check path escape attempts
    norm_filename = str(filename).replace("\\", "/").strip()
    if norm_filename.startswith(("/", "\\")) or ".." in norm_filename or ":" in norm_filename:
        return None
    target = (root_resolved / norm_filename).resolve()
    try:
        # Guarantee target is inside root_resolved
        target.relative_to(root_resolved)
        return target
    except ValueError:
        return None

def _comment_header_for(path, description):
    ext = path.suffix.lower()
    if ext in {".py", ".pyx"}:
        return f"# {description}\n"
    if ext in {".js", ".ts", ".jsx", ".tsx", ".java", ".c", ".cpp", ".go", ".rs"}:
        return f"// {description}\n"
    if ext == ".html":
        return f"<!-- {description} -->\n"
    if ext == ".css":
        return f"/* {description} */\n"
    return f"# {description}\n"

def pick_folder_with_dialog():
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        folder = filedialog.askdirectory()
        root.destroy()
        return folder if folder else None
    except Exception as e:
        return None
