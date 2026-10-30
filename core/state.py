DEFAULTS = {
    "app_stage": "home",
    "architecture_plan": None,
    "plan_scaffolded": False,
    "target_dir": "",
    "selected_model": None,
    "messages": [],
    "events": [],
    "apply_status": None,
    "show_ai": True,
    "flow_timestamp": 0,
    "console_history": [],
    "last_ai_request": None,
    "last_failed_ai_request": None,
    "moodboard_items": [
        {"id": "mb_1", "type": "Architecture", "tag": "arch", "title": "Modular Services", "content": "Keep core business logic in /services and LLM provider logic in /core."},
        {"id": "mb_2", "type": "Mechanic", "tag": "mechanic", "title": "Watchdog Observer", "content": "File changes trigger automatic canvas synchronization via background thread."},
        {"id": "mb_3", "type": "Reference", "tag": "ref", "title": "Low Latency Inference", "content": "Groq / Nebius endpoint acceleration for real-time code patches."}
    ],
    "plan_steps": [],
    "short_plan_steps": [],
    "roadmap_expanded": False,
    "roadmap_error": None,
    "roadmap_loaded_for": None,
    "current_step": None,
    "plan_status": "review",
    "left_pane_collapsed": False,
    "output_pane_collapsed": False,
    "active_studio_tab": "preview",
    "last_patch_files": [],
    "ghost_writer_active": False,
    "live_reload_key": 0,
    "auto_apply": False,
    "focus_mode": False,
    "last_preview_error": None,
    "preview_update_glow": False,
    "project_mode": "Basic Mode",
    "show_full_plan": False,
    "wrap_lines": True,
}


class SessionStateManager:
    """Small, explicit home for app-wide Streamlit session defaults and stage moves."""

    @staticmethod
    def initialize(state) -> None:
        for key, value in DEFAULTS.items():
            state.setdefault(key, value)
        state.setdefault("recent_projects", [])
        state.setdefault("target_dir", "")

    @staticmethod
    def go_to(state, stage: str, **updates) -> None:
        state.update(updates)
        state["app_stage"] = stage
