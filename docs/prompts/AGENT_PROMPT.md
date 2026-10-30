# AGENT PROMPT: Live Codebase Canvas — Bug Audit, Workflow Automation & UI Polish

> **Context.** You are working on the *Live Codebase Canvas* (LCC), a local-first Streamlit
> app. Users describe a project idea, AI generates an architecture plan, scaffolds files
> on disk, then renders the codebase as an interactive node graph with an AI coding partner,
> file editor, and Python runner. The app currently starts and 13/14 tests pass. This prompt
> documents (1) bugs found in the current code, (2) a workflow-automation study, (3) next steps
> to make the user journey more automatic, and (4) subtle UI polish to match the moodboard at
> `C:\Users\saher\Documents\Hackathon\obsidian\moodboard`.
>
> **Project layout** (relevant files):
> - `app.py` — main Streamlit app, routing, provider detection, canvas, AI assistant
> - `core/ai.py` — AI provider configs, chat, patch extraction, file generation
> - `core/state.py` — session-state defaults
> - `services/files.py` — tree scanning, file I/O, CONTEXT.md export
> - `services/executor.py` — Python subprocess runner
> - `ui/theme.py` — CSS theme injection
> - `ui/components.py` — all UI rendering functions (front page, moodboard, node editor, status bar, etc.)
> - `ui/bitmap_animation.py` — rotating 3D ASCII sphere widgets
> - `utils/helpers.py` — path safety, dialog picker
> - `test_app.py` — 14 AppTest-based integration tests (13 pass, 1 times out)
>
> Moodboard references:
> - Screenshot: `Screenshot 2026-10-11 210349.png` — electric-blue/black bg, white text, high-contrast Bodoni/Didot serif headline, geometric sans-serif UI, wide letter-spacing, split-screen layout, mythological line-art illustration, terminal-style install commands, crosshair cursor.
> - HTML: `immortal — what if a coin could live forever_.html` — pure-black bg, white text, Cormorant Garamond (italic) serif, Space Mono monospace, animated rotating moiré grid, canvas particle animations (lemniscate, ring illusion, tunnel zoom), pointer-trail effect, glassmorphic modals, crosshair cursor.
> - Current theme (`ui/theme.py`) already matches ~80%: deep blue-black bg, white text, Playfair Display headings, JetBrains Mono code, static moiré grid, crosshair cursor. Polish targets the remaining 20%.

---

## 1. BUG AUDIT — Current bugs found in the codebase

### BUG 1  (CRITICAL) — `submit_mode="disable"` makes the AI chat permanently non-functional

**Location:** `app.py:391`

```python
chat_input_val = st.chat_input("Ask the AI to code...", disabled=not api_key, submit_mode="disable")
```

**What happens:** In Streamlit 1.65, `submit_mode` accepts `"submit"` (default), `"disable"`, or `"stop"`. With `"disable`, pressing Enter does NOT submit the chat input — the return value is **always `None`** on every render. Since `active_prompt = chat_input_val` is always `None`, the `if active_prompt and api_key:` guard on line 394 is never entered. The user can type in the chat box, press Enter, and nothing ever happens. The entire AI coding-assistant panel is dead.

**How to fix:** Remove `submit_mode="disable"` entirely (the default `"submit"` is correct), or explicitly set `submit_mode="submit"`:

```python
chat_input_val = st.chat_input("Ask the AI to code...", disabled=not api_key)
```

---

### BUG 2  (CRITICAL) — Quick Build auto-generation never fires

**Location:** `app.py:501-506`

```python
if st.button("✅ Scaffold Project", type="primary", key="scaffold_plan", icon=":material/construction:")\
    or st.session_state.pop("quick_build", False):          # <-- pop #1 consumes the flag
    scaffold_project(target_dir, plan, st.session_state.get("project_idea", ""))
    st.session_state["plan_scaffolded"] = True
    st.session_state["architecture_plan"] = None
    if st.session_state.pop("quick_build", False):          # <-- pop #2 always gets False
        # Auto-generate + save the first file after scaffolding
        ...
```

**What happens:** When the user clicks "⚡ Quick Build" (line 541-543), it sets `st.session_state["quick_build"] = True` and reruns. On the next render:

1. Line 502: the `Scaffold Project` button was NOT clicked, so Python evaluates the right side of the `or`. `st.session_state.pop("quick_build", False)` returns `True` — the flag is **consumed and removed** from session state.
2. The `if` block runs: `scaffold_project()` creates the files.
3. Line 506: `st.session_state.pop("quick_build", False)` is called again — but the flag was already popped on line 502, so it returns `False`. The auto-generation block is **skipped entirely**.

