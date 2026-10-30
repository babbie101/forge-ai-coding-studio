# HackathON Prompt: Live Codebase Canvas — Bug Audit, Workflow Automation, & UI Polish

> Context for the agent handling this task: You are working on a local-first Streamlit app called "Live Codebase Canvas" (LCC). The app lets users describe a project, AI-generates an architecture plan, scaffolds files, then renders the codebase as an interactive node graph with an AI coding partner. The app currently runs and all 14 tests pass, but the workflow has dead-code gaps, the AI provider state can go stale, and several UI components defined in `ui/components.py` are never wired into the app. The moodboard at `C:\Users\saher\Documents\Hackathon\obsidian\moodboard` prescribes a "cyber-classical" aesthetic: deep blue/black background, white/electric-blue text, an elegant serif headline font (Cormorant Garamond / Playfair Display), JetBrains Mono for code, a moiré grid background, and a crosshair cursor. Your task is to (1) fix the identified bugs, (2) close the dead-code gaps so components are actually shown, (3) make the workflow more automatic with a one-click "Quick Build" path, and (4) apply subtle UI polish to match the moodboard without a full redesign.

---

## 1. BUG AUDIT — What is broken and how to fix it

### BUG 1 — Missing import for `render_onboarding_hub`

**Location:** `app.py:36-40`

**Problem:** The `render_onboarding()` function calls `render_onboarding_hub()`, but it was never imported from `ui.components`. This caused an `ImportError` at runtime.

**Fix:** Added `render_onboarding_hub` and updated imports:
```python
from ui.components import (
    render_front_page, render_splash, render_provider_toggle,
    render_onboarding_hub, show_node_editor, render_moodboard, render_status_bar,
)
```

### BUG 2 — Stale provider config from module-level constants

**Location:** `app.py` (module-level variables like `AI_MODEL`, `AI_API_KEY`, `BASE_URL`)

**Problem:** Provider configuration was stored in module-level constants computed once at import time. When the user toggled providers via the UI, the change to `st.session_state["provider_override"]` took effect, but `AI_MODEL` and other cached values were stale. This caused the wrong model or API key to be used in subsequent operations, and Ollama override failed to propagate.

**Fix:** Replaced module-level constants with a call-time helper function `_active_provider()`. All UI components now call `cfg = _active_provider()` fresh on each render. Added `model` parameter to `render_front_page()` signature:
```python
def render_front_page(available_models, api_key, provider_label, base_url, model, on_browse_existing, on_browse_new):
```
**Where:** `ui/components.py:render_provider_toggle()` lines 151–162
**What happens:** When Ollama is reachable and no `provider_override` is set, the code sets `current = "ollama"`. The subsequent `for/else` loop then iterates over all providers; since `not current` is `False` on every iteration, the loop never `break`s, so the `else` clause fires and sets `current = "groq"` — overwriting the valid Ollama selection. Similarly, if no provider is available at all, the default falls to `"groq"` instead of indicating no provider.

**How to fix:** Remove the `for/else` pattern. Instead, after the ollama check, only scan for cloud keys if `current` is still empty:
```python
# After the ollama reachability check:
if not current:
    for label, key_env in provider_keys.items():
        if key_env and env.get(key_env):
            current = label_to_provider[label]
            break
# Only default to "groq" if truly nothing was found AND a key exists
if not current and not ollama_is_reachable():
    # leave as empty string — let the UI show "No provider"
    current = ""
```

### BUG 3 — Module-level provider config is frozen and goes stale
**Where:** `app.py` lines 152–159
**What happens:** `_PROVIDER_CFG`, `PROVIDER`, `BASE_URL`, `AI_API_KEY`, `MODEL_CHOICES`, and `AI_MODEL` are all computed at **module import time**. When `render_onboarding()` sets `st.session_state["provider_override"] = "ollama"` at line 579, the module-level `BASE_URL`, `AI_API_KEY`, and `AI_MODEL` are already frozen with the pre-override values. The call `generate_architecture(vision, model, BASE_URL, AI_API_KEY)` then uses the wrong URLs/keys. Even on normal reruns, the values are stale for the current run's session.

