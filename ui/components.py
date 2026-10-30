import streamlit as st
import re
import time
import datetime
import html
from pathlib import Path
from services.files import (
    get_file_path, scan_tree, invalidate_scan_tree, build_preview_tree,
    export_context_md, save_workspace_file,
)
from services.executor import (
    run_python_preview, detect_workspace_preview_type, get_static_preview_url,
    is_streamlit_app, start_streamlit_preview,
)
from utils.helpers import safe_file_path
from core.ai import (
    generate_architecture, run_ai_chat, apply_patch, extract_code_block, 
    extract_patch_blocks, generate_file_content, generate_roadmap, ask_whats_next,
)
from ui.bitmap_animation import render_bitmap_animation, render_ascii_background, render_datastream_pulse


def _is_valid_workspace_name(name: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]*", name))


def _apply_home_template() -> None:
    selected = st.session_state.get("home_template_choice")
    template = next(
        (item for item in _home_templates() if item["title"] == selected),
        None,
    )
    if template:
        st.session_state["project_idea_input"] = template["description"]


def _home_templates() -> list[dict[str, str]]:
    return [
        {
            "title": "Streamlit app",
            "description": "A polished Streamlit app with a clear workflow, responsive layout, and useful interactive controls.",
        },
        {
            "title": "FastAPI service",
            "description": "A small FastAPI service with typed endpoints, SQLite storage, and focused automated tests.",
        },
        {
            "title": "Data dashboard",
            "description": "A clear data dashboard with useful filters, readable charts, and a concise project overview.",
        },
        {
            "title": "Python tool",
            "description": "A small Python tool with a clear command-line workflow, helpful error messages, and tests.",
        },
    ]


def _start_home_workspace(mode: str) -> None:
    parent = st.session_state.get("new_parent_input", "").strip()
    name = st.session_state.get("new_workspace_name", "").strip()
    vision = st.session_state.get("project_idea_input", "").strip()
    if not parent or not Path(parent).is_dir() or not name:
        st.error("Choose an existing parent folder and enter a workspace name.")
        return
    if mode != "blank" and not vision:
        st.error("Add a short project description before generating a plan.")
        return
    if not _is_valid_workspace_name(name):
        st.error("Workspace name must use only letters, numbers, and hyphens, and start with a letter or number.")
        return
    workspace = Path(parent) / name
    if workspace.exists():
        st.error("That workspace folder already exists. Open it as an existing project instead.")
        return

    st.session_state["target_dir"] = str(workspace)
    st.session_state["project_idea"] = vision if mode != "blank" else ""
    st.session_state["architecture_plan"] = None
    st.session_state["plan_steps"] = []
    st.session_state["short_plan_steps"] = []
    st.session_state["current_step"] = None
    st.session_state["plan_scaffolded"] = mode == "blank"
    st.session_state["plan_status"] = "review" if mode == "plan" else "in_progress"
    st.session_state["messages"] = []
    st.session_state["roadmap_loaded_for"] = None
    st.session_state.pop("roadmap_step_selector", None)
    st.session_state["create_from_idea"] = mode != "blank"
    st.session_state["quick_build"] = mode == "quick"
    st.session_state["workspace_section"] = "Code" if mode == "blank" else "Chat"
    st.session_state["app_stage"] = "workspace"
    st.rerun()


def status_pills(target_name, key_ok, provider_label, extra=""):
    """Small rounded pills with colored dots for status."""
    c1, c2, c3 = st.columns([2, 1, 1])
    with c1:
        label = target_name or "No target"
        st.markdown(f'<span class="status-pill"><span class="connection-dot" style="background:#3b82f6;"></span> Active: {html.escape(str(label))}</span>', unsafe_allow_html=True)
    with c2:
        st.markdown('<span class="status-pill"><span class="connection-dot"></span> Watcher active</span>', unsafe_allow_html=True)
    with c3:
        cls = " pill-accent" if key_ok else ""
        dot_color = "#22c55e" if key_ok else "#94a3b8"
        st.markdown(f'<span class="status-pill{cls}"><span class="connection-dot" style="background:{dot_color};"></span> {html.escape(str(provider_label))}</span>', unsafe_allow_html=True)
    if extra:
        st.markdown(extra, unsafe_allow_html=True)


def render_status_bar(target_dir, selected_id, model, event_count, current_step_title=None, phase=None):
    now_utc = datetime.datetime.now(datetime.timezone.utc).strftime("%H:%M UTC")
    if selected_id:
        target_name = selected_id
        ext = Path(selected_id).suffix.lower() or "text"
        file_info = f"{target_name} ({ext})"
    else:
        file_info = "No file selected"
    
    model_name = model or "No Model"
    ws_name = Path(target_dir).name if target_dir else "canvas"
    phase_str = f"Phase: {phase}" if phase else "Phase: Developing"
    step_str = f"Step: {current_step_title}" if current_step_title else "Step: None"
    
    status_html = f"""
    <div class="ide-status-bar">
        <div class="ide-status-group">
            <div class="ide-status-item" style="color: #3b82f6; font-weight: 700; display:flex; align-items:center; gap:6px;">
                <span class="status-dot blue" style="margin:0;"></span> LIVE CODEBASE CANVAS
            </div>
            <div class="ide-status-item">{html.escape(str(file_info))}</div>
            <div class="ide-status-item">{html.escape(str(phase_str))}</div>
            <div class="ide-status-item">{html.escape(str(step_str))}</div>
            <div class="ide-status-item">Workspace: <strong>{html.escape(str(ws_name))}</strong></div>
        </div>
        <div class="ide-status-group">
            <div class="ide-status-item">
                <span class="status-dot-live"></span>
                <span>Watchdog: {event_count} events</span>
            </div>
            <div class="ide-status-item">Model: {html.escape(str(model_name))}</div>
            <div class="ide-status-item">{now_utc}</div>
        </div>
    </div>
    """
    st.markdown(status_html, unsafe_allow_html=True)


