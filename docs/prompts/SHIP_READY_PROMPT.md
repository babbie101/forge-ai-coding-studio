# AGENT PROMPT: Live Codebase Canvas — Final Pass to "Ship Ready"

> Context for the agent handling this task: You are working on **Live Codebase Canvas (LCC)**,
> a local-first Streamlit app for the **Nebius x NVIDIA Global Hackathon** (Best Apps & Agents track).
> The app lets users describe a project idea, AI-generates an architecture plan, scaffolds files
> on disk, then renders the codebase as an interactive node graph with an AI coding partner,
> live file editor, and Python runner.
>
> **Current state:** The app runs and all 14 tests pass. Most critical bugs from earlier prompt
> cycles (BUG 1-9 from the old AGENT_PROMPT.md) have ALREADY been fixed. This prompt covers the
> REMAINING work to make the codebase clean, fully demo-ready, and ship-quality for the hackathon.
> Verify each item against the current code before acting - do NOT re-do work that is already complete.
>
> Run from `C:\Users\saher\Documents\Hackathon\Codebase` with `python3 -m streamlit run app.py`.
> Note: `python` (3.14) and `python3` (3.11) differ; the venv/deps live under `python3`.

---

## Project Structure

```
app.py                      Main Streamlit app: routing, provider detection, canvas, AI assistant
core/ai.py                  AI provider configs, chat, architecture generation, patch extraction
core/state.py               Session-state defaults (SessionStateManager)
services/files.py           Tree scanning, file I/O, CONTEXT.md export, safe path wrapping
services/executor.py        Python subprocess runner (30s timeout)
ui/components.py            All UI rendering: front page, moodboard, node editor, status bar, etc.
ui/theme.py                 CSS theme injection (cyber-classical IDE aesthetic)
ui/bitmap_animation.py      Rotating 3D ASCII sphere widget (HTML/JS iframe) - built, NOT wired in
utils/helpers.py            Path safety, native folder-picker dialog
test_app.py                 14 integration tests (all pass, ~90s runtime)
index.html                  Static landing page (separate from Streamlit app)
.env                        Redacted secrets (keys shown as ***) - real keys needed for demo
.env.example                Template for .env configuration
```

---

## What's Already Fixed (DO NOT RE-DO)

These bugs from earlier prompt cycles are already resolved in the current code.
Verify they are still correct before touching - if you find regressions, fix them,
but don't refactor what works.