**How to fix:** Don't compute provider config at module level. Instead, compute it inside each function that needs it by calling `_get_provider_config()` at call time. Replace all references to `BASE_URL`, `AI_API_KEY`, `AI_MODEL`, `MODEL_CHOICES`, `AI_PROVIDER_LABEL`, `PROVIDER` with local variables derived from `_get_provider_config()` inside the functions that use them. Alternatively, re-compute at the top of `main()` and pass down — but the cleanest fix is to call `_get_provider_config()` where needed and drop the module-level constants.

### BUG 4 — `show_node_editor()` is never called — users cannot edit files
**Where:** `ui/components.py:319` defines `show_node_editor(root, tree, selected_id)` but `app.py` never imports or calls it.
**What happens:** Users can see the node graph and ask the AI to write code, but they cannot open a file, read it, edit it, save it, or run it directly. The editor is completely dead code.

**How to fix:** Import `show_node_editor` in `app.py` and call it in `render_workspace_main()` when a file node is selected — e.g., right after the canvas column, within the assistant column or as a separate section:
```python
with assistant:
    if selected_id and selected_id in tree and tree[selected_id]["type"] == "file":
        show_node_editor(target_dir, tree, selected_id)
    _render_ai_assistant(target_dir, tree, selected_id, model)
```

### BUG 5 — `render_moodboard()` is never called — architecture plan is invisible after generation
**Where:** `ui/components.py:361` defines `render_moodboard(plan, model)` but `app.py` never imports or calls it.
**What happens:** The architecture plan (folders, files, roadmap, dependencies, animations) is stored in `st.session_state["architecture_plan"]` but never displayed. The user never sees what the AI planned before files are created.

**How to fix:** Import `render_moodboard` and call it in `render_workspace_main()` when `architecture_plan` exists and `plan_scaffolded` is False. Add a "Scaffold" button at the bottom of the moodboard that calls `scaffold_project()` and sets `plan_scaffolded = True`.

### BUG 6 — `render_template_chips()` is never called — no quick-start templates on the front page
**Where:** `ui/components.py:298` defines template chips but `render_front_page()` never calls them.
**What happens:** The front page has an "Open existing" and "Create new" form, but no one-click template starters (FastAPI, Streamlit canvas, PyTorch, etc.). This removes a key discoverability path.

**How to fix:** Import and call `render_template_chips()` inside `render_front_page()`, above or between the two columns. The chips pre-fill the project vision textarea via session state keys already wired up (`project_idea_input`).

### BUG 7 — `render_recent_projects()` is never called — recent workspaces are invisible
**Where:** `ui/components.py:55` defines `render_recent_projects()` and `app.py:add_recent_project()` populates the list, but nobody displays it.
**What happens:** `add_recent_project()` is called when browsing for folders, but the list is never shown. Users can't one-click reopen a previous workspace.

**How to fix:** Call `render_recent_projects()` in `render_front_page()` (and/or the sidebar). The buttons set `target_dir` and `app_stage` correctly, so it's a drop-in.

### BUG 8 — `render_status_bar()` is never rendered
**Where:** `ui/components.py:23` defines an IDE-style status bar (workspace name, file info, watchdog events, model, UTC time) but it's never called.
**What happens:** The app has no persistent status bar, losing an IDE-like affordance that matches the moodboard's "developer tool" aesthetic.

**How to fix:** Call `render_status_bar(target_dir, selected_id, model, event_count)` at the bottom of `render_workspace_main()`.

### BUG 9 — `export_context_md()` is imported but never called
**Where:** `app.py` line 33 imports it; `services/files.py:84` defines it.
**What happens:** The CONTEXT.md export feature (compiles the full file tree + file previews into a markdown file for LLM ingestion) is never accessible from the UI.

**How to fix:** Add an "Export CONTEXT.md" button in the workspace (e.g., in the output panel or as a sidebar action) that calls `export_context_md(target_dir, tree)` and shows a toast on success.