def render_recent_projects(header_text="Recent Workspaces"):
    """Render a one-click list of recently opened workspace folder paths."""
    recent = st.session_state.get("recent_projects", [])
    if not recent:
        st.caption("No recent projects yet. Open a workspace to see it here.")
        return
    
    st.markdown(f"<div class='recent-projects-header'>{header_text}</div>", unsafe_allow_html=True)
    for i, path in enumerate(recent):
        col1, col2 = st.columns([0.92, 0.08])
        with col1:
            if st.button(path, key=f"recent_project_{i}", help="Re-open this workspace", width="stretch", icon=":material/folder:"):
                st.session_state["target_dir"] = path
                st.session_state["architecture_plan"] = None
                st.session_state["plan_scaffolded"] = False
                st.session_state["plan_status"] = "in_progress"
                st.session_state["app_stage"] = "workspace"
                st.rerun()
        with col2:
            if st.button(" ", key=f"clear_recent_{i}", width="content", icon=":material/close:"):
                recent.remove(path)
                st.session_state["recent_projects"] = recent
                st.rerun()


def render_front_page(
    api_key=None,
    provider_label=None,
    base_url=None,
    model=None,
    on_browse_existing=None,
    on_browse_new=None,
):
    """Render the project launchpad with a short, guided start flow."""

    with st.sidebar:
        st.markdown(
            '<div class="forge-sidebar-brand">FORGE'
            '<span>Live codebase canvas</span></div>',
            unsafe_allow_html=True,
        )
        mode = st.radio(
            "Project Experience Mode",
            ["Basic Mode", "Advanced Mode"],
            index=0 if st.session_state.get("project_mode", "Basic Mode") == "Basic Mode" else 1,
            key="project_mode_radio_home",
            help="Basic Mode scaffolds clean index.html + app.py for fast prototyping. Advanced Mode enables full multi-file architectures & research moodboards."
        )
        st.session_state["project_mode"] = mode
        st.markdown("---")
        render_recent_projects()

    with st.container(border=True):
        st.caption("A WORKSPACE FOR IDEAS IN MOTION")
        st.title("FORGE")
        st.caption("Start with a sentence. Shape it into a plan, then make it real.")
        st.markdown('<div class="forge-rule"></div>', unsafe_allow_html=True)
        st.markdown(
            '<div class="forge-steps">'
            '<span><strong>01</strong> / Describe</span>'
            '<span><strong>02</strong> / Choose a roadmap</span>'
            '<span><strong>03</strong> / Build &amp; preview</span>'
            '</div>',
            unsafe_allow_html=True,
        )

    create_tab, open_tab = st.tabs(["Create a workspace", "Open an existing project"])
    with create_tab:
        st.subheader("Start with an idea", icon=":material/add_to_drive:")
        template_names = [template["title"] for template in _home_templates()]
        st.pills(
            "Start from a template",
            template_names,
            selection_mode="single",
            key="home_template_choice",
            on_change=_apply_home_template,
            help="A starter description is added to the project brief; you can edit it.",
        )
        parent_col, browse_col = st.columns([3, 1], vertical_alignment="bottom")
        with parent_col:
            st.text_input("Parent folder", key="new_parent_input", placeholder="C:\\Projects")
        with browse_col:
            st.button(
                "Browse",
                key="browse_new",
                width="stretch",
                icon=":material/folder_open:",
                on_click=on_browse_new,
            )

        with st.form("new_workspace_form", border=False):
            st.text_input("Workspace name", key="new_workspace_name", placeholder="my-new-project")
            st.text_area(
                "What are you building?",
                key="project_idea_input",
                placeholder="Describe the people who will use it and the main thing it should help them do.",
                height=90,
                help="You can start without AI or a roadmap using the last option below.",
            )
            plan_col, quick_col, blank_col = st.columns(3)
            with plan_col:
                plan_workspace = st.form_submit_button(
                    "Plan & Code",
                    key="plan_from_home",
                    type="primary",
                    width="stretch",
                    icon=":material/auto_awesome:",
                    help="Review the architecture and roadmap before creating project files.",
                )
            with quick_col:
                quick_workspace = st.form_submit_button(
                    "Quick build",
                    key="quick_build_from_home",
                    width="stretch",
                    icon=":material/rocket_launch:",
                    help="Generate a starter project and preview its first file.",
                )
            with blank_col:
                blank_workspace = st.form_submit_button(
                    "Start blank",
                    key="empty_workspace_from_home",
                    width="stretch",
                    icon=":material/edit_note:",
                    help="Create a workspace without AI planning; add and edit files yourself.",
                )

        if plan_workspace:
            _start_home_workspace("plan")
        elif quick_workspace:
            _start_home_workspace("quick")
        elif blank_workspace:
            _start_home_workspace("blank")

    with open_tab:
        st.subheader("Pick up where you left off", icon=":material/folder_open:")
        st.caption("Open a folder to edit its files and preview a local app.")
        path_col, browse_col = st.columns([3, 1], vertical_alignment="bottom")
        with path_col:
            st.text_input("Workspace folder", key="existing_path_input", placeholder="C:\\Projects\\my-app")
        with browse_col:
            st.button(
                "Browse",
                key="browse_existing",
                width="stretch",
                icon=":material/folder_open:",
                on_click=on_browse_existing,
            )
        if st.button(
            "Open project",
            key="open_existing",
            type="primary",
            width="stretch",
            icon=":material/arrow_forward:",
        ):
            selected = st.session_state.get("existing_path_input", "").strip()
            if not selected or not Path(selected).is_dir():
                st.error("Choose an existing folder before opening the workspace.")
            else:
                st.session_state["target_dir"] = selected
                st.session_state["architecture_plan"] = None
                st.session_state["plan_scaffolded"] = True
                st.session_state["plan_status"] = "in_progress"
                st.session_state["messages"] = []
                st.session_state["app_stage"] = "workspace"
                st.rerun()

    with st.expander("Explore starter ideas", expanded=False, icon=":material/lightbulb:"):
        render_template_chips()
    st.caption("Your files remain in the workspace folder you choose. Cloud AI receives project context only when you request AI help.")


