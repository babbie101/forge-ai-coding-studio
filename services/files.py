import os
import tempfile
from datetime import datetime
from pathlib import Path
import streamlit as st
from utils.helpers import _rel_posix, safe_file_path

EXCLUDED_DIRS = {".git", "__pycache__", ".streamlit", ".pytest_cache", "node_modules", ".venv"}
WINDOWS_DEVICE_NAMES = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}

@st.cache_data(ttl=5, max_entries=32, show_spinner=False)
def _scan_tree_cached(root: str, max_depth: int):
    tree = {
        ".": {
            "id": ".", "type": "folder", "path": ".",
            "name": os.path.basename(root) or root, "children": [],
        }
    }
    for dirpath, dirnames, filenames in os.walk(root, onerror=lambda _error: None):
        depth = dirpath.count(os.sep) - root.count(os.sep)
        dirnames[:] = sorted(
            d for d in dirnames
            if not d.startswith(".") and d not in EXCLUDED_DIRS and d.casefold() not in WINDOWS_DEVICE_NAMES
        )
        parent_id = _rel_posix(dirpath, root) or "."
        visible_dirs = dirnames if depth < max_depth else []
        for d in visible_dirs:
            child_path = _rel_posix(os.path.join(dirpath, d), root)
            tree[child_path] = {"id": child_path, "type": "folder", "path": child_path,
                                "name": d, "children": []}
            tree[parent_id]["children"].append(child_path)
        for fn in sorted(filenames):
            if fn.startswith(".") or fn.endswith((".pyc", ".log", ".env")) or fn.casefold() in WINDOWS_DEVICE_NAMES:
                continue
            try:
                child_path = _rel_posix(os.path.join(dirpath, fn), root)
            except ValueError:
                # Ignore Windows pseudo-files that cannot be relativized.
                continue
            tree[child_path] = {"id": child_path, "type": "file", "path": child_path,
                                "name": fn, "children": []}
            tree[parent_id]["children"].append(child_path)
        if depth >= max_depth:
            dirnames[:] = []
    return tree


def scan_tree(root: str, max_depth: int = 4):
    """Return a short-lived cached workspace tree for responsive UI reruns."""
    resolved_root = str(Path(root).resolve())
    return _scan_tree_cached(resolved_root, max_depth)


def invalidate_scan_tree(root: str, max_depth: int = 4):
    """Invalidate a cached tree after a known workspace filesystem change."""
    _scan_tree_cached.clear(str(Path(root).resolve()), max_depth)


def save_workspace_file(root: str | Path, relative_path: str, content: str) -> Path:
    """Atomically save UTF-8 text to a validated path inside the workspace."""
    target = safe_file_path(root, relative_path)
    if target is None:
        raise ValueError(f"Invalid workspace path: {relative_path!r}")

    target.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            prefix=f".{target.name}.",
            suffix=".tmp",
            dir=target.parent,
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(content)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_path, target)
    except OSError:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise

    invalidate_scan_tree(root)
    return target


def build_preview_tree(plan: dict):
    tree = {
        ".": {
            "id": ".", "type": "folder", "path": ".",
            "name": "Project Root", "children": [],
        }
    }
    for folder in plan.get("folders", []):
        # Handle nested folders
        parts = folder.strip("/").split("/")
        current_id = "."
        for i, part in enumerate(parts):
            path = "/".join(parts[:i+1])
            if path not in tree:
                tree[path] = {"id": path, "type": "folder", "path": path, "name": part, "children": []}
                tree[current_id]["children"].append(path)
            current_id = path
    for f in plan.get("files", []):
        path = f["path"].strip("/")
        parts = path.split("/")
        filename = parts[-1]
        parent_path = "/".join(parts[:-1]) or "."
        if parent_path not in tree:
            # Create implied parents
            parent_parts = parent_path.split("/")
            curr = "."
            for i, p in enumerate(parent_parts):
                p_path = "/".join(parent_parts[:i+1])
                if p_path not in tree:
                    tree[p_path] = {"id": p_path, "type": "folder", "path": p_path, "name": p, "children": []}
                    tree[curr]["children"].append(p_path)
                curr = p_path
        tree[path] = {"id": path, "type": "file", "path": path, "name": filename, "children": []}
        tree[parent_path]["children"].append(path)
    return tree

def get_file_path(root: str, info: dict) -> Path:
    rel = info["path"]
    root_resolved = Path(root).resolve()
    if rel == ".":
        return root_resolved
    target = safe_file_path(root_resolved, rel)
    if target is None:
        raise ValueError(f"Invalid workspace path: {rel!r}")
    return target

def export_context_md(root, tree):
    root_resolved = Path(root).resolve()
    context_path = root_resolved / "CONTEXT.md"
    lines = ["# CONTEXT.md", "", f"Generated: {datetime.now().isoformat()}",
             f"Project root: `{root_resolved}`", "", "## File tree", ""]
    for node_id in sorted(tree.keys()):
        info = tree[node_id]
        icon = "📁" if info["type"] == "folder" else "📄"
        lines.append(f"- {icon} `{node_id}`")
    lines += ["", "## File previews", ""]
    for node_id in sorted(tree.keys()):
        info = tree[node_id]
        if info["type"] != "file":
            continue
        file_path = get_file_path(str(root_resolved), info)
        try:
            text = file_path.read_text(encoding="utf-8")
        except Exception:
            text = "<unreadable>"
        lines.append(f"### {node_id}\n```\n{text[:4000]}\n```\n")
    context_path.write_text("\n".join(lines), encoding="utf-8")
    invalidate_scan_tree(root_resolved)
    return str(context_path)
