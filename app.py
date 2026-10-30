import os
import queue
import time
import re
import json
import html
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
import streamlit as st
from openai import OpenAI
try:
    from streamlit_flow import (
        StreamlitFlowEdge,
        StreamlitFlowNode,
        StreamlitFlowState,
        streamlit_flow,
    )
    from streamlit_flow.layouts import ManualLayout
    STREAMLIT_FLOW_AVAILABLE = True
except ImportError:
    STREAMLIT_FLOW_AVAILABLE = False
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from core.ai import (
    _ai_providers, available_chat_models, ai_chat, 
    generate_architecture, run_ai_chat, apply_patch, 
    extract_code_block, extract_code_blocks, extract_patch_blocks, generate_file_content,
    generate_diff_html, list_available_ollama_models, AIProviderError,
    generate_roadmap, ask_whats_next,
)
from core.state import DEFAULTS, SessionStateManager
from core.workspace_progress import load_project_progress, save_project_progress
from services.files import (
    scan_tree, invalidate_scan_tree, build_preview_tree, export_context_md,
    get_file_path, safe_file_path, save_workspace_file,
)
from ui.theme_forge import inject_theme
from ui.bitmap_animation import render_datastream_pulse
from ui.components import (
    render_front_page,
    render_onboarding_hub, show_node_editor, render_moodboard, render_status_bar,
    render_roadmap, render_ghost_writer, render_live_output_window,
)
from utils.helpers import _rel_posix, _comment_header_for, pick_folder_with_dialog

APP_ROOT = os.path.dirname(os.path.abspath(__file__))
PROJECT_PLAN_FILENAME = "PROJECT_PLAN.md"
CHAT_HISTORY_PAGE_SIZE = 30


def _project_progress_snapshot() -> dict:
    current_step = st.session_state.get("current_step")
    return {
        "project_idea": st.session_state.get("project_idea", ""),
        "architecture_plan": st.session_state.get("architecture_plan"),
        "plan_steps": st.session_state.get("plan_steps", []),
        "short_plan_steps": st.session_state.get("short_plan_steps", []),
        "roadmap_expanded": st.session_state.get("roadmap_expanded", False),
        "current_step_id": current_step.get("id") if isinstance(current_step, dict) else None,
        "plan_scaffolded": st.session_state.get("plan_scaffolded", True),
        "plan_status": st.session_state.get("plan_status", "in_progress"),
    }


def _persist_project_progress(workspace: str) -> bool:
    try:
        save_project_progress(workspace, _project_progress_snapshot())
    except (OSError, TypeError, ValueError) as error:
        st.session_state["roadmap_error"] = f"Could not save roadmap progress: {error}"
        return False
    st.session_state["roadmap_error"] = None
    return True


def _set_current_roadmap_step(step: dict, workspace: str) -> None:
    st.session_state["current_step"] = step
    st.session_state["roadmap_step_selector"] = step.get("id")
    _persist_project_progress(workspace)


def _toggle_roadmap_step(workspace: str, steps: list[dict]) -> None:
    selected_id = st.session_state.get("roadmap_step_selector")
    selected_step = next(
        (step for index, step in enumerate(steps)
         if step.get("id", f"step_{index}") == selected_id),
        None,
    )
    if not selected_step:
        return
    selected_step["status"] = (
        "planned" if selected_step.get("status") == "done" else "done"
    )
    next_step = next(
        (step for step in steps if step.get("status") != "done"),
        selected_step,
    )
    _set_current_roadmap_step(next_step, workspace)


def _persist_chat_roadmap_selection(workspace: str, steps: list[dict]) -> None:
    selected_id = st.session_state.get("roadmap_step_selector")
    selected_step = next(
        (step for index, step in enumerate(steps)
         if step.get("id", f"step_{index}") == selected_id),
        None,
    )
    if selected_step:
        _set_current_roadmap_step(selected_step, workspace)


def _open_workspace_chat() -> None:
    st.session_state["workspace_section"] = "Chat"


def _restore_project_progress(workspace: str) -> None:
    """Restore project roadmap once when switching to a workspace."""
    resolved_workspace = str(Path(workspace).resolve())
    if st.session_state.get("roadmap_loaded_for") == resolved_workspace:
        return

    try:
        progress = load_project_progress(resolved_workspace)
    except (OSError, ValueError) as error:
        progress = None
        st.session_state["roadmap_error"] = f"Could not load saved roadmap progress: {error}"

    if progress is None:
        if not st.session_state.get("roadmap_error"):
            st.session_state["roadmap_error"] = None
        if not st.session_state.get("create_from_idea", False):
            st.session_state["project_idea"] = ""
        st.session_state["architecture_plan"] = None
        st.session_state["plan_steps"] = []
        st.session_state["short_plan_steps"] = []
        st.session_state["roadmap_expanded"] = False
        st.session_state["current_step"] = None
        st.session_state.pop("roadmap_step_selector", None)
        st.session_state["plan_scaffolded"] = True
        st.session_state["plan_status"] = "in_progress"
    else:
        steps = progress.get("plan_steps", [])
        st.session_state["project_idea"] = progress.get("project_idea", "")
        st.session_state["architecture_plan"] = progress.get("architecture_plan")
        st.session_state["plan_steps"] = steps
        st.session_state["short_plan_steps"] = progress.get("short_plan_steps", [])
        st.session_state["roadmap_expanded"] = bool(progress.get("roadmap_expanded", False))
        st.session_state["plan_scaffolded"] = bool(progress.get("plan_scaffolded", True))
        st.session_state["plan_status"] = progress.get("plan_status", "in_progress")
        current_step_id = progress.get("current_step_id")
        st.session_state["current_step"] = next(
            (step for step in steps if step.get("id") == current_step_id),
            steps[0] if steps else None,
        )
        current_step = st.session_state["current_step"]
        if current_step:
            st.session_state["roadmap_step_selector"] = current_step.get("id")
        st.session_state["roadmap_error"] = None

    st.session_state["roadmap_loaded_for"] = resolved_workspace


# ---- AI Setup ----
def _ollama_is_running() -> bool:
    """True only after a successful probe to the configured Ollama server."""
    try:
        return bool(list_available_ollama_models())
    except Exception:
        return False


def _should_auto_select_ollama(provider_override):
    """Prefer local Ollama only when the user has not explicitly chosen a provider."""
    return (
        _ollama_is_running()
        and not provider_override
        and not os.getenv("FORGE_AI_PROVIDER", "").strip()
    )


def _resolve_provider():
    """Resolve an explicit provider preference before automatic detection."""
    env = dict(os.environ)
    preferred_provider = env.get("FORGE_AI_PROVIDER", "").strip().lower()
    if preferred_provider in _ai_providers:
        return preferred_provider

    ollama_url = env.get("OLLAMA_BASE_URL", "http://localhost:11434/v1/")
    is_local_ollama = "localhost" in ollama_url or "127.0.0.1" in ollama_url
    # Prefer a reachable local model over cloud credentials to avoid
    # accidental rate-limited requests or sending project context remotely.
    if _ollama_is_running():
        return "ollama"
    # A local Ollama key does not start a server. Prefer it only once that
    # server responds; a remote gateway is assumed reachable and may require
    # the configured key.
    if env.get("OLLAMA_API_KEY") and (not is_local_ollama or _ollama_is_running()):
        return "ollama"
    if env.get("OPENROUTER_API_KEY"):
        return "openrouter"
    if env.get("NEBIUS_API_KEY", "").strip():
        return "nebius"
    if env.get("GROQ_API_KEY"):
        return "groq"
    return None


def _load_api_key(provider: str | None = None):
    """Load the key belonging to one provider, never a key from another provider."""
    if not provider:
        return None
    key_env = _ai_providers[provider]["key_env"]
    return os.getenv(key_env) or None