def render_onboarding_hub(available_models, api_key, provider_label, base_url, on_browse_existing, on_browse_new):
    """Render onboarding controls and return a submitted planning request, if any."""
    st.title("Plan your workspace", icon=":material/account_tree:")
    st.caption("Review the proposed structure before the app creates files in your selected workspace.")
    left, right = st.columns([1, 1], gap="large")

    def load_software_template() -> None:
        st.session_state["onboarding_vision"] = (
            "A small FastAPI backend with a clear API, SQLite storage, tests, "
            "and a simple local development workflow."
        )

    with left:
        with st.container(border=True):
            st.subheader("Architecture brief")
            labels = list(available_models)
            no_models = not labels
            selected_label = st.selectbox(
                "Model", labels or ["No model available"], key="onboarding_model_label", disabled=no_models,
                help="Configure a provider key or start Ollama to enable model selection." if no_models else None,
            )
            st.button(
                "Use FastAPI backend starter", key="fastapi_backend_starter",
                icon=":material/api:", on_click=load_software_template,
            )
            st.text_area("Project vision", key="onboarding_vision", height=180,
                         placeholder="Describe the users, key screens, data, and constraints.")
            submitted = st.button("Plan architecture", type="primary", key="generate_architecture", width="stretch", icon=":material/architecture:")
    with right:
        with st.container(border=True):
            st.subheader("What you will review")
            st.markdown("- A compact folder and file plan\n- A build roadmap\n- A visual preview before scaffold\n- Explicit file creation only after approval")
            st.caption("No code is created during planning.")
    if submitted:
        if no_models:
            st.warning("No models are available. Configure an AI provider before planning.")
            return None
        return {
            "vision": st.session_state.get("onboarding_vision", "").strip(),
            "model_label": selected_label,
        }
    return None


def render_template_chips():
    """Render optional starter ideas that seed the new-workspace brief."""
    templates = [
        ("Streamlit app", "PYTHON · UI", "A polished Streamlit app with a clear workflow, responsive layout, and useful interactive controls.", "#3b82f6"),
        ("FastAPI service", "API · DB · TESTS", "A small FastAPI service with typed endpoints, SQLite storage, and focused automated tests.", "#22c55e"),
        ("Data dashboard", "DATA · CHARTS", "A clear data dashboard with useful filters, readable charts, and a concise project overview.", "#eab308"),
        ("Python tool", "PYTHON · CLI", "A small Python tool with a clear command-line workflow, helpful error messages, and tests.", "#ec4899"),
    ]
    st.markdown('<div class="recent-projects-header" style="margin-top:12px;">Starter ideas</div>', unsafe_allow_html=True)
    cols = st.columns(min(len(templates), 4), gap="small")
    for i, (title, label, desc, dot_color) in enumerate(templates):
        with cols[i]:
            st.markdown(
                f'<span class="status-dot" style="background:{dot_color};"></span>'
                f'**{html.escape(title)}**',
                unsafe_allow_html=True,
            )
            st.caption(label)
            st.caption(desc)
            if st.button(
                "Use this idea",
                key=f"template_chip_{i}",
                help=desc,
                width="stretch",
                icon=":material/add:",
            ):
                st.session_state["project_idea"] = desc
                st.session_state["project_idea_input"] = desc
                st.toast(f"Starter added: {title}.", icon=":material/check_circle:")
                st.rerun()


