# Project Roadmap: Live Codebase Canvas

## Vision
A local developer workspace for planning, scaffolding, and evolving a codebase through a visual node graph and optional coding support.

## 🛠 Current State
- **Architecture Planning:** AI generates a JSON project structure and roadmap.
- **Scaffolding:** Automatically creates folders and files on disk based on the plan.
- **Live Visualization:** Codebase is rendered as an interactive node graph using `streamlit-flow`.
- **AI Partner:** Chat interface that can apply patches (`SEARCH/REPLACE`) and create new files.
- **Code Execution:** Ability to run Python files and view output in a simplified console.
- **Context Management:** Ability to export the codebase state to `CONTEXT.md` for LLM ingestion.

## 🗺 Future Improvements

### Phase 1: Core Stability & DX (Immediate)
- [ ] **Robust Patching:** Implement a more advanced diff/patch system to handle indentation and whitespace more flexibly.
- [ ] **Integrated Terminal:** Replace the basic `subprocess.run` preview with a more persistent terminal emulator or a better-formatted output window.
- [ ] **Improved Context Export:** Allow users to choose which files to include in `CONTEXT.md` and set character limits per file.
- [ ] **Error Recovery:** Better handling of file system permissions and API timeouts.

### Phase 2: Visual & Interactive Enhancements (Short-term)
- [ ] **Actual Moodboard:** Implement the research board with support for image uploads, URLs, and sticky notes.
- [ ] **Node Customization:** Allow users to move nodes, group them, or color-code them based on module roles.
- [ ] **File Diff View:** Show a side-by-side diff before the AI applies a patch to the codebase.
- [ ] **Enhanced Editor:** Integrate a more powerful code editor (e.g., Monaco via a Streamlit component) with syntax highlighting.

### Phase 3: Power Features (Long-term)
- [ ] **Git Integration:** Integrated `git init`, `commit`, and `push` workflows directly from the canvas.
- [ ] **Multi-AI Support:** Ability to switch AI providers per task (e.g., using a specialized model for architecture and another for implementation).
- [ ] **Real-time Collaboration:** Multi-user support to collaborate on the codebase canvas in real-time.
- [ ] **Automated Testing:** AI-generated test suites that run automatically upon file updates.

## 📉 Technical Debt
- **Path Handling:** Standardize on `pathlib` across all modules.
- **State Management:** Move away from excessive `st.session_state` usage toward a more structured state manager.
- **UI Consistency:** Refine the CSS theme for better accessibility and high-contrast options.
## Current implemented state

- The app now supports explicit existing-workspace opening and new-workspace planning.
- Architecture plans are reviewed visually before a user chooses to scaffold files.
- The live canvas includes node focus navigation, project metrics, file inspection, export, local preview, and explicit AI patch application.
- The next milestone is stronger project review: selectable context exports, clearer patch review, and a more capable code editor.

