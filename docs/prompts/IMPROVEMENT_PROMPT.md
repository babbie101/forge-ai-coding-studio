# Live Codebase Canvas - Improvement Prompt

## Overview of the Codebase

The Live Codebase Canvas is a Streamlit application that provides an AI-powered development environment with:

**Architecture:**
- `app.py` - Main application with multi-stage workflow (home → onboarding → workspace)
- `core/ai.py` - AI provider abstractions (Ollama, Nebius, Groq, OpenRouter) with chat, architecture, roadmap generation
- `core/state.py` - Session state management with DEFAULTS
- `services/files.py` - Tree scanning, preview building, context export
- `services/executor.py` - Python code execution, preview type detection
- `ui/theme.py` - Ember dark-mode theme with ASCII background
- `ui/components.py` - UI components for moodboard, roadmap, ghost-writer, live output

**Key Features:**
- Multi-provider AI support (local Ollama, cloud providers)
- Visual file tree navigation (streamlit-flow)
- Architecture planning with AI-generated blueprints
- Development roadmap generation
- Auto-apply code generation
- Live Python execution preview
- Moodboard/research card system

---

## Issues Identified

### 1. Workflow & Usability Issues

**Problem:** When a user provides an idea, the roadmap should be the FIRST thing they see, but currently the moodboard/research notes appear before the roadmap, creating a confusing hierarchy.

**Current Flow (Problematic):**
1. User enters idea
2. AI generates architecture plan
3. Moodboard/Research notes shown
4. Roadmap shown AFTER (buried in the UI)

**Expected Flow:**
1. User enters idea
2. AI generates architecture plan + roadmap
3. **ROADMAP is displayed FIRST** (primary focus)
4. File structure shown
5. Development begins

### 2. Missing Roadmap Visibility

The roadmap is only shown in `render_onboarding_hub()` but gets buried in sidebar tabs in `render_workspace_main()`. Users don't see their concrete step-by-step path prominently.

### 3. Auto-Apply Confusion

Auto-apply is enabled by default (`"auto_apply": True` in DEFAULTS). New users may be surprised when code files are automatically written without explicit confirmation.

### 4. Progress Indication

Some AI operations (architecture planning, roadmap generation) have spinners but could benefit from progress messages.

### 5. Error Messages

Path validation errors are technical (e.g., "Use a simple workspace name without path separators"). Could be more helpful with examples.

---

## Improvement Prompt

```
You are an expert software engineer helping improve the Live Codebase Canvas application. A user has just provided an idea for their project. Your job is to generate the architecture plan and development roadmap.

## IMPORTANT: HOW USERS WILL INTERACT WITH YOU

When users tell you their idea, the FIRST thing they should see is:
1. A clear ROADMAP showing their step-by-step development journey
2. Then the architecture blueprint
3. Then we can discuss or modify as needed

## THE WORKFLOW YOU SHOULD ESTABLISH

1. **First Priority - Show Roadmap**: Generate and display the development roadmap prominently at the top
2. **Second - Architecture**: Show the file/folder structure
3. **Third - Discussion**: Let user review/edit before scaffolding

## OUTPUT FORMAT

Please provide your response in this structure:

### Step 1: Development Roadmap (Show FIRST)
List 5-8 concrete, actionable steps the user should follow:
- Each step should be a single implementable task
- Include the specific file(s) to work on
- Brief description of what to implement

### Step 2: Architecture Plan
Show the folder structure and file plan:
- Folders to create
- Files with brief descriptions

### Step 3: Quick Start (if ready to scaffold)
Offer to scaffold the project structure immediately

---

## VISUAL DESIGN GUIDELINES

The app should look professional and IDE-like:

**Theme:**
- Dark charcoal background (#0a0a0b)
- JetBrains Mono for code, Inter for UI
- Electric blue (#3b82f6) and green (#22c55e) accents
- No glassmorphism - solid dark surfaces
- 14px border radius on cards, 8px on buttons

**Layout:**
- 3-pane layout: Map (left) | Forge (center) | Window (right)
- Status bar at bottom showing context
- Clean sidebar navigation
- Visual file tree with color-coded nodes (blue=scaffolded, green=written, grey=planned)

---

## SPECIFIC IMPROVEMENTS TO MAKE

### 1. Fix render_moodboard() in ui/components.py
Move roadmap rendering to the TOP, before any research cards:
- Show "Development Roadmap" as the primary section
- Display "Architecture Blueprint" AFTER
- Research cards/moodboard come at the END (optional reference)

### 2. Improve Roadmap Visibility
In render_workspace_main(), ensure roadmap is visible in:
- Main canvas area (not just sidebar)
- Show completed step indicators
- "What's Next?" coach button more prominent

### 3. Auto-Apply Default
Change `"auto_apply": True` to `"auto_apply": False` in core/state.py DEFAULTS
Add clearer UI indicator when auto-apply is active

### 4. Enhanced Error Messages
In app.py render_onboarding(), improve path validation error messages:
- Instead of "Use a simple workspace name without path separators"
- Show: "Workspace name example: my-app (letters, numbers, hyphens only)"

### 5. Progress Messages
Add descriptive messages during long-running AI operations:
- "Planning your architecture..." → "Generating development roadmap..."
- Use st.progress() or st.info() for multi-step processes

### 6. Focus Mode Enhancement
Add a prominent "Focus Mode" toggle that:
- Hides the map sidebar
- Maximizes the Forge (coding) and Window (preview)
- Shows a clear "Exit Focus Mode" button

### 7. Roadmap-First Flow
When `create_from_idea` is triggered:
- Show roadmap in a prominent banner at the top
- Make "Scaffold Project" the primary call-to-action
- Add "View Full Plan" button to expand architecture details

### 8. Visual Hierarchy Improvements
- Use consistent spacing (12px gaps between sections)
- Ensure roadmap cards have clear visual separation
- Add subtle hover effects on interactive elements
- Use status dots (blue/green/purple/grey) consistently for node states

---

## FILES TO MODIFY

1. `ui/components.py` - render_moodboard(), render_roadmap(), render_workspace_main()
2. `core/state.py` - DEFAULTS (change auto_apply default)
3. `app.py` - render_onboarding(), better error messages, improved flow
4. `ui/theme.py` - minor CSS tweaks if needed

---

## IMPLEMENTATION CHECKLIST

- [ ] Move roadmap to top of render_moodboard()
- [ ] Change auto_apply default to False
- [ ] Improve error messages with examples
- [ ] Add "Focus Mode" toggle in main toolbar
- [ ] Make "What's Next?" button more prominent in sidebar
- [ ] Add visual progress indicators during AI planning
- [ ] Test the onboarding flow end-to-end
- [ ] Verify theme consistency across all components
```

## Summary of Issues Found

1. **Workflow Issue:** When users provide an idea, the roadmap is buried after moodboard/research instead of being shown first as the primary planning artifact.

2. **Visibility Issue:** Roadmap is only accessible in sidebar tabs, not prominently displayed in main canvas during development.

3. **Auto-Apply Confusion:** Defaulting to auto-apply can surprise new users who don't expect code to be written automatically.

4. **Error Messaging:** Validation errors are technical; could show helpful examples.

5. **Visual Hierarchy:** Research/moodboard cards currently appear before the roadmap they should support.

6. **Missing Focus Mode:** While technically implemented, it's not prominently featured in the UI for distraction-free coding.

**What Changed:** Created `IMPROVEMENT_PROMPT.md` with detailed analysis, identified issues, and a comprehensive improvement prompt that can be used to guide AI-generated responses in the correct order (roadmap first, then architecture, then discussion/code generation).