def show_node_editor(root, tree, selected_id):
    """Editor container as a dashboard card. Save=primary blue, Run=secondary."""
    if not selected_id or selected_id not in tree:
        st.info("Click a node on the canvas to inspect or edit it.")
        return
    info = tree[selected_id]

    # Show node plan status from plan_steps above editor
    steps = st.session_state.get("plan_steps", [])
    current_step = st.session_state.get("current_step")
    related_step = next((s for s in steps if selected_id in s.get("suggested_file_paths", [])), None)
    
    badge_html = ""
    if related_step:
        is_cur = current_step and current_step.get("id") == related_step.get("id")
        dot_cls = "blue" if is_cur else ("green" if related_step.get("status") == "done" else "yellow")
        badge_html = f'<div style="margin-bottom:8px;"><span class="status-pill"><span class="status-dot {dot_cls}"></span>Step: {related_step.get("title")}</span></div>'

    st.markdown(f"{badge_html}**Selected:** `{selected_id}` · **type:** `{info['type']}`", unsafe_allow_html=True)
    if info["type"] != "file":
        st.caption("Select a file node to view or edit its contents.")
        return
    file_path = get_file_path(root, info)
    try:
        current = file_path.read_text(encoding="utf-8")
    except Exception as e:
        st.error(f"Could not read `{selected_id}`: {e}")
        return
    ext = file_path.suffix.lower()
    lang = "python" if ext == ".py" else "markdown" if ext in {".md", ".mdown", ".txt"} else "text"
    safe_key = re.sub(r"[^A-Za-z0-9_]", "_", selected_id)
    
    with st.container(border=True):
        wrap_editor = st.session_state.get("wrap_lines", True)
        wrap_class = "white-space: pre-wrap !important; word-break: break-word !important;" if wrap_editor else "white-space: pre !important; overflow-x: auto !important;"
        st.markdown(f"""
        <style>
          div[data-testid="stTextArea"] textarea {{
            font-family: 'JetBrains Mono', monospace !important;
            font-size: 13px !important;
            line-height: 1.75 !important;
            {wrap_class}
          }}
        </style>
        """, unsafe_allow_html=True)
        edited = st.text_area(f"Edit `{selected_id}`", value=current, height=240, key=f"editor_{safe_key}")
        
        c1, c2 = st.columns(2)
        with c1:
            if st.button("Save changes", type="primary", width="stretch", key=f"save_{safe_key}", icon=":material/save:"):
                try:
                    save_workspace_file(root, selected_id, edited)
                    st.session_state["flow_timestamp"] = int(time.time() * 1000)
                    st.session_state["live_reload_key"] = int(time.time() * 1000)
                    st.session_state["preview_update_glow"] = True
                    st.toast(f"Saved `{selected_id}`", icon=":material/check:")
                    st.rerun()
                except Exception as e:
                    st.error(f"Failed to save `{selected_id}`: {e}")
        with c2:
            if ext == ".py" and st.button("Run code", width="stretch", key=f"run_{safe_key}", icon=":material/play_arrow:"):
                with st.spinner("Running preview..."):
                    stdout, stderr = run_python_preview(file_path)
                entry = f"--- Execution of {selected_id} ---\nSTDOUT:\n{stdout}\n\nSTDERR:\n{stderr}\n----------------------------"
                st.session_state.setdefault("console_history", []).append(entry)
                st.session_state["console_history"] = st.session_state["console_history"][-20:]
                st.session_state["live_reload_key"] = int(time.time() * 1000)
                st.session_state["preview_update_glow"] = True
                if stderr:
                    st.session_state["last_preview_error"] = {"file": selected_id, "stderr": stderr}
                else:
                    st.session_state["last_preview_error"] = None
                st.toast("Execution finished. Check the console.", icon=":material/terminal:")
                st.rerun()
        with st.expander("Preview formatted code"):
            st.code(edited[:5000], language=lang)


def render_roadmap(plan, steps, completed_steps, on_trigger_whats_next=None):
    """Checklist-style cards for the guided development journey.
    Ember dashboard card aesthetic: status dots, step cards, custom step adding,
    and What's Next coaching action.
    """
    st.markdown('<div class="recent-projects-header">Development Journey</div>', unsafe_allow_html=True)
    
    c_hdr, c_wn = st.columns([1.5, 1])
    with c_hdr:
        done_count = sum(1 for s in steps if s.get("id") in completed_steps or s.get("status") == "done")
        st.caption(f"{done_count} of {len(steps)} steps completed")
    with c_wn:
        if st.button("What's Next?", key="whats_next_btn", type="primary", width="stretch", icon=":material/tips_and_updates:"):
            if on_trigger_whats_next:
                on_trigger_whats_next()

    # Step cards
    for idx, step in enumerate(steps):
        s_id = step.get("id", f"step_{idx}")
        is_done = (s_id in completed_steps) or (step.get("status") == "done")
        is_active = (st.session_state.get("current_step", {}).get("id") == s_id) if st.session_state.get("current_step") else (idx == 0 and not is_done)
        
        # Color dot: green=done, blue=in-progress, grey=planned
        dot_color = "#22c55e" if is_done else ("#3b82f6" if is_active else "#64748b")
        active_border = "border-color: #3b82f6; background: #161b22;" if is_active else ""
        
        with st.container(border=True):
            col_dot, col_body, col_act = st.columns([0.08, 0.72, 0.20], vertical_alignment="center")
            with col_dot:
                st.markdown(f'<span class="status-dot" style="background:{dot_color}; margin:0;"></span>', unsafe_allow_html=True)
            with col_body:
                title_style = "color:#ffffff; font-weight:600;" if not is_done else "color:#94a3b8; text-decoration:line-through;"
                st.markdown(f'<span style="{title_style}">{html.escape(str(step.get("title", f"Step {idx+1}")))}</span>', unsafe_allow_html=True)
                if desc := step.get("description"):
                    st.caption(desc)
                if approach := step.get("approach"):
                    st.markdown(f'<span style="color:#3b82f6; font-size:11px;">🔧 {html.escape(str(approach))}</span>', unsafe_allow_html=True)
                # Show file sub-items
                if fpaths := step.get("suggested_file_paths"):
                    st.caption("Target files: " + ", ".join(f"`{p}`" for p in fpaths))
            with col_act:
                btn_label = "Active" if is_active else "Select"
                if not is_done:
                    if st.button(btn_label, key=f"select_step_{s_id}_{idx}", width="stretch", type="primary" if is_active else "secondary"):
                        st.session_state["current_step"] = step
                        # Pre-select primary file if present
                        if fpaths and fpaths[0] in st.session_state.get("tree", {}):
                            st.session_state["selected_id"] = fpaths[0]
                        st.rerun()
                    if st.button("Mark Done", key=f"done_step_{s_id}_{idx}", width="stretch", icon=":material/check:"):
                        step["status"] = "done"
                        if s_id not in completed_steps:
                            completed_steps.append(s_id)
                        # Auto-advance to next step
                        next_steps = [s for s in steps if s.get("status") != "done"]
                        st.session_state["current_step"] = next_steps[0] if next_steps else None
                        st.toast(f"Step completed: {step.get('title')}", icon=":material/check_circle:")
                        st.rerun()
                else:
                    if st.button("Re-open", key=f"reopen_step_{s_id}_{idx}", width="stretch"):
                        step["status"] = "planned"
                        if s_id in completed_steps:
                            completed_steps.remove(s_id)
                        st.session_state["current_step"] = step
                        st.rerun()