def _get_active_provider():
    """Resolve the active provider: UI override > env detection.

    The UI provider toggle stores its selection in st.session_state
    under ``provider_override``, which updates on each rerun.
    """
    if st.session_state.get("provider_override"):
        return st.session_state["provider_override"]
    return _resolve_provider()


def _get_provider_config():
    """Return the full provider config for the active provider.

    Resolved at runtime so UI overrides are honoured on every rerun.
    """
    provider = _get_active_provider()
    if not provider:
        return {
            "provider": None,
            "base_url": None,
            "api_key": None,
            "label": "No AI provider configured",
            "models": {},
            "default_model": None,
        }
    cfg = _ai_providers[provider]
    api_key = _load_api_key(provider)
    models = cfg["models"]
    if provider == "ollama":
        installed = list_available_ollama_models()
        # Native Ollama does not require authentication, while the OpenAI SDK
        # requires a non-empty value. This value never leaves the local server.
        api_key = api_key or "ollama-local"
        models = {installed_model: installed_model for installed_model in installed} or models
    # Default Groq model (no "openai/" prefix; that is an OpenRouter-only
    # convention and resolves to 404 on api.groq.com). "llama-3.3-70b-versatile"
    # is the verified Groq model from the provider config.
    if provider == "groq":
        # "llama-3.3-70b-versatile" is the verified Groq model (the
        # "openai/" prefixed name above is an OpenRouter convention and
        # resolves to 404 on api.groq.com).
        default_model = "llama-3.3-70b-versatile"
    else:
        default_model = next(iter(models.values()))
    return {
        "provider": provider,
        "base_url": os.getenv("OLLAMA_BASE_URL", cfg["base_url"]) if provider == "ollama" else cfg["base_url"],
        "api_key": api_key,
        "label": "FORGE",
        "models": models,
        "default_model": default_model,
    }


# Provider config is resolved at call time (not module level) so that
# UI provider overrides (st.session_state["provider_override"]) take
# effect immediately on every rerun.
def _active_provider():
    """Return the provider config, freshly resolved on every call."""
    return _get_provider_config()


def _model_for_provider(selected_model, provider_config):
    """Keep a saved model selection compatible when switching providers."""
    if selected_model in provider_config["models"].values():
        return selected_model
    return provider_config["default_model"]


# ---- Watchdog ----
class ChangeLogger(FileSystemEventHandler):
    def __init__(self, event_queue: queue.Queue, root: str):
        self.event_queue = event_queue
        self.root = root
    def on_any_event(self, event):
        if event.is_directory: return
        rel = os.path.relpath(event.src_path, self.root)
        self.event_queue.put(f"{event.event_type:>8}  {rel}")


def start_observer(root: str):
    """Start one watcher for the active workspace and retire any old watcher."""
    # Skip observer when running under AppTest (test dirs contain 'pytest' or 'tmp')
    root_str = str(root)
    if "pytest" in root_str or "tmp" in root_str.lower() or "Temp" in root_str:
        return None, queue.Queue()
    
    root = str(Path(root).resolve())
    active = st.session_state.get("workspace_observer")
    if active and active["root"] == root and active["observer"].is_alive():
        return active["observer"], active["queue"]

    for item in st.session_state.get("started_observers", []):
        observer = item.get("observer")
        if observer:
            observer.stop()
            observer.join(timeout=1)

    event_queue = queue.Queue()
    observer = Observer()
    observer.schedule(ChangeLogger(event_queue, root), root, recursive=True)
    observer.start()
    active = {"root": root, "observer": observer, "queue": event_queue}
    st.session_state["workspace_observer"] = active
    st.session_state["started_observers"] = [active]
    return observer, event_queue


# ---- Tree / Layout Helpers ----
def layout_positions(tree: dict, x_step=170, y_step=120, y_offset=80):
    leaf_counts = {}
    def count_leaves(node_id):
        children = tree[node_id]["children"]
        leaf_counts[node_id] = 1 if not children else sum(count_leaves(c) for c in children)
        return leaf_counts[node_id]
    total = count_leaves(".")
    root_x = total * x_step / 2
    positions = {".": (root_x, y_offset)}
    def place(node_id, x, y):
        children = tree[node_id]["children"]
        if not children: return
        start = x - (leaf_counts[node_id] - 1) * x_step / 2
        for child_id in children:
            cx = start + (leaf_counts[child_id] - 1) * x_step / 2
            cy = y + y_step
            positions[child_id] = (cx, cy)
            place(child_id, cx, cy)
            start += leaf_counts[child_id] * x_step
    place(".", root_x, y_offset)
    return positions


def build_flow_state(tree: dict, positions: dict, selected_id=None, primary=None, target_dir=""):
    nodes, edges = [], []
    steps = st.session_state.get("plan_steps", [])
    current_step = st.session_state.get("current_step")
    completed_steps = [s.get("id") for s in steps if s.get("status") == "done"]

    for node_id, info in tree.items():
        x, y = positions.get(node_id, (0, 0))
        kind = info["type"]
        is_primary = bool(primary and (node_id == primary or info["name"] == primary))
        
        # Determine code & roadmap status
        # Node status: blue=scaffolded, green=code-written, purple=in-progress, grey=planned-only
        dot_color = "#3b82f6"
        has_content = False
        if kind == "file" and target_dir:
            try:
                fp = safe_file_path(target_dir, info.get("path", node_id))
                if fp and fp.is_file():
                    content = fp.read_text(encoding="utf-8").strip()
                    # A file has written code if it has more than just the default header comment
                    has_content = len(content) > 60 and not content.startswith("# ") or "\ndef " in content or "\nclass " in content or "\nimport " in content
            except Exception:
                has_content = False

        is_step_target = current_step and node_id in current_step.get("suggested_file_paths", [])
        
        if is_primary:
            bg, border, bw = "#111111", "#3b82f6", "2px"
            dot_color = "#3b82f6"
        elif kind == "folder":
            # Check if any children exist and have content
            bg, border, bw = "#111111", "#22c55e" if info.get("children") else "#334155", "1px"
            dot_color = "#22c55e" if info.get("children") else "#64748b"
        else:
            if is_step_target:
                bg, border, bw = "#161b22", "#a855f7", "2px"
                dot_color = "#a855f7" # purple = in-progress
            elif has_content:
                bg, border, bw = "#111111", "#22c55e", "1px"
                dot_color = "#22c55e" # green = code-written
            else:
                bg, border, bw = "#111111", "#3b82f6", "1px"
                dot_color = "#3b82f6" # blue = scaffolded

        is_selected = node_id == selected_id
        label_text = info["name"] if len(info["name"]) <= 22 else f"{info['name'][:19]}…"
        dot_char = "●"
        nodes.append(StreamlitFlowNode(
            id=node_id, pos=(x, y),
            data={"content": f"{dot_char} {label_text}", "kind": kind, "path": info["path"]},
            node_type="default", source_position="bottom", target_position="top",
            selectable=True, selected=is_selected,
            style={"backgroundColor": bg, "border": f"{bw} solid {border}",
                   "borderRadius": "8px", "padding": "6px", "color": "#e2e8f0",
                   "fontFamily": "'JetBrains Mono', monospace", "fontSize": 11,
                   "boxShadow": "0 2px 4px rgba(0,0,0,.12)",
                   "outline": "2px solid #93c5fd" if is_selected else "none"},
        ))
        for child_id in info["children"]:
            edges.append(StreamlitFlowEdge(
                id=f"{node_id}-{child_id}", source=node_id, target=child_id,
                marker_end={"type": "arrowclosed"},
                style={"stroke": "#3b82f6", "strokeWidth": 1.5, "filter": "drop-shadow(0 0 3px rgba(59,130,246,0.5))"},
            ))
    return StreamlitFlowState(nodes, edges, selected_id=selected_id)