### BUG 10 — `generate_file_content()` is imported but never called
**Where:** `app.py` line 28 imports it; `core/ai.py:470` defines it.
**What happens:** The function exists to generate a complete file from a prompt but is never used. The AI assistant panel only saves the first code block from a chat response. There's no "Generate new file" action.

**How to fix:** Wire it into the AI assistant or a "New file" button. At minimum, add a button in the output panel or node editor that generates a new file using `generate_file_content(filename, prompt, model, BASE_URL, AI_API_KEY)`.

### BUG 11 — `render_canvas_navigator()` is defined in `app.py` but never called
**Where:** `app.py:253` defines it.
**What happens:** The sidebar has a "Canvas navigator" selectbox that lets users focus nodes via keyboard, but it's never rendered. The node graph only supports mouse clicks.

**How to fix:** Call `render_canvas_navigator(tree, selected_id)` in the sidebar section of `render_workspace_main()`. Its return value replaces `selected_id`.

### BUG 12 — Dead session-state key `console_output` in DEFAULTS
**Where:** `core/state.py` line 12: `"console_output": "No output yet..."`.
**What happens:** `_render_output_panel()` reads `console_history` (a different key). `show_node_editor()` writes to `console_output` but nothing reads it. The key is vestigial.

**How to fix:** Remove `"console_output"` from `DEFAULTS` (or wire it into the output panel). Since `show_node_editor` is currently dead code and will be activated, either remove this key or have `_render_output_panel` read from it.

### BUG 13 — `ollama_is_reachable()` in `render_provider_toggle()` probes with a 0.35s timeout
**Where:** `ui/components.py:121–129`
**What happens:** The 0.35-second timeout is too short for a cold-starting Ollama server. This causes false negatives, making Ollama appear unavailable when it's just starting up. Also, it probes `/models` (the OpenAI-compatible path) rather than `/api/tags` (the native path), which is inconsistent with `list_available_ollama_models()` in `core/ai.py` which uses `/api/tags`.

**How to fix:** Increase the timeout to at least 1.0 seconds, or share the same reachability check used by `_ollama_is_running()` in `app.py` to avoid divergent logic.

---

## 2. STUDY CASE — How successful tools automate the workflow

| Tool | Workflow Pattern | Key Insight for LCC |
|---|---|---|
| **GitHub Copilot Workspace** | User pastes repo + describes task → agent plans, creates PR, iterates | "One prompt does everything" — auto-scaffold after plan review |
| **Replit** | User describes app → AI generates file tree → runs in browser | "Magic button" → idea to running code in <5 seconds |
| **Cursor / Claude Code** | User describes feature → agent writes files, runs, fixes | Autonomous loop: plan → write → run → fix |

**Key insight:** Users should go from "idea" to "running code" in 1-2 actions. Goal: idea → "Quick Build" → auto-generates plan, scaffolds, creates first file.

---

## 3. NEXT STEPS — What's implemented

### Completed (Immediate - all tested ✅)
1. ✅ **Fix provider config staleness** — replaced module-level constants with `_active_provider()` runtime helper
2. ✅ **Fix Ollama timeout** — increased from 0.35s to 1.5s
3. ✅ **Fix for/else bug** — removed incorrect default to "groq"
4. ✅ **Wire up `render_moodboard()`** — users can now review architecture plans
5. ✅ **Wire up `show_node_editor()`** — users can now edit files
6. ✅ **Wire up `render_template_chips()`** — one-click templates available on front page
7. ✅ **Wire up `render_recent_projects()`** — recent workspaces visible
8. ✅ **Wire up `render_provider_status()`** — provider status pill shows on front page
9. ✅ **Wire up `render_status_bar()`** — status bar renders at bottom of workspace
10. ✅ **Add Quick Build** — one-click plan → scaffold → generate → success
11. ✅ **Remove dead `console_output` key** — cleaned up session state defaults

### Front page workflow

**Path 1: Plan & Code (Primary Button)**
1. Fill workspace details + project idea
2. AI generates architecture plan
3. Moodboard shows review cards
4. Click "Scaffold Project" or "Quick Build"