def render_moodboard(
    plan,
    model=None,
    on_start_development=None,
    on_expand_roadmap=None,
    on_select_step=None,
    on_refine_plan=None,
):
    """Render a compact project roadmap with optional architecture and moodboard details."""
    if not plan: return
    st.markdown("## Your build journey")
    st.caption("Pick a step to see what it involves. Start when you’re ready; you can change direction any time.")
    steps = st.session_state.get("plan_steps", [])
    if error := st.session_state.get("roadmap_error"):
        st.warning(error)

    if steps:
        expanded = st.session_state.get("roadmap_expanded", False)
        completed_count = sum(step.get("status") == "done" for step in steps)
        st.progress(
            completed_count / len(steps),
            text=f"{completed_count} of {len(steps)} steps complete",
        )
        current_step = st.session_state.get("current_step") or steps[0]
        current_id = current_step.get("id")
        timeline_nodes = []
        for index, step in enumerate(steps):
            step_id = step.get("id", f"step_{index}")
            done = step.get("status") == "done"
            active = step_id == current_id
            state = "done" if done else "active" if active else "upcoming"
            icon = "✓" if done else f"{index + 1:02d}"
            timeline_nodes.append(
                f'<div class="roadmap-node {state}" aria-label="Step {index + 1}: {state}">'
                f'<span class="roadmap-node-icon">{icon}</span>'
                f'<span class="roadmap-node-title">{html.escape(str(step.get("title", f"Step {index + 1}")))}</span>'
                "</div>"
            )
        st.markdown(
            '<div class="roadmap-track" aria-label="Project roadmap">'
            + "".join(timeline_nodes)
            + "</div>",
            unsafe_allow_html=True,
        )

        if on_expand_roadmap:
            label = "Show short roadmap" if expanded else "Expand into coding steps"
            st.button(
                label,
                key="expand_roadmap_btn",
                icon=":material/keyboard_double_arrow_down:",
                on_click=on_expand_roadmap,
            )

        for start in range(0, len(steps), 2):
            cols = st.columns(2)
            for offset, col in enumerate(cols):
                idx = start + offset
                if idx >= len(steps):
                    continue
                step = steps[idx]
                step_id = step.get("id", f"step_{idx}")
                is_done = step.get("status") == "done"
                is_active = step_id == current_id
                with col:
                    with st.container(border=True):
                        if is_done:
                            st.badge("Complete", icon=":material/check_circle:", color="green")
                        elif is_active:
                            st.badge("Selected", icon=":material/radio_button_checked:", color="blue")
                        else:
                            st.badge(f"Step {idx + 1}", icon=":material/pending:", color="gray")
                        st.markdown(f"### {html.escape(str(step.get('title', f'Step {idx + 1}')))}")
                        if description := step.get("description"):
                            st.write(description)
                        if is_active:
                            with st.expander("What this step involves", expanded=False):
                                if approach := step.get("approach"):
                                    st.write(approach)
                                if paths := step.get("suggested_file_paths"):
                                    st.caption("Planned files: " + ", ".join(f"`{path}`" for path in paths))
                        if not is_active:
                            if on_select_step:
                                on_click = lambda selected=step: on_select_step(selected)
                            else:
                                on_click = lambda selected=step: st.session_state.__setitem__("current_step", selected)
                            st.button(
                                "Choose this step",
                                key=f"choose_roadmap_step_{step_id}_{idx}",
                                icon=":material/arrow_forward:",
                                type="secondary",
                                width="stretch",
                                on_click=on_click,
                            )

        if not expanded:
            st.caption("Need more guidance? Expand the roadmap for practical, file-by-file coding steps.")

    if on_start_development:
        st.space("small")
        if st.button(
            "Start building",
            type="primary",
            key="start_development_btn",
            icon=":material/rocket_launch:",
            width="stretch",
            help="Create the planned files and open your workspace with the selected step ready.",
        ):
            on_start_development()

    # ===== ARCHITECTURE & FULL PLAN TOGGLE =====
    st.markdown("---")
    show_full = st.toggle("Show Full Plan (Architecture & Files)", value=st.session_state.get("show_full_plan", False), key="toggle_show_full_plan")
    st.session_state["show_full_plan"] = show_full

    if show_full:
        # ===== ARCHITECTURE BLUEPRINT =====
        st.markdown(f"### Architecture Blueprint: {plan.get('summary', 'Project Plan')}")

        # ===== FILE STRUCTURE =====
        st.markdown("### File Structure")
        folders = plan.get("folders", [])
        if folders:
            st.markdown("#### Directory Structure")
            st.markdown(" ".join(f"`{f}`" for f in folders))
        files = plan.get("files", [])
        if files:
            st.markdown("#### Planned Files")
            n_cols = 3
            for i in range(0, len(files), n_cols):
                cols = st.columns(n_cols)
                for j, f in enumerate(files[i:i + n_cols]):
                    with cols[j]:
                        st.markdown(f"""
                        <div class="card">
                            <div style="display:flex; align-items:center; gap:6px;">
                                <span class="status-dot blue"></span>
                                <strong style="color:#ffffff;">{html.escape(str(f["path"]))}</strong>
                            </div>
                            <div style="color:#94a3b8; font-size:12px; margin-top:4px;">{html.escape(str(f.get("description", "")))}</div>
                        </div>
                        """, unsafe_allow_html=True)

    moodboard_items = st.session_state.get("moodboard_items", [])
    if st.button(
        "Feed moodboard into architect",
        width="stretch",
        disabled=not moodboard_items,
        help="Refine the reviewed architecture using your research and design notes.",
        icon=":material/psychology:",
        type="primary",
    ):
        summary_notes = "\n".join(
            "- [" + str(item.get("type", "Note")) + " - " + str(item.get("title", "")) + "]: "
            + str(item.get("content", ""))
            for item in moodboard_items
        )
        if on_refine_plan:
            on_refine_plan(summary_notes)
        else:
            feed_prompt = (
                "Please refine the architecture taking into account these research and design "
                f"notes from the moodboard:\n{summary_notes}"
            )
            st.session_state.setdefault("messages", []).append({"role": "user", "content": feed_prompt})
            st.toast("Moodboard notes added to the conversation.", icon=":material/psychology:")
            st.rerun()

    # ===== MOODBOARD/RESEARCH CARDS =====
    with st.expander("Explore Moodboard & Research Cards (Optional)", expanded=False):
        # Interactive Ideation & Research Section
        if "moodboard_items" not in st.session_state:
            st.session_state["moodboard_items"] = []

        st.markdown("### Notes and references")
        items = st.session_state.get("moodboard_items", [])
        if items:
            n_cols = min(len(items), 3)
            cols = st.columns(n_cols)
            for idx, item in enumerate(items):
                col_target = cols[idx % n_cols]
                with col_target:
                    with st.container(border=True):
                        title = item.get("title", "Untitled note")
                        content = item.get("content", "")
                        cat = item.get("type", "Note")
                        dot_color = "#3b82f6" if cat == "Architecture" else "#22c55e" if cat == "Core Mechanic" else "#ec4899"
                        st.markdown(f'<span class="status-dot" style="background:{dot_color};"></span><span style="color:#94a3b8;font-size:11px;font-weight:600;text-transform:uppercase;">{html.escape(str(cat))}</span>', unsafe_allow_html=True)
                        st.markdown(f"**{title}**")
                        is_url = isinstance(content, str) and content.startswith(("https://", "http://"))
                        is_image = is_url and content.lower().split("?", 1)[0].endswith((".png", ".jpg", ".jpeg", ".gif", ".webp"))
                        if is_image:
                            st.image(content, width="stretch", alt=f"Reference image for {title}")
                        elif is_url:
                            st.link_button("Open reference", content, icon=":material/open_in_new:", width="stretch")
                        elif content:
                            st.markdown(content)
                    item_id = item.get("id", f"mb_{idx}")
                    if st.button("Remove", key=f"del_mb_{item_id}", width="content", icon=":material/close:"):
                        st.session_state["moodboard_items"] = [x for x in items if x.get("id") != item_id]
                        st.rerun()
        else:
            st.caption("No research cards yet. Add research links or architecture ideas below.")

        with st.expander("Add Research Card or Note", expanded=False):
            with st.form("new_moodboard_card_form", clear_on_submit=True):
                c_t, c_cat = st.columns([2, 1])
                with c_t:
                    card_title = st.text_input("Title", placeholder="e.g. Pygame Sound Effects")
                with c_cat:
                    card_cat = st.selectbox("Category", ["Architecture", "Core Mechanic", "UI/UX", "Reference Link"])
                card_content = st.text_area("Details / URL / Snippet", placeholder="e.g. Using SDL mixer for 8-bit sound fx...", height=70)
                submitted = st.form_submit_button("Add to Moodboard", type="primary")
                if submitted and card_title.strip():
                    tag_map = {"Architecture": "arch", "Core Mechanic": "mechanic", "UI/UX": "ui", "Reference Link": "ref"}
                    new_item = {
                        "id": f"mb_{int(datetime.datetime.now().timestamp()*1000)}",
                        "type": card_cat,
                        "tag": tag_map.get(card_cat, "arch"),
                        "title": card_title.strip(),
                        "content": card_content.strip()
                    }
                    st.session_state["moodboard_items"].append(new_item)
                    st.toast("Card added to moodboard!", icon=":material/check:")
                    st.rerun()

    # Additional sections
    animations = plan.get("animations", [])
    if animations:
        st.markdown("#### Suggested Animations")
        for anim in animations:
            name = html.escape(str(anim.get("name", "")))
            description = html.escape(str(anim.get("description", "")))
            location = html.escape(str(anim.get("location", "")))
            st.markdown(f'<div class="card"><strong>{name}</strong> — {description} <span style="color:#3b82f6;">Location: {location}</span></div>', unsafe_allow_html=True)
    dependencies = plan.get("dependencies", [])
    if dependencies:
        st.markdown("#### Dependencies")
        with st.container(border=True):
            st.code("\n".join(str(dependency) for dependency in dependencies), language="text")
    run_checklist = plan.get("run_checklist", [])
    if run_checklist:
        st.markdown("#### Build and run checklist")
        for step in run_checklist:
            st.checkbox(str(step), key=f"plan_check_{str(step)}", disabled=True)