def render_canvas_navigator(tree: dict, selected_id: str | None) -> str | None:
    """Provide a dependable keyboard-friendly companion to graph node clicks."""
    folders = sum(node["type"] == "folder" for node in tree.values())
    files = len(tree) - folders
    st.sidebar.subheader("Canvas navigator")
    st.sidebar.caption(f"{folders} folders · {files} files")
    options = list(tree.keys())
    active = selected_id if selected_id in tree else "."
    if "requested_node_focus" not in st.session_state:
        st.session_state["canvas_node_picker"] = active

    def request_node_focus() -> None:
        st.session_state["requested_node_focus"] = st.session_state["canvas_node_picker"]

    st.sidebar.selectbox(
        "Focus node",
        options,
        key="canvas_node_picker",
        format_func=lambda item: f"[{tree[item]['type'].upper()}] {item}",
        on_change=request_node_focus,
    )
    if st.sidebar.button("Reset canvas focus", icon=":material/center_focus_strong:", key="reset_canvas_focus", width="stretch"):
        st.session_state["selected_id"] = None
        st.session_state["flow_timestamp"] = int(time.time() * 1000)
        st.rerun()

    # Step navigation in sidebar
    steps = st.session_state.get("plan_steps", [])
    if steps:
        st.sidebar.markdown('<div class="recent-projects-header" style="margin-top:12px;">Roadmap Navigation</div>', unsafe_allow_html=True)
        cur = st.session_state.get("current_step")
        cur_idx = next((i for i, s in enumerate(steps) if s.get("id") == cur.get("id")), 0) if cur else 0
        p_col, n_col = st.sidebar.columns(2)
        with p_col:
            if st.button("Previous", key="prev_step_btn", disabled=(cur_idx <= 0), width="stretch", icon=":material/arrow_back:"):
                st.session_state["current_step"] = steps[cur_idx - 1]
                st.rerun()
        with n_col:
            if st.button("Next", key="next_step_btn", disabled=(cur_idx >= len(steps) - 1), width="stretch", icon=":material/arrow_forward:"):
                st.session_state["current_step"] = steps[cur_idx + 1]
                st.rerun()

    requested = st.session_state.pop("requested_node_focus", None)
    if requested is None:
        return selected_id
    return None if requested == "." else requested


def scaffold_project(root, plan, project_idea=""):
    root_path = Path(root).resolve()
    planned_folders = []
    for folder in plan.get("folders", []):
        if not isinstance(folder, str):
            raise ValueError("Every planned folder must be a path string.")
        folder_path = safe_file_path(root_path, folder)
        if folder_path is None:
            continue
        if folder_path.exists() and not folder_path.is_dir():
            raise FileExistsError(f"Cannot create planned folder because a file already exists there: `{folder}`")
        planned_folders.append(folder_path)

    planned_files = []
    for file_info in plan.get("files", []):
        if not isinstance(file_info, dict) or not isinstance(file_info.get("path"), str):
            raise ValueError("Every planned file must have a path string.")
        target = safe_file_path(root_path, file_info["path"])
        if target is None:
            raise ValueError(f"Invalid planned file path: {file_info['path']!r}")
        planned_files.append((target, file_info))

    project_plan_path = safe_file_path(root_path, PROJECT_PLAN_FILENAME)
    output_paths = [target for target, _ in planned_files] + [project_plan_path]
    normalized_outputs = [str(path).casefold() for path in output_paths]
    if len(normalized_outputs) != len(set(normalized_outputs)):
        raise ValueError("The plan contains duplicate output paths.")
    existing_outputs = [path for path in output_paths if path.exists()]
    if existing_outputs:
        conflicts = ", ".join(
            f"`{path.relative_to(root_path).as_posix()}`" for path in existing_outputs
        )
        raise FileExistsError(f"Scaffolding would overwrite existing files: {conflicts}")
    for target, _ in planned_files:
        for parent in target.parents:
            if parent == root_path:
                break
            if parent.exists() and not parent.is_dir():
                raise FileExistsError(
                    f"Cannot create `{target.relative_to(root_path).as_posix()}` because "
                    f"`{parent.relative_to(root_path).as_posix()}` is a file."
                )

    root_path.mkdir(parents=True, exist_ok=True)
    for folder_path in planned_folders:
        folder_path.mkdir(parents=True, exist_ok=True)
    for target, file_info in planned_files:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(_comment_header_for(target, file_info.get("description", "")), encoding="utf-8")
    project_plan_path.write_text(
        f"# {plan.get('summary','Project')}\n\n## Vision\n{project_idea}\n\n## Files\n"
        + "\n".join(f"- `{file_info['path']}`: {file_info.get('description','')}" for _, file_info in planned_files) + "\n",
        encoding="utf-8")
    invalidate_scan_tree(root_path)


# ---- UI Callbacks ----
def on_browse_existing():
    picked = pick_folder_with_dialog()
    if picked:
        st.session_state["existing_path_input"] = picked
        st.session_state["existing_path"] = picked
        add_recent_project(picked)


def on_browse_new():
    picked = pick_folder_with_dialog()
    if picked:
        st.session_state["new_parent_input"] = picked
        st.session_state["new_parent"] = picked
        add_recent_project(picked)


def add_recent_project(path):
    """Add a workspace path to the recent-projects list (max 10 entries)."""
    recent = st.session_state.get("recent_projects", [])
    if path in recent:
        recent.remove(path)
    recent.insert(0, path)
    if len(recent) > 10:
        recent = recent[:10]
    st.session_state["recent_projects"] = recent


def apply_ai_response(target_dir, selected_id, text, plan=None):
    patches = extract_patch_blocks(text)
    blocks = extract_code_blocks(text)
    written, errors = [], []
    for filename_hint, search, replace in patches:
        ok, msg_p = apply_patch(target_dir, selected_id, search, replace, filename_hint)
        (written.append(f"patched {msg_p}") if ok else errors.append(msg_p))
    for _lang, code, filename_hint in blocks:
        target_name = filename_hint or selected_id
        if not target_name:
            if plan and isinstance(plan, dict) and plan.get("files"):
                first_f = plan["files"][0]
                target_name = first_f.get("path") if isinstance(first_f, dict) else str(first_f)
            else:
                target_name = "app.py" if (_lang and "py" in _lang) else "main.py"
        target_path = safe_file_path(target_dir, target_name)
        if target_path is None:
            errors.append(f"Invalid filename hint: `{target_name}`")
            continue
        try:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            save_workspace_file(target_dir, target_name, code)
            rel = os.path.relpath(target_path.resolve(), Path(target_dir).resolve())
            written.append(rel.replace("\\", "/"))
        except Exception as e:
            errors.append(f"Failed to write `{target_name}`: {e}")

    if written:
        invalidate_scan_tree(target_dir)
    
    if written and not errors:
        return {"type": "success", "message": f"Auto-Applied {len(written)} file(s): {'; '.join(written)}", "files": written}
    elif written and errors:
        return {"type": "warning", "message": f"Auto-Applied {len(written)} file(s), but some failed: {'; '.join(errors)}", "files": written}
    elif errors:
        return {"type": "error", "message": "; ".join(errors)}
    return None


def _build_chat_context(target_dir, tree, selected_id):
    """Include the selected file and a few project-level docs, not every source file."""
    root = Path(target_dir)
    parts = []
    selected_file = tree.get(selected_id) if selected_id else None
    selected_path = None
    remaining = 12000

    if selected_file and selected_file.get("type") == "file":
        selected_path = selected_file.get("path", selected_id)
        path = safe_file_path(root, selected_path)
        if path and path.is_file():
            try:
                content = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as error:
                st.warning(f"Could not read `{selected_path}` for chat context: {error}")
            else:
                section = f"--- ACTIVE FILE: {selected_path} ---\n{content[:9000]}"
                parts.append(section)
                remaining -= len(section)

    for relative_path in (
        "README.md",
        "PROJECT_PLAN.md",
        "requirements.txt",
        "pyproject.toml",
        "package.json",
    ):
        if remaining <= 0 or relative_path == selected_path:
            continue
        info = tree.get(relative_path)
        if not info or info.get("type") != "file":
            continue
        path = safe_file_path(root, relative_path)
        if not path or not path.is_file():
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            st.warning(f"Could not read `{relative_path}` for chat context: {error}")
            continue
        section = f"--- {relative_path} ---\n{content[:min(1800, remaining)]}"
        parts.append(section)
        remaining -= len(section)

    return "\n\n".join(parts)