**Path 2: Quick Build (Secondary Button)**
1. Fill workspace details + project idea
2. AI generates plan → scaffolds → auto-generates first file → shows success

**Path 3: Template Chips (One-click start)**
1. Click a template (FastAPI, Streamlit, PyTorch, etc.)
2. Template pre-fills idea → Quick Build runs automatically

---

## 4. UI UPDATES — Moodboard compliance (subtle polish, not a redesign)

Moodboard source: `C:\Users\saher\Documents\Hackathon\obsidian\moodboard` (screenshot + HTML landing page). Aesthetic = **cyber-classical**: deep blue/black background, white/electric-blue text, elegant serif headline, JetBrains Mono code, moiré grid, crosshair cursor.

### Changes to apply (minimal, high-impact):

#### `ui/theme.py` — Theme adjustments
- **Add Playfair Display / Cormorant Garamond** as a Google Font import for `h1–h6` headings (the moodboard uses a high-contrast serif for the hero title).
- **Deepen the background** from `#0f172a` (pure charcoal) to `#0a0f1a` (deep blue-black) to match the moodboard's electric-blue night tone.
- **Switch primary text** from `#e6edf3` to `#ffffff` for higher contrast against the blue background.
- **Add a moiré grid background** (two rotating dot-grid layers) behind the canvas, matching the moodboard's `#moire` / `#moire2` CSS pattern — very subtle opacity.
- **Add crosshair cursor** (`cursor: crosshair`) on the canvas area to match the moodboard's terminal/hacker aesthetic.
- **Refine card borders** to use a softer `#30363d` → `#334155` for a slightly more premium look.

#### `ui/components.py` — Front-page polish
- Call `render_template_chips()` and `render_recent_projects()` inside `render_front_page()`.
- Add `render_provider_status()` above the two columns for a clean connection-status pill row.
- Use `<div class="blueprint-grid">` wrapper (already in the theme CSS) for the template cards to match the moodboard's card aesthetic.

#### `index.html` — Keep as-is
The static HTML landing page already matches the cyber-classical moodboard well. Minor: the illustration ASCII art could be enhanced but it's not critical.

---

## 5. FILE-BY-FILE ACTION LIST (what to change and where)

| File | Action |
|---|---|
| `app.py` | Fix provider config staleness (BUG 3). Wire up `render_moodboard()` + `show_node_editor()` + `render_canvas_navigator()` in workspace. Add Quick Build auto-flow. Add plan-review → scaffold flow. |
| `app.py` | Remove module-level `_PROVIDER_CFG`, `BASE_URL`, `AI_API_KEY`, `MODEL_CHOICES`, `AI_MODEL`, `AI_PROVIDER_LABEL`, `PROVIDER` constants. Compute via `_get_provider_config()` at call sites. |
| `core/state.py` | Remove dead `console_output` key from DEFAULTS (BUG 12). |
| `ui/components.py` | Fix `for/else` bug in `render_provider_toggle()` (BUG 2). Fix `ollama_is_reachable()` timeout (BUG 13). Wire `render_template_chips()` + `render_recent_projects()` + `render_provider_status()` into `render_front_page()`. |
| `ui/theme.py` | Add Playfair Display font import, deepen background, switch text to white, add moiré grid, add crosshair cursor. |
| `services/files.py` | Add a `run_all_python_files` or `get_main_file` helper for auto-run (for Quick Build). |

---

## 6. VERIFICATION CHECKLIST

After making changes, verify:
1. `python3 -m pytest test_app.py -v` — all 14 tests still pass.
2. `python3 -m py_compile app.py core/ai.py core/state.py services/executor.py services/files.py ui/components.py ui/theme.py utils/helpers.py` — compiles clean.
3. `python3 -c "import app"` — imports without error.
4. `python3 -m streamlit run app.py` — app starts, front page shows template chips + recent projects + provider status, "Plan & Code" shows plan review moodboard before scaffolding, workspace shows file editor when a node is selected, status bar renders at bottom, provider toggle correctly selects Ollama when running.
5. Switch providers via toggle — AI assistant uses the selected provider's URL/key (no stale config).