def render_ghost_writer(code: str, language: str = "python", filename: str = "main.py", is_streaming: bool = False, wrap_lines: bool = True):
    """Renders the Ghost-Writer animated code surface.
    
    Provides JetBrains Mono typography, increased line spacing (line-height: 1.75),
    word wrapping toggle for long lines or horizontal scrolling when wrap is disabled,
    streaming typewriter animation, blinking cursor, and glowing highlight lines.
    """
    escaped_code = html.escape(code)
    streaming_flag = "true" if is_streaming else "false"
    white_space_val = "pre-wrap" if wrap_lines else "pre"
    overflow_x_val = "hidden" if wrap_lines else "auto"
    word_break_val = "break-word" if wrap_lines else "normal"
    
    component_html = f"""<!doctype html><html><head><style>
      @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600;700&display=swap');
      * {{ box-sizing: border-box; margin:0; padding:0; }}
      body {{
        background: #0d1117;
        color: #e2e8f0;
        font-family: 'JetBrains Mono', Consolas, monospace;
        font-size: 13px;
        line-height: 1.75;
        padding: 12px;
        overflow-x: {overflow_x_val};
      }}
      .editor-bar {{
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding-bottom: 8px;
        margin-bottom: 8px;
        border-bottom: 1px solid #21262d;
        color: #8b949e;
        font-size: 11px;
      }}
      .filename-badge {{
        color: #58a6ff;
        font-weight: 600;
        display: flex;
        align-items: center;
        gap: 6px;
      }}
      .code-line {{
        display: flex;
        white-space: {white_space_val};
        word-break: {word_break_val};
      }}
      .line-num {{
        width: 34px;
        user-select: none;
        color: #484f58;
        text-align: right;
        padding-right: 12px;
        flex-shrink: 0;
      }}
      .line-content {{
        flex: 1;
        white-space: {white_space_val};
        word-break: {word_break_val};
      }}
      .typing-glow {{
        background: linear-gradient(90deg, rgba(59, 130, 246, 0.16) 0%, rgba(59, 130, 246, 0) 100%);
        border-left: 2px solid #58a6ff;
        box-shadow: inset 0 0 10px rgba(59, 130, 246, 0.1);
      }}
      .cursor {{
        display: inline-block;
        width: 8px;
        height: 15px;
        background: #58a6ff;
        vertical-align: middle;
        margin-left: 2px;
        box-shadow: 0 0 8px #58a6ff;
        animation: blink 0.8s infinite;
      }}
      @keyframes blink {{
        0%, 100% {{ opacity: 1; }}
        50% {{ opacity: 0; }}
      }}
    </style></head><body>
      <div class="editor-bar">
        <span class="filename-badge">● {html.escape(filename)}</span>
        <span>{html.escape(language.upper())} · GHOST-WRITER ACTIVE</span>
      </div>
      <div id="editor-body"></div>
      <script>
        (function() {{
          const rawCode = {repr(code)};
          const isStreaming = {streaming_flag};
          const container = document.getElementById('editor-body');

          if (!isStreaming) {{
            const lines = rawCode.split('\\n');
            let out = '';
            lines.forEach((ln, idx) => {{
              const isLast = (idx === lines.length - 1);
              out += '<div class="code-line ' + (isLast ? 'typing-glow' : '') + '">' +
                     '<span class="line-num">' + (idx + 1) + '</span>' +
                     '<span class="line-content">' + escapeHtml(ln) + (isLast ? '<span class="cursor"></span>' : '') + '</span>' +
                     '</div>';
            }});
            container.innerHTML = out;
            return;
          }}

          // Streaming Typewriter Effect
          let idx = 0;
          const speed = Math.max(4, Math.floor(1200 / (rawCode.length || 1)));
          function typeNext() {{
            if (idx <= rawCode.length) {{
              const current = rawCode.slice(0, idx);
              const lines = current.split('\\n');
              let out = '';
              lines.forEach((ln, lIdx) => {{
                const isCur = (lIdx === lines.length - 1);
                out += '<div class="code-line ' + (isCur ? 'typing-glow' : '') + '">' +
                       '<span class="line-num">' + (lIdx + 1) + '</span>' +
                       '<span class="line-content">' + escapeHtml(ln) + (isCur ? '<span class="cursor"></span>' : '') + '</span>' +
                       '</div>';
              }});
              container.innerHTML = out;
              container.scrollTop = container.scrollHeight;
              idx += Math.max(1, Math.floor(rawCode.length / 80));
              if (idx <= rawCode.length) {{
                setTimeout(typeNext, 20);
              }}
            }}
          }}
          typeNext();

          function escapeHtml(str) {{
            return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
          }}
        }})();
      </script>
    </body></html>"""
    st.components.v1.html(component_html, height=280, scrolling=True)