The net result: Quick Build scaffolds files but never auto-generates the first file. The user gets an empty project and no indication of why.

**How to fix:** Store the popped value in a local variable before the `or`:

```python
quick_build_requested = st.session_state.pop("quick_build", False)
if st.button("✅ Scaffold Project", type="primary", key="scaffold_plan", icon=":material/construction:") \
        or quick_build_requested:
    scaffold_project(target_dir, plan, st.session_state.get("project_idea", ""))
    st.session_state["plan_scaffolded"] = True
    st.session_state["architecture_plan"] = None
    if quick_build_requested:
        # Auto-generate + save the first file after scaffolding
        ...
```

---

### BUG 3 — Moodboard "Feed to Architect" writes to a key nobody reads

**Location:** `ui/components.py:444-453` (the `render_moodboard` "Feed" button) and `app.py:372` (the AI assistant reads `messages`, not `whiteboard_messages`)

```python
# components.py:445-453 — writes to whiteboard_messages:
st.session_state.setdefault("whiteboard_messages", []).append({"role": "user", "content": feed_prompt})

# app.py:372 — reads from messages:
for index, message in enumerate(st.session_state.setdefault("messages", [])):
```

**What happens:** The "Feed moodboard into architect" button appends user notes to `st.session_state["whiteboard_messages"]`, but `_render_ai_assistant` only iterates over `st.session_state["messages"]`. The feed is silently lost. Similarly, `render_ideas_panel` (components.py:530) returns a summary string but the caller never passes it to anything.

**How to fix:** Append to `messages` instead of `whiteboard_messages`, so the AI assistant actually sees the moodboard context:

```python
st.session_state.setdefault("messages", []).append({"role": "user", "content": feed_prompt})
```

Then remove the `setdefault("whiteboard_messages", ...)` line entirely.

---

### BUG 4 — `render_onboarding` never shows provider status

**Location:** `app.py:600-610` (the `render_onboarding` function)

**What happens:** `render_front_page` calls `render_provider_status(...)` to show a connection-status pill. But `render_onboarding` (the screen where the user actually generates an architecture plan) receives `api_key`, `provider_label`, `base_url` as parameters but never calls `render_provider_status`. The user is flying blind — they don't see which provider is active or whether their key is valid before spending time writing a vision and clicking "Plan architecture."

**How to fix:** Add a `render_provider_status(...)` call at the top of `render_onboarding`, mirroring what `render_front_page` does:

```python
def render_onboarding():
    ...
    render_provider_status(
        active_provider_config["label"], active_provider_config["api_key"],
        active_provider_config["base_url"],
        active_provider_config["default_model"],
    )
    st.title("Plan your workspace", ...)
    ...
```

---

### BUG 5 — Dead code: `render_splash`, `render_ideas_panel`, `available_models` parameter

**Locations:**
- `ui/components.py:272` — `render_splash()` is imported in `app.py:37` but the routing table in `main()` maps `"splash" → front_runner` (which calls `render_front_page`), never `render_splash`. The function itself just sets `app_stage="home"` and reruns — so it's a no-op redirect that is never triggered.
- `ui/components.py:493` — `render_ideas_panel()` is defined but never imported or called anywhere.
- `app.py:188, 701` — `render_front_page` accepts `available_models` as its first parameter but never references it in its body. In `main()`, `available_chat_models()` is called to produce the value, but the result is unused inside the function.

**Fix:** Remove `render_splash` and `render_ideas_panel` (or wire them in if the splash stage is needed). Remove the `available_models` parameter from `render_front_page` and the call site in `main()`, OR use it to render a model-preview dropdown on the front page.

---

### BUG 6 — `provider_override_select` is set but never read

**Location:** `app.py:644-645`

```python
if _ollama_is_running() and not st.session_state.get("provider_override"):
    st.session_state["provider_override"] = "ollama"
    st.session_state["provider_override_select"] = "Ollama (Local)"
```

**What happens:** `provider_override_select` is written here but no code anywhere reads it. It's vestigial state from a previous UI design where a selectbox label was tracked separately.

**How to fix:** Remove the `provider_override_select` line. Only `provider_override` (the internal provider key) is read by `_get_active_provider()`.

---

### BUG 7 — Test `test_new_workspace_opens_the_live_workspace` times out

**Location:** `test_app.py:110-119`

```python
def test_new_workspace_opens_the_live_workspace(tmp_path: Path):
    at = AppTest.from_file("app.py").run(timeout=25)
    ...
    at.button(key="plan_from_home").click().run(timeout=25)  # <-- TIMES OUT HERE
    assert at.session_state["app_stage"] == "workspace"
```