def _apply_chat_response(target_dir, selected_id, text, plan=None):
    result = apply_ai_response(target_dir, selected_id, text, plan=plan)
    if not result:
        st.info("This reply has no file changes to apply.")
        return
    st.session_state["apply_status"] = result
    if result["type"] == "error":
        st.error(result["message"])
        return

    files = result.get("files", [])
    st.session_state["last_patch_files"] = files
    st.session_state["live_reload_key"] = int(time.time() * 1000)
    st.session_state["flow_timestamp"] = int(time.time() * 1000)
    st.session_state["preview_update_glow"] = True
    if files:
        first_file = files[0].removeprefix("patched ")
        if safe_file_path(target_dir, first_file):
            st.session_state["selected_id"] = first_file
    st.toast(result["message"], icon=":material/check_circle:")
    st.rerun()


def _render_assistant_message(target_dir, selected_id, message, index, auto_apply):
    text = message["content"]
    blocks = extract_code_blocks(text)
    patches = extract_patch_blocks(text)
    if blocks:
        language, code, filename_hint = blocks[0]
        filename = filename_hint or selected_id or (
            "app.py" if language in {"python", "py"} else "main.txt"
        )
        st.code(code, language=language or "python")
        text_part = re.sub(r"```[\s\S]*?```", "", text).strip()
        if patches:
            text_part = re.sub(
                r"(?:^[ \t]*(?:###|(?:#\s*)?(?:filename|file):).*?\n)?"
                r"^[ \t]*<<<<<<< SEARCH\s*?\n.*?\n[ \t]*=======\s*?\n"
                r".*?\n[ \t]*>>>>>>> REPLACE\s*$",
                "",
                text_part,
                flags=re.MULTILINE | re.DOTALL,
            ).strip()
        if text_part:
            st.markdown(text_part)
        if not auto_apply:
            save_col, run_col, apply_col = st.columns(3)
            target_path = safe_file_path(target_dir, filename)
            if target_path is None:
                st.error("The generated filename is not valid for this workspace.")
            else:
                with save_col:
                    if st.button(
                        f"Save {filename}",
                        key=f"save_response_{index}_{hash(code) & 0xffffffff}",
                        type="primary",
                        icon=":material/save:",
                        width="stretch",
                    ):
                        target_path.parent.mkdir(parents=True, exist_ok=True)
                        save_workspace_file(target_dir, filename, code)
                        st.session_state["flow_timestamp"] = int(time.time() * 1000)
                        st.session_state["live_reload_key"] = int(time.time() * 1000)
                        st.session_state["preview_update_glow"] = True
                        st.session_state["selected_id"] = filename
                        st.toast(f"Saved {filename}", icon=":material/check_circle:")
                        st.rerun()
                with run_col:
                    if st.button(
                        f"Save & run {filename}",
                        key=f"preview_{index}",
                        icon=":material/play_arrow:",
                        width="stretch",
                    ):
                        target_path.parent.mkdir(parents=True, exist_ok=True)
                        save_workspace_file(target_dir, filename, code)
                        st.session_state["selected_id"] = filename
                        st.session_state["live_reload_key"] = int(time.time() * 1000)
                        st.session_state["preview_update_glow"] = True
                        if target_path.suffix.lower() in {
                            ".html", ".htm", ".xhtml", ".py", ".md", ".markdown"
                        }:
                            st.session_state["preview_entry_file"] = filename
                        if target_path.suffix.lower() == ".py":
                            st.session_state["auto_run_file"] = filename
                        st.rerun()
                with apply_col:
                    if st.button(
                        "Apply changes",
                        key=f"apply_response_{index}",
                        icon=":material/done_all:",
                        width="stretch",
                        help="Write the AI-generated file or patch into your workspace.",
                    ):
                        _apply_chat_response(
                            target_dir,
                            selected_id,
                            text,
                            plan=st.session_state.get("architecture_plan"),
                        )
    elif patches:
        explanation = re.sub(
            r"(?:^[ \t]*(?:###|(?:#\s*)?(?:filename|file):).*?\n)?"
            r"^[ \t]*<<<<<<< SEARCH\s*?\n.*?\n[ \t]*=======\s*?\n"
            r".*?\n[ \t]*>>>>>>> REPLACE\s*$",
            "",
            text,
            flags=re.MULTILINE | re.DOTALL,
        ).strip()
        if explanation:
            st.markdown(explanation)
        for hint, search, replacement in patches:
            st.caption(f"Proposed edit: `{hint or selected_id or 'selected file'}`")
            with st.expander("Review patch", expanded=False):
                before_col, after_col = st.columns(2)
                with before_col:
                    st.markdown("**Find**")
                    st.code(search)
                with after_col:
                    st.markdown("**Replace with**")
                    st.code(replacement)
        if not auto_apply and st.button(
            "Apply patch",
            key=f"apply_patch_{index}",
            icon=":material/done_all:",
            width="content",
        ):
            _apply_chat_response(
                target_dir,
                selected_id,
                text,
                plan=st.session_state.get("architecture_plan"),
            )
    else:
        st.markdown(text)