@st.fragment
def render_live_output_window(target_dir: str, tree: dict):
    """Renders the Live Output Window (Right Pane of the Development Studio).
    
    Automatically hot-reloads when files change or AI patches are applied.
    Detects Web Apps (renders live HTML iframe preview) or Python Scripts
    (provides instant Execution + streamed console logs).
    """
    preview_files = sorted(
        node_id for node_id, node in tree.items()
        if node.get("type") == "file"
        and Path(node_id).suffix.lower() in {".html", ".htm", ".xhtml", ".py", ".md", ".markdown"}
    )
    if not preview_files:
        st.info("Add an HTML or Python file to preview your project.")
        return

    preferred = next(
        (path for path in preview_files if Path(path).name.casefold() == "index.html"),
        next(
            (path for path in preview_files if Path(path).name.casefold() in {"app.py", "main.py", "run.py"}),
            preview_files[0],
        ),
    )
    if st.session_state.get("preview_entry_file") not in preview_files:
        st.session_state["preview_entry_file"] = preferred
    file_col, refresh_col = st.columns([3, 1], vertical_alignment="bottom")
    with file_col:
        preview_file = st.selectbox("File to preview", preview_files, key="preview_entry_file")
    with refresh_col:
        refreshed = st.button(
            "Refresh preview",
            key="refresh_preview",
            icon=":material/refresh:",
            help="Reload the selected file preview.",
        )

    info = detect_workspace_preview_type(target_dir, preview_file)
    preview_type = info.get("type", "empty")
    entry_file = info.get("entry_file", "None")
    entry_path = info.get("entry_path")

    st.caption(f"Previewing `{entry_file}` · {preview_type}")

    if preview_type == "web" and entry_path:
        cache_bust = time.time_ns() if refreshed else ""
        preview_url = get_static_preview_url(
            target_dir, entry_file, cache_bust=cache_bust
        )
        if preview_url:
            st.iframe(preview_url, height=520)
        else:
            st.error(f"Could not load `{entry_file}` in the local preview.")
    
    elif preview_type == "python":
        if entry_path and is_streamlit_app(entry_path):
            preview_col, _ = st.columns([1, 2])
            with preview_col:
                run_app = st.button(
                    "Run app",
                    key="live_run_streamlit_app_btn",
                    type="primary",
                    icon=":material/play_arrow:",
                    width="stretch",
                )
            preview_url = None
            preview_error = None
            if run_app:
                with st.spinner(f"Starting {entry_file}..."):
                    preview_url, preview_error = start_streamlit_preview(
                        entry_path, working_directory=target_dir
                    )
                st.session_state["streamlit_preview_file"] = str(entry_path.resolve())
                st.session_state["streamlit_preview_url"] = preview_url
                st.session_state["streamlit_preview_error"] = preview_error
            elif st.session_state.get("streamlit_preview_file") == str(entry_path.resolve()):
                preview_url = st.session_state.get("streamlit_preview_url")
                preview_error = st.session_state.get("streamlit_preview_error")

            if preview_error:
                st.error(f"Could not start the app preview: {preview_error}")
            elif preview_url:
                version = entry_path.stat().st_mtime_ns
                st.iframe(
                    f"{preview_url}?forge_preview={version}",
                    height=520,
                )
            else:
                st.info("Run the app to open it in the preview window.")
            return

        run_col, clear_col = st.columns(2)
        with run_col:
            run_btn = st.button("Run", key="live_run_output_btn", type="primary", icon=":material/play_arrow:", width="stretch")
        with clear_col:
            if st.button("Clear", key="live_clear_console_btn", icon=":material/delete_sweep:", width="stretch"):
                st.session_state["console_history"] = []
                st.session_state["last_preview_error"] = None
                st.rerun()
        
        auto_run_requested = st.session_state.pop("auto_run_file", None)
        if run_btn or auto_run_requested == preview_file:
            target_to_run = preview_file
            run_abs_path = safe_file_path(target_dir, target_to_run)
            if run_abs_path is None:
                stdout, stderr = "", f"Invalid preview path: {target_to_run}"
            else:
                with st.spinner(f"Running {target_to_run}..."):
                    stdout, stderr = run_python_preview(run_abs_path)
            
            if stderr:
                st.session_state["last_preview_error"] = {"file": target_to_run, "stderr": stderr}
            else:
                st.session_state["last_preview_error"] = None
                st.session_state["preview_update_glow"] = True

            out_entry = f"$ python {target_to_run}\n{stdout or '(No stdout)'}"
            if stderr:
                out_entry += f"\n\n[STDERR / Traceback]:\n{stderr}"
            st.session_state.setdefault("console_history", []).append(out_entry)
            st.session_state["console_history"] = st.session_state["console_history"][-8:]

        history = st.session_state.get("console_history", [])
        body_text = "\n\n".join(history) if history else f"Ready to execute `{entry_file}`. Press Run above."
        st.code(body_text, language="text")
        
        # Self-Healing Action Button if an error is detected in stderr
        last_err = st.session_state.get("last_preview_error")
        if last_err and last_err.get("stderr"):
            heal_col1, heal_col2 = st.columns([2.5, 1.5], vertical_alignment="center")
            with heal_col1:
                st.markdown(f'<span style="color:#ef4444; font-size:12px; font-weight:600;">⚠️ Error in <code>{html.escape(str(last_err["file"]))}</code></span>', unsafe_allow_html=True)
            with heal_col2:
                if st.button("Auto-Heal Code", key="auto_heal_code_btn", type="primary", icon=":material/healing:", width="stretch"):
                    heal_prompt = f"The preview execution of `{last_err['file']}` failed with this stderr error:\n```\n{last_err['stderr']}\n```\nPlease diagnose the root cause and provide the exact fixed code to self-heal and resolve this error completely."
                    st.session_state["pending_ai_prompt"] = heal_prompt
                    st.session_state["last_preview_error"] = None
                    st.rerun()
    
    else:
        # Default empty/scaffolded workspace preview
        st.info(f"`{entry_file}` is not a supported preview type.")