**What happens:** Clicking "Plan & Code" sets `create_from_idea=True` and enters the workspace stage. `render_workspace_main` then calls `generate_architecture()` — a **real HTTP request** to the configured API provider. With placeholder API keys in `.env` (e.g., `OPENROUTER_API_KEY=sk-or-v1-…`), the request either hangs waiting for a network response or the provider returns an error slowly. The 25-second `AppTest` timeout is hit before the script finishes rendering.

**How to fix:** Mock `generate_architecture` in the test (or in the AppTest setup) so it returns a canned plan without making a network call:

```python
from unittest.mock import patch

def test_new_workspace_opens_the_live_workspace(tmp_path: Path):
    fake_plan = {
        "summary": "Test workspace", "folders": ["src"],
        "files": [{"path": "src/main.py", "description": "Entry point"}],
        "roadmap": [], "dependencies": [], "run_checklist": [],
    }
    with patch("app.generate_architecture", return_value=fake_plan):
        at = AppTest.from_file("app.py").run(timeout=25)
        ...
```

Alternatively, split into two tests: a UI-flow test (mocked AI) and a separate integration test for the real API call with a longer timeout.

---

### BUG 8 — `nul` artifact in repo root

**Location:** `./nul` (repo root)

**What happens:** A file named `nul` exists in the project root. On Windows, `nul` is a reserved device name — `Path("nul").exists()` returns `True` but `is_file()` returns `False` (it's the null device, not a real file). It shows up in `git status` as an untracked entry and cannot be deleted with normal file operations. It was likely created by an accidental `echo ... > nul` redirect.

**How to fix:** Remove it at the OS level: `del nul` from cmd.exe, or `rm nul` from git-bash (may need to run from cmd.exe).

---

### BUG 9 — No auto-run after Quick Build generates the first file

**Location:** `app.py:529-533` (Quick Build auto-generation block)

**What happens:** After Quick Build scaffolds files and auto-generates the first file (e.g., `src/main.py`), the user lands in the workspace. The file is on disk but `selected_id` is still `None` (or whatever was set before). The user must manually click the file node in the graph to open the editor, then click "Run code" to see output. This breaks the "idea → running code in one click" experience.

**How to fix:** After writing the file, set `st.session_state["selected_id"]` to the generated file path and trigger a focus refresh so the output panel auto-runs it:

```python
# After target_path.write_text(code, ...):
st.session_state["selected_id"] = target_name
st.session_state["flow_timestamp"] = int(time.time() * 1000)
```

And optionally auto-run: set a session flag like `st.session_state["auto_run_file"] = target_name` that `_render_output_panel` detects and triggers a run on first render.

---

## 2. STUDY CASE — How successful tools automate the "idea → code" workflow

| Tool | Workflow Pattern | Key Insight for LCC |
|---|---|---|
| **GitHub Copilot Workspace** | User describes a task → agent proposes a plan (PR with file changes) → user approves → agent iterates on review comments until done | "One prompt does everything" — plan is shown briefly, then agent proceeds autonomously. User only intervenes when something looks wrong. |
| **Replit** | User types "make a game" → AI generates full file tree + code → app runs in browser instantly | "Magic button" → idea to running app in <5 seconds. Immediate visual feedback (the app runs right away, errors are shown inline). |
| **Cursor / Claude Code** | User says "add a dark mode toggle" → agent writes files, runs tests, sees failures, fixes, re-runs — autonomously | Autonomous loop: **plan → write → run → observe failure → fix → repeat** until green. The agent doesn't hand back control after each step. |
| **Vercel v0** | User pastes a screenshot/description → AI generates React components → "Remix" with follow-up prompts | Iteration is first-class: the AI remembers context and can be re-prompted against the same artifact. |

**Key takeaways for LCC:**
1. **Reduce to 1-2 actions:** Idea → Quick Build → running code should be 1 click (auto-run the generated file).
2. **Show-then-proceed:** Display the architecture plan for 2-3 seconds as a "review" step, then auto-scaffold. Don't force a second click.
3. **Auto-execute:** After generating `app.py` or `main.py`, immediately run it and display the console output. The user should see results, not just files.
4. **Agentic loop:** Once in the workspace, the AI assistant should be able to: write a file → run it → capture errors → fix → re-run, without the user manually intervening at each step. A toggle like "Agent Mode: ON" should make this the default.
5. **Template → Run in one click:** Clicking a template chip should auto-fill the vision, pick a default model, scaffold, generate, AND run — all in one flow.

---

## 3. NEXT STEPS — Workflow automation roadmap

### Immediate (fix + wire up — prerequisite for a smooth flow)

1. **Fix BUG 1** (`submit_mode`) — the AI chat must work before anything else.
2. **Fix BUG 2** (Quick Build flag consumption) — one-liner, restores the auto-generate flow.
3. **Fix BUG 3** (feed moodboard → `messages`) — makes the "research → architect" feedback loop functional.
4. **Fix BUG 9** (auto-select + auto-run after Quick Build) — completes the "idea → running code" loop.
5. **Fix BUG 4** (provider status on onboarding) — so the user knows their key is valid before planning.

### Medium-term (auto-run + agentic loop)

6. **Auto-detect entry point:** In `_render_output_panel`, auto-select the first `.py` file whose name matches `main.py`, `app.py`, or `run.py` (in that priority). After Quick Build, auto-run it.
7. **AI "Agent Mode" toggle:** Add a boolean switch `st.session_state["agent_mode"]`. When ON, after the AI generates a code block and it's saved, the app automatically runs the file and feeds any `stderr` back to the AI with the prompt "This file produced the following errors. Fix them and regenerate." Loop until it compiles/runs cleanly (max 3 iterations).
8. **Template chip → Quick Build in one click:** Modify `render_template_chips()` so clicking a chip sets `project_idea`, fills `new_workspace_name` with a slug derived from the template, and sets `st.session_state["quick_build"] = True` — so one click goes from template to running app.
9. **Keyboard shortcuts:**
   - `Ctrl/Cmd + Enter` — submit the AI chat (explicitly submit, even if `submit_mode` is changed later).
   - `Ctrl/Cmd + S` — save the node editor.
   - `Ctrl/Cmd + K` — open a command palette (scaffold / run / export / toggle provider).

### Long-term (autonomous multi-step workflows)

10. **Scaffold → Run → Fix loop:** After scaffolding a multi-file plan, iterate: generate file 1 → run → fix → generate file 2 → import file 1 → run → fix → … The AI manages the dependency order from the plan's file list.
11. **CONTEXT.md auto-export on file change:** The watchdog observer already detects file changes — trigger `export_context_md()` automatically after each AI write so the context file is always current.
12. **Command palette:** A `Ctrl/Cmd + K` palette with actions: "Scaffold project", "Run main file", "Export CONTEXT.md", "Toggle provider", "Quick Build", "Reset workspace".

---

## 4. UI UPDATES — Moodboard compliance (subtle polish, no redesign)

The current `ui/theme.py` already captures the cyber-classical aesthetic (deep blue-black, white text, JetBrains Mono, crosshair cursor, moiré grid). The moodboard prescribes a few refinements. Apply only the high-impact, low-risk changes:

### `ui/theme.py` — Theme refinements (minimal, targeted)

a. **Swap Playfair Display → Cormorant Garamond** for headings. The moodboard screenshot uses a high-contrast Didot/Bodoni serif; Cormorant Garamond is the closest web-safe equivalent. Update the Google Fonts `@import` and the `h1–h6` `font-family`:
```css
@import url('https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600;700&display=swap');
h1,h2,h3,h4,h5,h6 { font-family: 'Cormorant Garamond', Georgia, serif !important; }
```

b. **Animate the moiré grid.** The moodboard HTML has two grid layers — one static, one slowly rotating. Add a CSS `@keyframes spin` animation to the second layer in the `.stApp::before` background:
```css
.stApp::before {
  background-image:
    radial-gradient(circle, rgba(56,189,248,.045) 1px, transparent 1.2px),
    radial-gradient(circle, rgba(56,189,248,.025) 1px, transparent 1.2px);
  background-size: 28px 28px;
  background-position: 0 0, 14px 14px;
  animation: moire-spin 240s linear infinite;
}
@keyframes moire-spin { from { background-position: 0 0, 14px 14px; } to { background-position: 28px 28px, 42px 42px; } }
```

c. **Widen letter-spacing on headings and status-bar labels** (moodboard uses 0.04–0.08em tracking):
```css
h1,h2,h3,h4,h5,h6 { letter-spacing: -0.03em; }
.ide-status-bar { letter-spacing: 0.06em; }
```

d. **Glassmorphic cards.** Add `backdrop-filter: blur(8px)` and a semi-transparent background to `.blueprint-grid`, `.card`, and `.ide-console` for a light frosted-glass feel against the dark bg:
```css
.blueprint-grid { background: rgba(17, 27, 43, 0.75); backdrop-filter: blur(8px); }
.card { background: rgba(30, 41, 59, 0.85); backdrop-filter: blur(6px); }
.ide-console { background: rgba(17, 27, 43, 0.85); backdrop-filter: blur(6px); }
```

e. **Add a subtle pointer-trail effect.** The moodboard HTML renders a `<canvas>` pointer trail. In Streamlit, this can be approximated by injecting a tiny inline HTML/JS component at the end of `inject_theme()` that draws fading dots following the cursor. Keep it minimal (low opacity, few dots) so it doesn't distract from the canvas graph.

f. **Refine the hero/front page.** The front page (`render_front_page`) currently just renders provider status + title + template chips + two form columns. The moodboard's `index.html` has a split-screen hero with ASCII art and a subtitle. Consider adding the rotating ASCII sphere (`ui/bitmap_animation.py`) to the front page hero area for visual match, and a centered subtitle below the title.

### `ui/components.py` — Front-page polish (minimal)

a. **Wire `render_template_chips()` result into the flow.** Currently template chips set `project_idea` but the user still has to fill parent folder + workspace name and click Plan & Code. Add a default workspace name when a template is clicked (e.g., slugify the template title), and set `st.session_state["quick_build"] = True` so the template → Quick Build flow is one click.

b. **Show provider status on onboarding.** (Addresses BUG 4.) Add `render_provider_status(...)` at the top of `render_onboarding`.

c. **Add a "Run output" auto-display.** After Quick Build auto-generates and runs, display the result as a success toast and scroll-focus the console.

### `index.html` — Keep as-is

The static landing page already matches the moodboard well (electric-blue bg, white text, JetBrains Mono, ASCII art, grid bg, status bar). No changes needed unless the user wants to sync the font from Playfair → Cormorant in the `<style>` block (line 43-46 of index.html uses `Inter` and `JetBrains Mono` — consider adding `Cormorant Garamond` for `h1`).

---

## 5. VERIFICATION CHECKLIST

After making changes, verify:

1. `python3 -m pytest test_app.py -v` — all 14 tests pass (including the mocked `test_new_workspace_opens_the_live_workspace`).
2. `python3 -m py_compile app.py core/ai.py core/state.py services/executor.py services/files.py ui/components.py ui/theme.py utils/helpers.py` — compiles clean.
3. `python3 -c "import app"` — imports without error.
4. `python3 -m streamlit run app.py` — manually verify:
   - Front page shows template chips, recent projects, and provider status pill.
   - Clicking a template chip pre-fills the vision field.
   - "Plan & Code" → plan review moodboard → "Scaffold" or "Quick Build" both work.
   - **Quick Build scaffolds AND auto-generates the first file AND auto-runs it** (BUG 2 + BUG 9 fixed).
   - In the workspace, the AI chat input accepts text (press Enter → message sent) — BUG 1 fixed.
   - "Feed moodboard into architect" sends the notes to the AI assistant panel — BUG 3 fixed.
   - Onboarding screen shows provider status — BUG 4 fixed.
   - Headings use Cormorant Garamond serif; moiré grid animates subtly; cards have frosted-glass effect — UI polish applied.
5. Provider toggle correctly switches between Ollama / Nebius / Groq / OpenRouter — AI assistant uses the selected provider's URL and key on every render (no stale config).

---

## 6. EXECUTION ORDER (recommended)

This is the order in which fixes should be applied, because later steps depend on earlier ones:

| Step | Bug | File | Why first |
|---|---|---|---|
| 1 | BUG 1 (submit_mode) | `app.py:391` | Unblocks the entire AI chat — nothing downstream works without it |
| 2 | BUG 2 (quick_build flag) | `app.py:501-506` | Restores the Quick Build → auto-generate path |
| 3 | BUG 9 (auto-run) | `app.py:529-533` | Completes the "idea → running code" loop |
| 4 | BUG 3 (feed moodboard) | `ui/components.py:451` | Makes research notes actually reach the AI |
| 5 | BUG 4 (onboarding status) | `app.py:600` | Gives the user feedback before they spend time planning |
| 6 | BUG 7 (test mock) | `test_app.py:110` | Makes the test suite green again |
| 7 | BUG 5 (dead code) | `ui/components.py`, `app.py:188` | Cleanup — remove or wire `render_splash`, `render_ideas_panel`, `available_models` |
| 8 | BUG 6 (provider_override_select) | `app.py:645` | One-line removal of dead state |
| 9 | BUG 8 (nul artifact) | repo root | `del nul` from cmd.exe |
| 10 | UI polish | `ui/theme.py`, `ui/components.py` | Visual refinements — safe to do last, purely cosmetic |