1. **Chat input submission** - `submit_mode="disable"` removed (app.py:391 now just `disabled=not api_key`). Pressing Enter submits the chat. Verified in current code.
2. **Quick Build flag consumption** - `quick_build_requested = st.session_state.pop("quick_build", False)` stored in a local var before the `or` check (app.py:515). Flag is not double-popped.
3. **Auto-run after Quick Build** - Quick Build sets `st.session_state["auto_run_file"]` + `["selected_id"]` (app.py:540-542); `_render_output_panel` detects `auto_run_file` and auto-runs on post-rerun render (app.py:456-459).
4. **Moodboard feed -> messages** - "Feed moodboard into architect" appends to `messages` (components.py:451), not the dead `whiteboard_messages`.
5. **Provider status on onboarding** - `render_provider_status()` called in both `render_front_page` (components.py:190) and `render_onboarding` (app.py:624).
6. **Ollama timeout** - 1.5s timeout in `ollama_is_reachable()` (components.py:126).
7. **for/else provider fallthrough** - `render_provider_toggle()` uses sequential if-checks, not for/else (components.py:151-162).
8. **Wired components** - `render_moodboard` (app.py:557), `show_node_editor` (app.py:612), `render_template_chips` (components.py:193), `render_recent_projects` (components.py:194), `render_status_bar` (app.py:615), `render_canvas_navigator` (app.py:579) all called.
9. **Test mocking** - `test_new_workspace_opens_the_live_workspace` patches `generate_architecture` (test_app.py:122-124). All 14 tests pass.
10. **Theme** - Cormorant Garamond + Playfair Display imported, deep blue-black bg (#0a0f1a), white text, animated moiré grid (moire-spin 240s), crosshair cursor, glassmorphic cards (backdrop-filter blur on .blueprint-grid, .card, .ide-console).
11. **No stale provider_override_select** - the dead `provider_override_select` key from the old BUG 6 is NOT present in the current app.py.
12. **Module-level provider constants gone** - No `_PROVIDER_CFG`, `PROVIDER`, `AI_MODEL`, `BASE_URL`, `AI_API_KEY`, `MODEL_CHOICES` at module level. All resolved via `_active_provider()` at call time.

---

## Task Categories

The remaining work falls into 6 categories. Complete them in the order listed - later
items depend on earlier ones being stable.

---

### Category A: Dead Code & Repo Hygiene

**A1. Remove dead functions from `ui/components.py`**

- `render_splash()` (components.py:272-275) - defined but never called. The routing table in
  app.py:728-733 maps `"splash"` to `front_runner` (i.e. `render_front_page`). `render_splash`
  just sets `app_stage="home"` and reruns - a no-op redirect. Remove it.

- `render_ideas_panel()` (components.py:493-535) - defined but never imported or called anywhere.
  It has a "Feed ideas into architect" button that returns a summary string, but `render_moodboard`
  (components.py:445) already has its own "Feed moodboard into architect" button that appends to `messages`.
  So removing `render_ideas_panel` does NOT lose functionality.

- **Unused `available_models` parameter in `render_front_page`** - `render_front_page(available_models, ...)`
  at components.py:188 accepts `available_models` as its first parameter but never references it in the
  body. Note: `render_onboarding_hub` (components.py:277) ALSO takes `available_models` as its first
  parameter and DOES use it (components.py:292: `labels = list(available_models)`). These are two
  separate functions. Only remove the parameter from `render_front_page` and its call site in `main()`
  (app.py:724-727); leave `render_onboarding_hub`'s parameter intact.

- After removal: `grep -rn "render_splash\|render_ideas_panel" app.py ui/` returns no matches.

**A2. Remove the `nul` file from repo root**

- A 0-byte file named `nul` exists at the repo root. On Windows, `nul` is a reserved device name
  and cannot be opened/deleted normally via Python or git-bash. Remove it at the OS level:
  ```cmd
  del nul
  ```
  Run from cmd.exe in the project root. Verify it's gone afterward.

**A3. Remove stray scratch files from repo root**

- `test` (487 bytes) - a "Hackathon Test Node" markdown file, not a Python test. Delete it.
- `test_output2.py` (49 bytes) - a 2-line `print("second file")` artifact. Delete it.
- `SKILL.md.txt` (0 bytes) - empty placeholder. Delete it.
- `hackathon` (487 bytes) - same content as the `test` file. Delete it.

**A4. Archive or delete obsolete prompt artifacts**

- `HACKATHON_PROMPT.md` (17KB) - prompt from a previous agent cycle documenting bugs already fixed.
- `AGENT_PROMPT.md` (24KB) - same; its "Completed" checklist lists fixes that are already applied.
- Both reference old line numbers and code shapes that no longer match.
- Decision: Create a `docs/` directory and move both files there with `-v1` suffixes
  (e.g. `docs/AGENT_PROMPT-v1.md`, `docs/HACKATHON_PROMPT-v1.md`), OR delete them outright.
  If keeping as a record of the development process, move to `docs/`. If deleting, confirm
  no code references them (verified: they are standalone docs, no imports).

**A5. Clean up stale generated docs and update .gitignore**

- `CONTEXT.md` - auto-generated app output (Export CONTEXT.md button). Currently stale (4 Oct 2026).
  Add `CONTEXT.md` and `PLAN.md.txt` to `.gitignore` so they are never committed.
- `PLAN.md.txt` (4KB) - stale master plan referencing old models (Qwen 3.8 27B, GPT-OSS 120B)
  and old phases. Delete it. README.md and this SHIP_READY_PROMPT.md cover the essentials.

---

### Category B: Stale Documentation

**B1. Rewrite `README.md`** (currently 54 lines, describes OLD 3-stage flow)

Current README says:
- "splash -> onboarding hub -> workspace" (old 3-stage; current app is 2-stage: "home" + "workspace"
  with onboarding embedded in `render_onboarding()`)
- "Qwen 3.8 27B" model references (wrong - that was from PLAN.md.txt; README doesn't actually
  mention specific models, but it is outdated on the flow description)

Rewrite README to accurately describe:
- The 2-stage UI: home/landing page (template chips, recent projects, provider toggle)
  -> workspace (canvas, AI assistant, file editor, console)
- Quick Build flow: describe idea -> AI generates plan -> scaffold + auto-generate first file -> auto-run
- The Plan & Code path: describe idea -> AI generates plan -> review moodboard -> scaffold -> workspace
- The provider toggle (Ollama/Nebius/Groq/OpenRouter) and how it is detected
- How to create `.env` with a real API key (reference `.env.example`)
- The test command: `python3 -m pytest test_app.py -v`
- The actual file layout (core/, services/, ui/, utils/)

**B2. Delete `PROJECT_CONTEXT.md`** (currently 97 lines, describes OLD state)

It references:
- Old 3-stage UI with splash screen
- Old model picker: `Qwen 3.8 27B`, `GPT-OSS 120B` (don't exist in current `_ai_providers`)
- `generate_architecture(topic, model)` with 2 args (current signature: `(topic, model, base_url, api_key)`)
- `render_workspace()` (current: `render_workspace_main()`)
- `whiteboard_messages` session key (dead - replaced by `messages`)
- Session-state keys that don't exist: `pending_new_file`, `confirm_delete`
- Notes that `show_ai`, `apply_status` exist as session-state keys (they do NOT in current state.py)

Recommendation: DELETE `PROJECT_CONTEXT.md`. This SHIP_READY_PROMPT.md is the authoritative context.

**B3. Update `.env.example`** (already mostly accurate, just verify/polish)

- Current `.env.example` has GROQ_API_KEY, OPENROUTER_API_KEY, NEBIUS_API_KEY, OLLAMA_API_KEY,
  OLLAMA_BASE_URL. This matches `_resolve_provider()` expectations.
- Add comments clarifying:
  - Nebius key must start with `nb-`
  - OpenRouter key starts with `sk-or-v1-`
  - Ollama can be empty; set `OLLAMA_BASE_URL` for a remote gateway, otherwise native local
- No structural changes needed, just polish comments.

---

### Category C: UI / Moodboard Compliance (Close the "Last 20%")

The theme (`ui/theme.py`) already captures the cyber-classical aesthetic (~80% match).
The `index.html` landing page also matches well. Close the remaining gaps.

**C1. Render the rotating ASCII sphere on the front page**

`ui/bitmap_animation.py` has `render_rotating_ascii_sphere()` and `render_bitmap_animation()` -
fully built, never called anywhere. The front page (`render_front_page` in `components.py:188`)
shows provider status, title, template chips, and recent projects, but no visual hero element.

Add the ASCII sphere to the front page:
- Import `render_bitmap_animation` (or `render_rotating_ascii_sphere`) from `ui.bitmap_animation`
  in `components.py`
- Call it in `render_front_page()` - place it between the title/caption and the template chips
- Keep it subtle (low opacity) so it enhances rather than overwhelms

**C2. Add pointer-trail cursor effect to the Streamlit app**

The moodboard HTML (`index.html`) has a pointer-trail effect and the old AGENT_PROMPT.md v1
mentioned it (section 4e). The current `ui/theme.py` has a crosshair cursor but no trail.

Implement a minimal pointer-trail in `inject_theme()` (ui/theme.py):
- Inject a small `<script>` at the end of the `st.html()` block (after the `</style>`)
- Capture `mousemove` events on the document body
- Draw 8-10 fading dots following the cursor using single-pixel `div` elements
- Use `#3b82f6` (electric blue) at low opacity (0.15-0.25)
- Respect `prefers-reduced-motion` (disable entirely if set)
- Keep DOM elements minimal - reuse a single container `div` and recycle dot elements
- The existing `cursor: crosshair` on `.stApp` should stay

**C3. Update `index.html` font stack to include Cormorant Garamond**

The static landing page uses `Inter` (UI) + `JetBrains Mono` (code) but NOT `Cormorant Garamond`
or `Playfair Display`. The Streamlit app theme uses Cormorant Garamond for headings.

Sync `index.html`:
- Add `Cormorant Garamond` to the Google Fonts `link` import (line 10)
- Apply it to `h1` and headings (currently uses `Inter` - see the `h1` CSS rule at line 33)
- Keep `JetBrains Mono` for code/monospace elements
- Minimal change - just font sync, no layout changes

---

### Category D: Test Coverage Gaps

The 14 existing tests all pass but only cover infrastructure (path safety, tree scanning,
JSON extraction, provider detection, subprocess execution). No tests cover user-facing workflows.
Add tests that mock all AI calls (`generate_architecture`, `run_ai_chat`, `generate_file_content`)
so tests don't hit real APIs or depend on network.

**D1. `test_quick_build_scaffolds_and_sets_autorun`**

Mock `generate_architecture` to return a simple plan. Drive AppTest:
1. Start at "home" stage
2. Set `new_parent_input`, `new_workspace_name`, `project_idea_input`
3. Click `quick_build_from_home` button
4. Run, then assert:
   - `app_stage == "workspace"`
   - `plan_scaffolded == True`
   - `architecture_plan == None`
   - First file from plan created on disk
   - `auto_run_file` session key matches generated file path (or `selected_id` is set)

**D2. `test_chat_input_sends_message`**

Mock provider config so `api_key` is non-empty. In workspace mode with temp dir:
1. Set `st.session_state["provider_override"] = "groq"` (or mock `_get_provider_config` to return a fake config with a real-looking key)
2. Type into chat input and submit
3. Mock `run_ai_chat` to return a canned response with a code block
4. Assert a "user" message appears in `messages`
5. Assert an "assistant" message appears with the mocked content
6. Assert the "Save" button for the code block appears

**D3. `test_moodboard_feed_appends_to_messages`**

1. Set up workspace with `architecture_plan` present, `plan_scaffolded = False`
2. Click the "Feed moodboard into architect" button (key is in `render_moodboard` at components.py:445)
3. Assert `messages` list grew by one entry with role "user"

**D4. `test_node_editor_save_writes_file`**

1. Create a temp file in a workspace dir
2. Set `selected_id` to that file, navigate to workspace
3. Edit the text_area value and click "Save changes"
4. Assert file on disk contains the new content

**D5. `test_export_context_md_creates_file`**

1. Set up workspace with a known file tree
2. Click "Export CONTEXT.md" button (key: `export_context_btn`, app.py:580)
3. Assert `CONTEXT.md` exists at workspace root and contains file-tree + file-content sections

**D6. `test_provider_toggle_changes_provider`**

1. In workspace mode
2. Click a provider button (e.g. the one with key `provider_ollama` or `provider_groq`)
3. Assert `st.session_state["provider_override"]` matches the selected provider key

**D7. Speed up the test suite**

Current runtime ~90s. The bottleneck is `AppTest.from_file("app.py").run(timeout=25)` called
multiple times per test. In tests that set multiple values, batch `.set_value()` calls and call
`.run()` once instead of after every interaction. Target: reduce total runtime below 75s.

---

### Category E: Hackathon Demo Readiness

**E1. Verify end-to-end "Idea -> Running Code" demo flow**

This is the headline demo for judges. Walk through manually with a REAL API key
(Nebius `nb-...` or Groq `gsk_...`):

1. Front page: fill parent folder (temp dir), workspace name, project idea
2. Click "Quick Build" (the lightning bolt button)
3. AI generates architecture plan (real call to `generate_architecture`)
4. App scaffolds folders + files on disk
5. App auto-generates first file (real call to `generate_file_content`)
6. App auto-selects + auto-runs the file in the output panel
7. Console panel shows output (or errors if the generated code has bugs - which is a normal AI result, not an app bug)
8. Status bar shows correct model label and "Watchdog: N events"

Document any failure points. The `.env` currently has redacted `***` values - a real key is needed.
The Nebius endpoint (`https://api.studio.nebius.ai/v1/`) and Groq endpoint
(`https://api.groq.com/openai/v1/`) are both configured in `core/ai.py:25-66`.

**E2. Verify the "Plan & Code" (non-Quick-Build) path works**

1. Front page: fill parent folder, workspace name, project idea
2. Click "Plan & Code" button
3. Onboarding screen generates plan
4. Moodboard renders review cards (folders, files, roadmap, dependencies, run_checklist)
5. Click "Scaffold Project" (not Quick Build)
6. App scaffolds files, falls through to workspace with empty canvas
7. User can then click a file node to open the editor, or chat with the AI assistant

Verify this path doesn't break and the moodboard renders correctly with the plan data.

---

### Category F: Minor Code Quality

**F1. `generate_architecture` system prompt - clarify `animations` field**

The system prompt (ai.py:182-193) asks for JSON with fields including `"animations"`, but
validation (ai.py:211) treats `animations` as optional:
```python
required = {"summary", "folders", "files", "roadmap", "dependencies", "run_checklist"}  # "animations" is optional
```
This is fine functionally, but the system prompt should explicitly note `animations` is optional,
or the validation set should include it with a fallback. Minor clarity fix.

**F2. `run_ai_chat` context text is unbounded**

At app.py:398-402, when a file node is selected, its full text is read and passed as
`context_text` to the AI. For large files this could exceed token limits. Add a truncation
safety: if the file exceeds 2000 lines, truncate to the first 1000 lines and append
`"... (file truncated: showing first 1000 of {n} lines)"`.

**F3. Verify `render_onboarding_hub` signature matches its call site**

Check that the `render_onboarding_hub` function signature in `components.py:277` matches how
it is called in `app.py:646`. Current call:
```python
request = render_onboarding_hub(
    active_models, active_provider_config["api_key"], active_provider_config["label"],
    active_provider_config["base_url"], on_browse_existing, on_browse_new,
)
```
And the function signature is:
```python
def render_onboarding_hub(available_models, api_key, provider_label, base_url, on_browse_existing, on_browse_new):
```
These match - verify after any refactoring.

---

## Execution Order

Complete tasks in this order. Each tier should pass verification before moving on.

| Tier | Category | Tasks |
|---|---|---|
| 1 | A - Hygiene | A1, A2, A3, A4, A5 (dead code, file cleanup, gitignore) |
| 2 | B - Docs | B1, B2, B3 (README, PROJECT_CONTEXT, .env.example) |
| 3 | C - UI | C1, C2, C3 (ASCII sphere, pointer trail, index.html font) |
| 4 | D - Tests | D1-D7 (new tests, speed up suite) |
| 5 | E - Demo | E1, E2 (end-to-end demo, Plan&Code path) |
| 6 | F - Polish | F1-F3 (minor code quality) |

---

## Verification Checklist

After ALL tasks are complete:

1. **Tests:** `python3 -m pytest test_app.py -v` - all tests pass (14 original + new). Runtime under 75s.
2. **Compile:** `python3 -m py_compile app.py core/ai.py core/state.py services/executor.py services/files.py ui/components.py ui/theme.py utils/helpers.py` - clean.
3. **Import:** `python3 -c "import app"` - no error. (py_compile does not resolve imports; this catches missing imports, circular references.)
4. **App starts:** `python3 -m streamlit run app.py` - front page renders without errors. (AI calls need a real key; UI should render regardless.)
5. **Repo clean:** No stray files. `nul`, `test`, `test_output2.py`, `hackathon`, `SKILL.md.txt` gone. `.gitignore` excludes `CONTEXT.md` and `PLAN.md.txt`. Obsolete prompts moved to `docs/` or deleted.
6. **Dead code gone:** `grep -rn "render_splash\|render_ideas_panel" app.py ui/` - no matches.
7. **UI renders:** Front page shows ASCII sphere, pointer-trail is active, index.html has Cormorant Garamond.
8. **No stale refs:** `grep -rn "whiteboard_messages\|pending_new_file\|confirm_delete\|render_workspace()" app.py ui/ core/ services/ utils/` - no matches in source files.

---

## Acceptance Criteria - "Good Enough" = Ship Ready

The app is ship-ready for the hackathon when ALL of these are true:

- [ ] All tests pass (14 original + new workflow tests)
- [ ] App starts and renders the front page without errors
- [ ] Quick Build flow works end-to-end (plan -> scaffold -> generate -> auto-run) with a real API key
- [ ] "Plan & Code" path works end-to-end (plan -> review moodboard -> scaffold -> workspace)
- [ ] Chat input accepts and sends messages (Enter submits)
- [ ] Moodboard "Feed to architect" appends to the AI chat history
- [ ] Node editor saves edits to disk
- [ ] "Export CONTEXT.md" creates the file on disk
- [ ] Status bar renders at the bottom of the workspace
- [ ] Provider toggle switches providers; AI assistant uses the selected provider (no stale config)
- [ ] No dead code or stray files in the repo root
- [ ] README.md accurately reflects the current 2-stage app
- [ ] Theme matches the moodboard (Cormorant Garamond, animated moiré grid, crosshair, ASCII sphere, pointer trail)
- [ ] `.env.example` is accurate and documented
- [ ] No reference to stale/obsolete bugs or line numbers in committed source files

---

## Style Guide

- Match existing conventions: 4-space indentation, `\"\"\"triple-quote\"\"\"` docstrings, `snake_case` functions, `from module import` style imports.
- Do NOT reformat files unrelated to your task - touch only what an item requires.
- Do NOT commit or push (no git repo initialized in this workspace; leave it alone).
- Do NOT print secrets or the real `.env` contents. The committed `.env` has redacted `***` values.
- When modifying `ui/theme.py`, keep all CSS in the single `st.html(\"\"\"...\"\"\")` call to match the existing format (the entire theme is one `st.html` call with everything on one line inside).
- When adding new test functions, append them to the end of `test_app.py` and use `AppTest.from_file("app.py")` with mocked AI calls.
- When removing functions from `components.py`, check that `app.py` imports don't reference them (use grep to verify no `ImportError` will result).