@st.fragment
def _render_ai_assistant(target_dir, tree, selected_id, model, api_key, base_url, provider):
    """The focused coding surface: history, one response, automatic hot-apply pipeline."""
    c_title, c_wrap, c_toggle = st.columns([2.0, 1.0, 1.0], vertical_alignment="center")
    with c_title:
        st.subheader("Forge: AI Coding Studio", icon=":material/terminal:")
        if selected_id and selected_id in tree and tree[selected_id]["type"] == "file":
            st.caption(f"Context: `{selected_id}`")
        else:
            st.caption("Describe a change in plain language. Roadmap steps are optional.")
        if not api_key:
            st.info(
                "AI help is not configured. You can still add, edit, and preview files in Code; "
                "connect a provider only when you want AI assistance.",
                icon=":material/edit_note:",
            )
    with c_wrap:
        wrap_lines = st.toggle("Word Wrap", value=st.session_state.get("wrap_lines", True), key="wrap_lines_toggle")
        st.session_state["wrap_lines"] = wrap_lines
    with c_toggle:
        auto_apply = st.toggle(
            "Auto-apply AI changes",
            value=st.session_state.get("auto_apply", False),
            key="auto_apply_toggle",
            help="Save generated code automatically. Leave off to review and save each response yourself.",
        )
        st.session_state["auto_apply"] = auto_apply

    roadmap_steps = st.session_state.get("plan_steps", [])
    if roadmap_steps:
        step_ids = [step.get("id", f"step_{index}") for index, step in enumerate(roadmap_steps)]
        current_id = (st.session_state.get("current_step") or {}).get("id")
        selected_index = step_ids.index(current_id) if current_id in step_ids else 0
        with st.container(border=True):
            st.markdown("#### Build from your roadmap")
            selected_step_id = st.selectbox(
                "Choose a step",
                step_ids,
                index=selected_index,
                format_func=lambda step_id: next(
                    (step.get("title", step_id) for index, step in enumerate(roadmap_steps)
                     if step.get("id", f"step_{index}") == step_id),
                    step_id,
                ),
                key="roadmap_step_selector",
                label_visibility="collapsed",
                on_change=_persist_chat_roadmap_selection,
                args=(target_dir, roadmap_steps),
            )
            selected_step = next(
                step for index, step in enumerate(roadmap_steps)
                if step.get("id", f"step_{index}") == selected_step_id
            )
            st.session_state["current_step"] = selected_step
            if selected_step.get("description"):
                st.caption(selected_step["description"])
            build_col, done_col = st.columns(2)
            with build_col:
                if st.button(
                    "Build this step",
                    key="build_roadmap_step",
                    type="primary",
                    icon=":material/auto_awesome:",
                    width="stretch",
                ):
                    paths = ", ".join(selected_step.get("suggested_file_paths", [])) or "the appropriate project files"
                    st.session_state["pending_ai_prompt"] = (
                        f"Implement this roadmap step: {selected_step.get('title', '')}\n"
                        f"Goal: {selected_step.get('description', '')}\n"
                        f"Approach: {selected_step.get('approach', '')}\n"
                        f"Relevant files: {paths}\n"
                        "Generate the smallest complete change for this step and explain how to verify it."
                    )
            with done_col:
                is_done = selected_step.get("status") == "done"
                st.button(
                    "Mark complete" if not is_done else "Mark incomplete",
                    key="toggle_roadmap_step_done",
                    icon=":material/check_circle:",
                    width="stretch",
                    on_click=_toggle_roadmap_step,
                    args=(target_dir, roadmap_steps),
                )

    chat_panel = st.container(border=True)
    with chat_panel:
        with st.container(height=350):
            messages = st.session_state.setdefault("messages", [])
            visible_count = st.session_state.setdefault(
                "chat_visible_message_count", CHAT_HISTORY_PAGE_SIZE
            )
            if len(messages) > visible_count and st.button(
                f"Load {min(CHAT_HISTORY_PAGE_SIZE, len(messages) - visible_count)} earlier messages",
                key="load_earlier_chat_messages",
                width="stretch",
            ):
                visible_count = min(
                    len(messages), visible_count + CHAT_HISTORY_PAGE_SIZE
                )
                st.session_state["chat_visible_message_count"] = visible_count
            visible_start = max(0, len(messages) - visible_count)
            for index, message in enumerate(messages[visible_start:], start=visible_start):
                with st.chat_message(message["role"]):
                    if message["role"] == "assistant":
                        _render_assistant_message(
                            target_dir, selected_id, message, index, auto_apply
                        )
                    else:
                        st.markdown(message["content"])
            chat_live_slot = st.container()

            if st.session_state.get("ghost_writer_active"):
                st.session_state["ghost_writer_active"] = False

        failed_request = st.session_state.get("last_failed_ai_request")
        if failed_request:
            st.error(failed_request["error"])
            if st.button(
                "Retry last message",
                key="retry_last_chat_message",
                icon=":material/replay:",
            ):
                st.session_state["pending_ai_prompt"] = failed_request["prompt"]
                st.session_state["last_failed_ai_request"] = None

        chat_input_val = st.chat_input(
            "Message FORGE about your project...",
            key="forge_chat_input",
            disabled=not api_key,
            submit_mode="disable",
        )
    # Check for pending prompt (e.g. from Auto-Heal Code) or user chat input
    active_prompt = st.session_state.pop("pending_ai_prompt", None) or chat_input_val

    if active_prompt and api_key:
        messages = st.session_state["messages"]
        replaying_failed_prompt = bool(
            messages
            and messages[-1].get("role") == "user"
            and messages[-1].get("content") == active_prompt
        )
        if not replaying_failed_prompt:
            messages.append({"role": "user", "content": active_prompt})
            with chat_live_slot:
                with st.chat_message("user"):
                    st.markdown(active_prompt)
        history = messages[:-1] if replaying_failed_prompt or messages else []
        context_text = _build_chat_context(target_dir, tree, selected_id)
        streamed_text = []

        def display_streamed_text(chunk):
            streamed_text.append(chunk)
            current_text = "".join(streamed_text)
            if (
                len(current_text) - st.session_state.get("chat_stream_rendered_length", 0) >= 80
                or current_text.endswith("\n")
            ):
                response_placeholder.markdown(current_text)
                st.session_state["chat_stream_rendered_length"] = len(current_text)

        try:
            with chat_live_slot:
                with st.chat_message("assistant"):
                    response_placeholder = st.empty()
                    with st.spinner("FORGE is thinking..."):
                        active_plan = st.session_state.get("architecture_plan") or {}
                        active_plan = dict(active_plan)
                        active_plan["_steps"] = st.session_state.get("plan_steps", [])
                        reply, metadata = run_ai_chat(
                            active_prompt,
                            selected_id or "no file",
                            context_text,
                            history,
                            model,
                            base_url,
                            api_key,
                            plan=active_plan,
                            tree=tree,
                            project_idea=st.session_state.get("project_idea", ""),
                            include_metadata=True,
                            stream_callback=display_streamed_text,
                        )
                    if not reply or not reply.strip():
                        raise AIProviderError(
                            "FORGE received an empty reply. Please retry your message."
                        )
                    response_placeholder.empty()
                    st.session_state["messages"].append(
                        {"role": "assistant", "content": reply, "metadata": metadata}
                    )
                    response_index = len(st.session_state["messages"]) - 1
                    auto_apply = st.session_state.get("auto_apply", False)
                    _render_assistant_message(
                        target_dir,
                        selected_id,
                        st.session_state["messages"][response_index],
                        response_index,
                        auto_apply,
                    )
            st.session_state["last_ai_request"] = {"prompt": active_prompt, "at": time.time()}
            st.session_state["last_failed_ai_request"] = None
            st.session_state.pop("chat_stream_rendered_length", None)

            if auto_apply:
                apply_res = apply_ai_response(target_dir, selected_id, reply, plan=active_plan)
                if apply_res:
                    st.session_state["apply_status"] = apply_res
                    files_applied = apply_res.get("files", [])
                    st.session_state["last_patch_files"] = files_applied
                    st.session_state["live_reload_key"] = int(time.time() * 1000)
                    st.session_state["ghost_writer_active"] = True
                    st.session_state["flow_timestamp"] = int(time.time() * 1000)
                    st.session_state["preview_update_glow"] = True
                    if files_applied:
                        first_f = files_applied[0]
                        st.session_state["selected_id"] = first_f
                        if Path(first_f).suffix.lower() in {".html", ".htm", ".xhtml", ".py", ".md", ".markdown"}:
                            st.session_state["preview_entry_file"] = first_f
                        if Path(first_f).suffix.lower() == ".py":
                            st.session_state["auto_run_file"] = first_f
                        st.toast(f"File auto-saved: {first_f}", icon=":material/check_circle:")
                        st.rerun()
        except AIProviderError as e:
            st.session_state["last_failed_ai_request"] = {"prompt": active_prompt, "error": str(e)}
            st.session_state.pop("chat_stream_rendered_length", None)
            st.rerun()
        except Exception as e:
            st.session_state["last_failed_ai_request"] = {
                "prompt": active_prompt,
                "error": f"AI request failed: {e}",
            }
            st.session_state.pop("chat_stream_rendered_length", None)
            st.rerun()
    elif active_prompt:
        st.warning("Configure an AI provider key to use coding actions.")


def _fallback_roadmap_steps(plan: dict, vision: str) -> list[dict]:
    files = plan.get("files", [])
    paths = [
        item.get("path", "") if isinstance(item, dict) else str(item)
        for item in files
    ]
    feature = vision.strip().splitlines()[0][:100] if vision.strip() else "the core experience"
    return [
        {
            "id": "step_1",
            "title": "Set up the project",
            "description": f"Prepare {paths[0] if paths else 'the main project files'} and the structure needed for {feature}.",
            "approach": "Start with the planned files and keep the first version small.",
            "suggested_file_paths": paths[:2],
            "status": "planned",
        },
        {
            "id": "step_2",
            "title": "Build the core experience",
            "description": f"Implement the main user-facing behavior for {feature}.",
            "approach": "Build one complete user flow, then refine it with real interactions.",
            "suggested_file_paths": paths[:3],
            "status": "planned",
        },
        {
            "id": "step_3",
            "title": "Test and polish",
            "description": "Run the project, check its main flow, and fix rough edges.",
            "approach": "Verify the experience in the live preview and address any errors.",
            "suggested_file_paths": paths[-2:],
            "status": "planned",
        },
    ]


def _create_workspace_file(target_dir: str, file_name: str, starter: str = "auto") -> str:
    """Create a new starter file safely and return its workspace-relative path."""
    templates = {
        "web": (
            "index.html",
            """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>My new idea</title>
  <style>
    :root { color-scheme: dark; font-family: system-ui, sans-serif; background: #111214; color: #f1f1f3; }
    body { min-height: 100vh; margin: 0; display: grid; place-items: center; }
    main { width: min(680px, calc(100% - 3rem)); padding: 3rem; border: 1px solid #303238; border-radius: 20px; background: #191a1d; }
    p { color: #a2a3a8; line-height: 1.7; }
    button { margin-top: 1rem; padding: .8rem 1rem; border: 0; border-radius: 10px; background: #8297ff; color: #111214; font-weight: 700; cursor: pointer; }
  </style>
</head>
<body>
  <main>
    <p>YOUR PROJECT STARTS HERE</p>
    <h1>A little space for your idea.</h1>
    <p>Change this page, add your own styles, and use Preview to see your work.</p>
    <button onclick="this.textContent = 'Nice. Keep building.'">Try an interaction</button>
  </main>
</body>
</html>
""",
        ),
        "python": (
            "app.py",
            '''"""A small starting point for your project."""\n\n\ndef main():\n    print("Your project is ready for its first feature.")\n\n\nif __name__ == "__main__":\n    main()\n''',
        ),
        "notes": ("README.md", "# Your project\n\n## The idea\n\n## What I want to try first\n\n## Notes\n"),
    }
    if starter in templates:
        file_name, content = templates[starter]
    else:
        path = safe_file_path(target_dir, file_name.strip())
        if not file_name.strip() or path is None:
            raise ValueError("Enter a valid file path inside this workspace.")
        if path.suffix.lower() == ".py":
            content = '"""Project entry point."""\n\n\ndef main():\n    pass\n\n\nif __name__ == "__main__":\n    main()\n'
        elif path.suffix.lower() == ".html":
            content = "<!doctype html>\n<html lang=\"en\">\n<head>\n  <meta charset=\"utf-8\">\n  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n  <title>My project</title>\n</head>\n<body>\n  <main>\n    <h1>It works</h1>\n  </main>\n</body>\n</html>\n"
        elif path.suffix.lower() == ".md":
            content = "# Project notes\n\n"
        else:
            content = ""

    path = safe_file_path(target_dir, file_name)
    if path is None:
        raise ValueError("The starter filename is not valid for this workspace.")
    if path.exists():
        raise FileExistsError(f"`{file_name}` already exists.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    invalidate_scan_tree(target_dir)
    return path.relative_to(Path(target_dir)).as_posix()


def render_workspace_main():
    target_dir = st.session_state.get("target_dir", "")
    if not target_dir:
        st.warning("Open or create a workspace first.")
        return
    Path(target_dir).mkdir(parents=True, exist_ok=True)
    _restore_project_progress(target_dir)
    cfg = _active_provider()
    model = _model_for_provider(st.session_state.get("selected_model"), cfg)
    st.session_state["selected_model"] = model
    api_key = cfg["api_key"]
    base_url = cfg["base_url"]
    provider = cfg["provider"]
    provider_label = "FORGE"

    def expand_roadmap(expanded: bool) -> None:
        if not expanded:
            short_steps = st.session_state.get("short_plan_steps", [])
            st.session_state["plan_steps"] = short_steps
            st.session_state["roadmap_expanded"] = False
            st.session_state["current_step"] = short_steps[0] if short_steps else None
            if short_steps:
                st.session_state["roadmap_step_selector"] = short_steps[0].get("id")
            _persist_project_progress(target_dir)
            return
        try:
            with st.spinner("Expanding your roadmap into coding steps..."):
                detailed_steps = generate_roadmap(
                    st.session_state.get("project_idea", ""),
                    st.session_state.get("architecture_plan") or {},
                    model,
                    base_url,
                    api_key,
                    expanded=True,
                )
            st.session_state["plan_steps"] = detailed_steps
            st.session_state["roadmap_expanded"] = True
            st.session_state["roadmap_error"] = None
            st.session_state["current_step"] = detailed_steps[0] if detailed_steps else None
            if detailed_steps:
                st.session_state["roadmap_step_selector"] = detailed_steps[0].get("id")
            _persist_project_progress(target_dir)
        except AIProviderError as error:
            st.session_state["roadmap_error"] = f"Could not expand the roadmap: {error}"

    # --- Plan & Code: generate architecture plan (then review before scaffold) ---
    if st.session_state.pop("create_from_idea", False):
        st.session_state["roadmap_error"] = None
        if not api_key:
            st.error("Configure an AI provider key before using Plan & Code.")
            st.session_state["app_stage"] = "home"
            return
        # Create the workspace directory up-front so the watchdog observer,
        # tree scanner, and Quick Build flow all have a valid target before
        # the AI plan is generated (and before any scaffolding).
        Path(target_dir).mkdir(parents=True, exist_ok=True)
        try:
            with st.spinner("Planning your architecture..."):
                is_basic = st.session_state.get("project_mode", "Basic Mode") == "Basic Mode"
                if is_basic:
                    # Basic Mode: Scaffold only index.html + app.py, skip moodboard/animations/complex dependencies
                    plan = {
                        "summary": st.session_state.get("project_idea", "Clean starter application"),
                        "folders": [],
                        "files": [
                            {"path": "index.html", "description": "Interactive web interface"},
                            {"path": "app.py", "description": "Main application and server logic"},
                        ],
                        "roadmap": [
                            {"phase": "Phase 1: Setup", "goal": "Initialize index.html and app.py starter templates"},
                            {"phase": "Phase 2: Core Logic", "goal": "Implement primary features and handlers"},
                            {"phase": "Phase 3: Run & Preview", "goal": "Launch live preview and test outputs"},
                        ],
                        "dependencies": [],
                        "run_checklist": ["Run python app.py or preview index.html in the Live Output window"],
                    }
                else:
                    plan = generate_architecture(st.session_state.get("project_idea", ""), model, base_url, api_key)
                with st.spinner("Creating a short project roadmap..."):
                    try:
                        steps = generate_roadmap(
                            st.session_state.get("project_idea", ""),
                            plan,
                            model,
                            base_url,
                            api_key,
                        )
                    except AIProviderError as error:
                        steps = _fallback_roadmap_steps(plan, st.session_state.get("project_idea", ""))
                        st.session_state["roadmap_error"] = (
                            f"AI roadmap unavailable; showing a starter roadmap instead: {error}"
                        )
            st.session_state["architecture_plan"] = plan
            st.session_state["plan_steps"] = steps
            st.session_state["short_plan_steps"] = steps
            st.session_state["roadmap_expanded"] = False
            st.session_state["current_step"] = steps[0] if steps else None
            if steps:
                st.session_state["roadmap_step_selector"] = steps[0].get("id")
            st.session_state["project_idea"] = st.session_state.get("project_idea", "")
            st.session_state["selected_model"] = model
            st.session_state["plan_scaffolded"] = False
            st.session_state["plan_status"] = "review"
            st.session_state["apply_status"] = {"type": "info", "message": "Architecture and roadmap generated! Review your plan below to start development."}
            _persist_project_progress(target_dir)
        except AIProviderError as error:
            # Keep the new workspace open even when a free provider is busy;
            # the user can immediately ask the assistant to code instead.
            Path(target_dir).mkdir(parents=True, exist_ok=True)
            st.session_state["apply_status"] = {
                "type": "warning",
                "message": f"Planning was unavailable: {error}. The workspace is ready for your first coding request.",
            }

    # --- Plan review: show moodboard, offer Scaffold or Quick Build ---
    plan = st.session_state.get("architecture_plan")
    if plan and not st.session_state.get("plan_scaffolded", True):
        quick_build_requested = st.session_state.pop("quick_build", False)
        if st.button("Scaffold Project", type="primary", key="scaffold_plan", icon=":material/construction:")\
            or quick_build_requested:
            try:
                scaffold_project(target_dir, plan, st.session_state.get("project_idea", ""))
            except (FileExistsError, ValueError, OSError) as error:
                st.error(f"Could not scaffold the project: {error}")
                return
            st.session_state["plan_scaffolded"] = True
            st.session_state["plan_status"] = "in_progress"
            _persist_project_progress(target_dir)
            st.session_state["architecture_plan"] = None
            if quick_build_requested:
                # Auto-generate + save the first file after scaffolding
                plan_files = plan.get("files", [])
                if plan_files:
                    first_file = plan_files[0]
                    fname = first_file["path"]
                    prompt = f"Create the complete runnable file {fname}. Description: {first_file.get('description','')}. Follow the architecture plan: {plan.get('summary','')}"
                    try:
                        with st.spinner(f"Auto-generating {fname}…"):
                            generated = generate_file_content(fname, prompt, model, base_url, api_key)
                            blocks = extract_code_blocks(generated)
                            if blocks:
                                _lang, code, filename_hint = blocks[0]
                                target_name = filename_hint or fname
                                target_path = safe_file_path(target_dir, target_name)
                                if target_path:
                                    target_path.parent.mkdir(parents=True, exist_ok=True)
                                    save_workspace_file(target_dir, target_name, code)
                                    invalidate_scan_tree(target_dir)
                                    target_name = target_path.relative_to(Path(target_dir)).as_posix()
                                    st.session_state["selected_id"] = target_name
                                    if Path(target_name).suffix.lower() in {".html", ".htm", ".xhtml", ".py", ".md", ".markdown"}:
                                        st.session_state["preview_entry_file"] = target_name
                                    if Path(target_name).suffix.lower() == ".py":
                                        st.session_state["auto_run_file"] = target_name
                                    st.session_state["flow_timestamp"] = int(time.time() * 1000)
                                    st.session_state["apply_status"] = {
                                        "type": "success",
                                        "message": f"Quick Build complete: {target_name} created and running now.",
                                    }
                    except Exception as e:
                        st.session_state["apply_status"] = {
                            "type": "error",
                            "message": f"Quick Build auto-generation failed: {e}",
                        }
            else:
                st.session_state["apply_status"] = {"type": "success", "message": "Files scaffolded. Use the canvas to build."}
            st.rerun()
        def on_start_dev():
            try:
                scaffold_project(target_dir, plan, st.session_state.get("project_idea", ""))
            except (FileExistsError, ValueError, OSError) as error:
                st.error(f"Could not scaffold the project: {error}")
                return
            st.session_state["plan_scaffolded"] = True
            st.session_state["plan_status"] = "in_progress"
            _persist_project_progress(target_dir)
            st.session_state["architecture_plan"] = None
            st.toast("Project structure scaffolded! Development journey started.", icon=":material/rocket_launch:")
            st.rerun()

        st.markdown('<div class="blueprint-grid">', unsafe_allow_html=True)
        render_moodboard(
            plan,
            model,
            on_start_development=on_start_dev,
            on_expand_roadmap=lambda: expand_roadmap(not st.session_state.get("roadmap_expanded", False)),
            on_select_step=lambda step: _set_current_roadmap_step(step, target_dir),
            on_refine_plan=lambda summary: _refine_plan_from_ideas(summary, model),
        )
        st.markdown("</div>", unsafe_allow_html=True)
        
        c_p1, c_p2 = st.columns(2)
        with c_p1:
            prev_label = "Hide Architecture" if st.session_state.get("show_full_plan", False) else "Preview Architecture"
            if st.button(prev_label, key="preview_arch_btn", icon=":material/visibility:", width="stretch"):
                st.session_state["show_full_plan"] = not st.session_state.get("show_full_plan", False)
                st.rerun()
        with c_p2:
            if st.button("Quick build & run", key="build_and_run_btn", icon=":material/rocket_launch:", width="stretch"):
                st.session_state["quick_build"] = True
                st.session_state["plan_status"] = "in_progress"
                st.rerun()
        st.caption("Quick build generates a starter file immediately; Start building opens the guided workspace.")
        return

    observer, event_queue = start_observer(target_dir)
    events = st.session_state.setdefault("events", [])
    workspace_changed = False
    while not event_queue.empty():
        events.append(event_queue.get())
        workspace_changed = True
    st.session_state["events"] = events[-30:]
    if workspace_changed:
        invalidate_scan_tree(target_dir)
    tree = scan_tree(target_dir)
    selected_id = st.session_state.get("selected_id")
    if selected_id not in tree:
        selected_id = None

    steps = st.session_state.get("plan_steps", [])
    plan_status = st.session_state.get("plan_status", "in_progress")
    cur_step = st.session_state.get("current_step")
    completed_steps = [s.get("id") for s in steps if s.get("status") == "done"]

    def trigger_whats_next():
        with st.spinner("AI is analyzing your roadmap progress..."):
            advice = ask_whats_next(
                st.session_state.get("project_idea", ""),
                {"summary": Path(target_dir).name},
                steps, completed_steps, selected_id,
                model, base_url, api_key
            )
        st.session_state["whats_next_advice"] = advice
        st.toast(advice, icon=":material/tips_and_updates:")

    # Barebones layout: chat + preview only
    st.caption("PROJECT / WORKSPACE")
    st.title(Path(target_dir).name)
    st.caption("Choose a step. Make a change. See it take shape.")
    if st.session_state.get("roadmap_error") and not st.session_state.get("architecture_plan"):
        st.warning(st.session_state["roadmap_error"])
    if steps:
        completed_count = len(completed_steps)
        current_step = cur_step or next(
            (step for step in steps if step.get("status") != "done"),
            steps[0],
        )
        with st.container(border=True):
            st.markdown("#### Your roadmap")
            st.progress(
                completed_count / len(steps),
                text=f"{completed_count} of {len(steps)} steps complete",
            )
            st.markdown(
                f"**Continue with:** {current_step.get('title', 'Next step')}"
            )
            if current_step.get("description"):
                st.caption(current_step["description"])
            if api_key:
                st.button(
                    "Continue in chat",
                    key="continue_roadmap_in_chat",
                    icon=":material/arrow_forward:",
                    on_click=_open_workspace_chat,
                )

    left, right = st.columns([1, 1], gap="medium")
    with left:
        workspace_section = st.segmented_control(
            "Workspace view",
            ["Chat", "Code"],
            default="Code" if selected_id or not api_key else "Chat",
            label_visibility="collapsed",
            key="workspace_section",
            width="stretch",
        )
        if workspace_section == "Chat":
            _render_ai_assistant(target_dir, tree, selected_id, model, api_key, base_url, provider)
        else:
            workspace_files = [
                node_id for node_id, info in tree.items()
                if info.get("type") == "file"
            ]
            with st.form("create_workspace_file", border=False):
                file_col, create_col = st.columns([3, 1], vertical_alignment="bottom")
                with file_col:
                    new_file_name = st.text_input(
                        "New file",
                        placeholder="e.g. index.html or src/main.py",
                        label_visibility="collapsed",
                        key="new_workspace_file_name",
                    )
                with create_col:
                    create_file = st.form_submit_button(
                        "Add file",
                        icon=":material/add:",
                        type="primary",
                        width="stretch",
                        key="add_workspace_file",
                    )
            if create_file:
                try:
                    st.session_state["selected_id"] = _create_workspace_file(
                        target_dir, new_file_name
                    )
                    st.rerun()
                except (ValueError, FileExistsError) as error:
                    st.warning(str(error))
                except OSError as error:
                    st.error(f"Could not create the file: {error}")

            if workspace_files:
                editor_index = workspace_files.index(selected_id) if selected_id in workspace_files else 0
                editor_file = st.selectbox(
                    "Choose a file",
                    workspace_files,
                    index=editor_index,
                    key="workspace_editor_file",
                )
                st.session_state["selected_id"] = editor_file
                show_node_editor(target_dir, tree, editor_file)
            else:
                st.subheader("Start with a useful first file")
                st.caption("Choose a starter, or add your own filename above. These files are yours to edit.")
                starter_columns = st.columns(3)
                starter_choices = [
                    ("web", "Web page", "A styled HTML page with one working interaction.", ":material/language:"),
                    ("python", "Python app", "A small runnable Python entry point.", ":material/terminal:"),
                    ("notes", "Project notes", "A README to capture your idea and next steps.", ":material/description:"),
                ]
                for column, (starter_id, title, description, icon) in zip(starter_columns, starter_choices):
                    with column:
                        with st.container(border=True):
                            st.markdown(f"**{icon} {title}**")
                            st.caption(description)
                            if st.button(
                                f"Create {title.lower()}",
                                key=f"starter_file_{starter_id}",
                                width="stretch",
                            ):
                                try:
                                    st.session_state["selected_id"] = _create_workspace_file(
                                        target_dir, "", starter=starter_id
                                    )
                                    st.rerun()
                                except FileExistsError as error:
                                    st.warning(str(error))
                                except (ValueError, OSError) as error:
                                    st.error(f"Could not create the starter file: {error}")
                st.caption("Or switch to Chat to describe what you want built. AI assistance is optional.")
    with right:
        st.subheader("Preview", help="HTML files render here. Python scripts run on demand and show their output.")
        render_live_output_window(target_dir, tree)

    if st.button("Back to projects", key="workspace_home", icon=":material/home:"):
        st.session_state["app_stage"] = "home"
        st.rerun()

def render_onboarding():
    """Generate an architecture plan without creating files until the user approves it."""
    if "onboarding_vision" not in st.session_state:
        st.session_state["onboarding_vision"] = st.session_state.get("project_idea", "")
    # provider config kept internal
    active_provider_config = _get_provider_config()
    active_models = active_provider_config["models"]
    # Ollama: surface only models actually installed locally. A 404 "model not
    # found" happens whenever the user picks a model that isn't pulled yet (no
    # API call leaves Ollama even if the server is up). If none of the config's
    # entries are installed, fall back to any available model so the user can
    # still plan with whatever they have.
    if active_provider_config["provider"] == "ollama":
        installed = list_available_ollama_models()
        if installed:
            active_models = {
                label: model for label, model in active_models.items()
                if model in installed
            }
            if not active_models:
                active_models = {m: m for m in installed}

    request = render_onboarding_hub(
        active_models, active_provider_config["api_key"], active_provider_config["label"],
        active_provider_config["base_url"],
        on_browse_existing, on_browse_new,
    )
    if not request:
        return

    st.session_state["roadmap_error"] = None
    vision = request["vision"]
    if not vision:
        st.warning("Add a project vision before generating an architecture.")
        return
    if not active_provider_config["api_key"]:
        st.error("Configure provider before planning.")
        return

    models = active_models
    model = models.get(request["model_label"], active_provider_config["default_model"])
    # Prefer local Ollama only when the user has not explicitly selected a provider.
    if _should_auto_select_ollama(st.session_state.get("provider_override")):
        st.session_state["provider_override"] = "ollama"
        # Recompute config after setting the override so base_url / api_key / model are fresh
        # provider config kept internal
    active_provider_config = _get_provider_config()
    active_models = active_provider_config["models"]
    model = models.get(request["model_label"], active_provider_config["default_model"])
    try:
        with st.spinner("Planning your architecture..."):
            plan = generate_architecture(vision, model, active_provider_config["base_url"], active_provider_config["api_key"])
            with st.spinner("Generating development roadmap..."):
                try:
                    steps = generate_roadmap(vision, plan, model, active_provider_config["base_url"], active_provider_config["api_key"])
                except AIProviderError as error:
                    steps = _fallback_roadmap_steps(plan, vision)
                    st.session_state["roadmap_error"] = (
                        f"AI roadmap unavailable; showing a starter roadmap instead: {error}"
                    )
        st.session_state["architecture_plan"] = plan
        st.session_state["plan_steps"] = steps
        st.session_state["short_plan_steps"] = steps
        st.session_state["roadmap_expanded"] = False
        st.session_state["current_step"] = steps[0] if steps else None
        st.session_state["project_idea"] = vision
        st.session_state["selected_model"] = model
        st.session_state["plan_scaffolded"] = False
        st.session_state["plan_status"] = "review"
        st.session_state["app_stage"] = "workspace"
        st.rerun()
    except AIProviderError as error:
        if error.status_code == 503 and active_provider_config["provider"] == "ollama":
            st.error(
                "Ollama is not reachable at the configured URL. Start it with `ollama serve`, "
                "or set `OLLAMA_BASE_URL` in `.env` to your Ollama-compatible gateway URL."
            )
            return
        messages = {
            400: "The provider rejected the planning request (HTTP 400). Try another model or simplify the vision.",
            429: "The provider is rate-limiting requests (HTTP 429). Wait a moment and try again.",
            503: "The provider is temporarily unavailable (HTTP 503). Check its endpoint and try again.",
        }
        st.error(messages.get(error.status_code, f"Architecture planning failed: {error}"))


def _refine_plan_from_ideas(idea_summary: str, model: str | None) -> None:
    """Regenerate a reviewed architecture when the user explicitly feeds in ideas."""
    if not idea_summary.strip():
        st.info("Add at least one idea before sending notes to the architect.")
        return
    cfg = _active_provider()
    if not cfg["api_key"]:
        st.error("Need provider setup before refining.")
        return
    vision = st.session_state.get("project_idea", "")
    request = f"{vision}\n\nArchitecture notes to incorporate:\n{idea_summary}"
    try:
        with st.spinner("Updating the architecture from your ideas…"):
            model = model or cfg["default_model"]
            plan = generate_architecture(request, model, cfg["base_url"], cfg["api_key"])
            try:
                steps = generate_roadmap(vision, plan, model, cfg["base_url"], cfg["api_key"])
                st.session_state["roadmap_error"] = None
            except AIProviderError as error:
                steps = _fallback_roadmap_steps(plan, vision)
                st.session_state["roadmap_error"] = (
                    f"AI roadmap unavailable; showing a starter roadmap instead: {error}"
                )
        st.session_state["architecture_plan"] = plan
        st.session_state["plan_steps"] = steps
        st.session_state["short_plan_steps"] = steps
        st.session_state["roadmap_expanded"] = False
        st.session_state["current_step"] = steps[0] if steps else None
        if steps:
            st.session_state["roadmap_step_selector"] = steps[0].get("id")
        else:
            st.session_state.pop("roadmap_step_selector", None)
        st.session_state["plan_status"] = "review"
        st.session_state["plan_scaffolded"] = False
        st.session_state["apply_status"] = {"type": "success", "message": "Architecture updated from your ideas. Review it before scaffolding."}
        workspace = st.session_state.get("target_dir")
        if workspace:
            _persist_project_progress(workspace)
        st.rerun()
    except AIProviderError as error:
        st.error(f"Could not update the plan: {error}")


def main():
    st.set_page_config(page_title="FORGE — AI Coding Studio", layout="wide", initial_sidebar_state="expanded")
    inject_theme()
    SessionStateManager.initialize(st.session_state)
    stage = st.session_state.get("app_stage", "home")
    def front_runner():
        render_front_page(
            on_browse_existing=on_browse_existing,
            on_browse_new=on_browse_new,
        )
    {
        "home": front_runner,
        "splash": front_runner,
        "onboarding": render_onboarding,
        "workspace": render_workspace_main,
    }.get(stage, front_runner)()


if __name__ == "__main__":
    main()
