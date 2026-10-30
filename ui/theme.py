import streamlit as st


def inject_theme():
    """Apply the Ember dark-mode SaaS dashboard design system with full-viewport
    interactive ASCII background support.

    Aesthetic: flat near-black background (#0a0a0b), white/light-gray text,
    Inter font everywhere, solid dark surfaces (#111111 / #1a1b1f),
    subtle slate borders (#334155), electric blue (#3b82f6) / green (#22c55e) accents,
    no glassmorphism (no backdrop-filter blur), default cursor with a subtle 6-dot trail.
    """
    st.html("""
    <style>
      @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500;600;700&display=swap');

      :root {
        --bg: #0a0a0b;
        --deep: #0a0a0b;
        --surface: #111111;
        --surface-2: #1a1b1f;
        --line: #334155;
        --border: #334155;
        --border-subtle: #1e293b;
        --text: #ffffff;
        --muted: #94a3b8;
        --muted-2: #64748b;
        --blue: #3b82f6;
        --cyan: #06b6d4;
        --green: #22c55e;
        --yellow: #eab308;
        --pink: #ec4899;
        --purple: #a855f7;
      }

      /* Global resets & typography: Inter everywhere, default cursor */
      html, body {
        background-color: #0a0a0b !important;
        color: var(--text) !important;
        font-family: 'Inter', system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif !important;
        cursor: default !important;
      }

      .stApp {
        background: transparent !important;
        color: var(--text) !important;
        font-family: 'Inter', system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif !important;
        cursor: default !important;
      }

      /* Full-viewport interactive ASCII background container */
      .ascii-full-bg {
        position: fixed !important;
        top: 0 !important;
        left: 0 !important;
        width: 100vw !important;
        height: 100vh !important;
        z-index: -1 !important;
        opacity: 0.45 !important;
        pointer-events: none !important;
        overflow: hidden !important;
      }

      /* Pin any iframe rendered for the ascii background to full viewport behind content */
      iframe {
        position: fixed !important;
        top: 0 !important;
        left: 0 !important;
        width: 100vw !important;
        height: 100vh !important;
        z-index: -1 !important;
        opacity: 0.45 !important;
        pointer-events: none !important;
        border: none !important;
        overflow: visible !important;
      }

      /* Streamlit element container holding the 0-height iframe should not push layout */
      [data-testid="stCustomComponentV1"] {
        position: fixed !important;
        top: 0 !important;
        left: 0 !important;
        width: 0 !important;
        height: 0 !important;
        margin: 0 !important;
        padding: 0 !important;
        overflow: visible !important;
        pointer-events: none !important;
        z-index: -1 !important;
      }

      /* Ensure the main app content sits above the background */
      [data-testid="stAppViewContainer"] {
        position: relative !important;
        z-index: 1 !important;
        background: transparent !important;
      }

      /* Ensure sidebar sits above the ASCII bg */
      [data-testid="stSidebar"] {
        position: relative !important;
        z-index: 2 !important;
        background-color: var(--surface) !important;
        border-right: 1px solid var(--line) !important;
      }
      [data-testid="stSidebar"] * {
        color: var(--text);
      }
      [data-testid="stSidebar"] .stCaption, [data-testid="stSidebar"] p {
        color: var(--muted);
      }

      /* Main block container above bg */
      [data-testid="stMainBlockContainer"] {
        position: relative !important;
        z-index: 1 !important;
        max-width: 1240px;
        padding-top: 1.5rem;
        padding-bottom: 3.5rem;
      }

      /* Make all Streamlit cards/containers sit above the bg */
      .stApp > div {
        position: relative !important;
        z-index: 1 !important;
      }

      /* Streamlit app chrome */
      [data-testid="stHeader"], [data-testid="stToolbar"] {
        background: transparent !important;
      }

      /* Headings */
      h1, h2, h3, h4, h5, h6 {
        color: var(--text) !important;
        font-family: 'Inter', system-ui, sans-serif !important;
        font-weight: 700 !important;
        letter-spacing: -0.02em !important;
      }

      p, span, label, div {
        font-family: 'Inter', system-ui, sans-serif;
      }

      /* Streamlit container cards: solid dark, 14px radius, #334155 border, no backdrop-filter */
      [data-testid="stVerticalBlockBorderWrapper"], .blueprint-grid, .card {
        background: var(--surface) !important;
        border: 1px solid var(--line) !important;
        border-radius: 14px !important;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15) !important;
      }

      /* Buttons (.stButton>button): 8px radius, default transparent bg + 1px border #334155 */
      .stButton > button {
        border-radius: 8px !important;
        border: 1px solid var(--line) !important;
        background: var(--surface-2) !important;
        color: var(--text) !important;
        font-family: 'Inter', sans-serif !important;
        font-size: 13px !important;
        font-weight: 500 !important;
        transition: all 140ms ease !important;
        padding: 0.45rem 0.85rem !important;
      }
      .stButton > button:hover {
        border-color: var(--blue) !important;
        background: #232730 !important;
        color: #ffffff !important;
        transform: translateY(-0.5px);
        box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.2) !important;
      }
      .stButton > button[kind="primary"] {
        background: var(--blue) !important;
        border-color: var(--blue) !important;
        color: #ffffff !important;
        font-weight: 600 !important;
      }
      .stButton > button[kind="primary"]:hover {
        background: #2563eb !important;
        border-color: #2563eb !important;
        box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.3) !important;
      }

      /* Inputs, Textareas, Selectboxes */
      input, textarea, [data-baseweb="select"] > div {
        background: var(--surface-2) !important;
        color: var(--text) !important;
        border: 1px solid var(--line) !important;
        border-radius: 8px !important;
        font-family: 'Inter', sans-serif !important;
      }
      input::placeholder, textarea::placeholder {
        color: var(--muted) !important;
        opacity: 0.8 !important;
      }
      input:focus, textarea:focus, .stButton > button:focus-visible, [data-baseweb="select"] > div:focus-within {
        outline: 2px solid rgba(59, 130, 246, 0.27) !important;
        outline-offset: 2px !important;
        border-color: var(--blue) !important;
        box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.2) !important;
      }

      /* Tabs */
      [data-testid="stTabs"] [data-baseweb="tab"] {
        color: var(--muted) !important;
        font-family: 'Inter', sans-serif !important;
        font-size: 13px !important;
        font-weight: 500 !important;
      }
      [data-testid="stTabs"] [aria-selected="true"] {
        color: var(--blue) !important;
        border-bottom-color: var(--blue) !important;
      }

      /* Code and pre tags: JetBrains Mono retained ONLY for code blocks and console output */
      [data-testid="stCodeBlock"], code, pre {
        font-family: 'JetBrains Mono', Consolas, monospace !important;
      }

      /* Card styles: solid dark #111111, border #334155, 12-14px radius, no glassmorphism */
      .card {
        background: var(--surface);
        border: 1px solid var(--line);
        border-radius: 12px;
        padding: 12px;
        margin: 6px 0;
        transition: transform 120ms ease, border-color 120ms ease;
      }
      .card:hover {
        border-color: var(--blue);
        transform: translateY(-1px);
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
      }

      /* Console card */
      .ide-console {
        background: var(--surface);
        color: #93c5fd;
        border: 1px solid var(--line);
        border-radius: 12px;
        padding: 1rem;
        white-space: pre-wrap;
        font-family: 'JetBrains Mono', monospace;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
      }

      /* Status bar at bottom */
      .ide-status-bar {
        position: fixed;
        bottom: 0;
        left: 0;
        right: 0;
        z-index: 50;
        height: 30px;
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 0 16px;
        background: var(--surface-2);
        border-top: 1px solid #1e293b;
        color: var(--muted);
        font: 11px 'JetBrains Mono', monospace;
        letter-spacing: 0.04em;
      }
      .ide-status-group { display: flex; align-items: center; }
      .ide-status-item { padding: 0 10px; border-right: 1px solid #1e293b; }
      .ide-status-item:last-child { border: 0; }
      .status-dot-live {
        display: inline-block;
        width: 7px;
        height: 7px;
        border-radius: 50%;
        background: var(--green);
        box-shadow: 0 0 0 2px rgba(34, 197, 94, 0.2);
        margin-right: 5px;
      }

      /* Status pills */
      .status-pill {
        display: inline-flex;
        align-items: center;
        gap: 0.4rem;
        padding: 0.35rem 0.7rem;
        border: 1px solid var(--line);
        border-radius: 8px;
        background: var(--surface-2);
        color: #ffffff !important;
        font: 500 12px 'Inter', sans-serif;
      }
      .pill-accent {
        border-color: rgba(34, 197, 94, 0.4);
        color: #86efac !important;
      }
      .connection-dot {
        width: 7px;
        height: 7px;
        border-radius: 50%;
        background: var(--green);
        box-shadow: 0 0 0 2px rgba(34, 197, 94, 0.2);
      }

      .recent-projects-header {
        font: 600 11px 'Inter', sans-serif;
        color: var(--muted);
        text-transform: uppercase;
        letter-spacing: 0.06em;
        margin-bottom: 8px;
      }

      /* Colored status dots */
      .status-dot {
        display: inline-block;
        width: 8px;
        height: 8px;
        border-radius: 50%;
        margin-right: 8px;
      }
      .status-dot.yellow { background: var(--yellow); }
      .status-dot.green { background: var(--green); }
      .status-dot.blue { background: var(--blue); }
      .status-dot.pink { background: var(--pink); }
      .status-dot.purple { background: var(--purple); }

      /* Diff viewer */
      .diff-container {
        border: 1px solid var(--line);
        border-radius: 10px;
        overflow: hidden;
        margin: 1rem 0;
        font: 12px/1.55 'JetBrains Mono', monospace;
        background: var(--surface);
      }
      .diff-header {
        padding: 0.65rem 0.85rem;
        background: var(--surface-2);
        color: var(--text);
        border-bottom: 1px solid var(--line);
      }
      .diff-columns { display: grid; grid-template-columns: 1fr 1fr; }
      .diff-columns section {
        min-width: 0;
        max-height: 340px;
        padding: 0.7rem;
        border-right: 1px solid var(--line);
        overflow: auto;
      }
      .diff-columns section:last-child { border-right: 0; }
      .diff-label {
        display: block;
        color: var(--muted);
        font-size: 10px;
        font-weight: 600;
        text-transform: uppercase;
        margin-bottom: 0.5rem;
      }
      .diff-line { white-space: pre; padding: 2px 6px; }
      .diff-line.removed { background: rgba(239, 68, 68, 0.15); color: #fca5a5; }
      .diff-line.added { background: rgba(34, 197, 94, 0.15); color: #86efac; }

      /* Studio 3-Pane Layout & Forge / Window Aesthetics */
      .studio-container {
        display: flex;
        gap: 12px;
        width: 100%;
        margin-top: 4px;
        margin-bottom: 12px;
      }
      
      .studio-pane {
        background: var(--surface);
        border: 1px solid var(--border);
        border-radius: 12px;
        padding: 12px;
        box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.05), 0 8px 24px rgba(0, 0, 0, 0.35);
        transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
        position: relative;
      }

      .studio-pane:hover {
        border-color: #475569;
      }

      .studio-pane-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding-bottom: 8px;
        margin-bottom: 10px;
        border-bottom: 1px solid var(--border-subtle);
      }

      .studio-pane-title {
        font-size: 11px;
        font-weight: 700;
        letter-spacing: 0.06em;
        text-transform: uppercase;
        color: var(--muted);
        display: flex;
        align-items: center;
        gap: 6px;
      }

      /* Ghost-Writer Code Surface (Forge) */
      .forge-editor {
        font-family: 'JetBrains Mono', monospace !important;
        font-size: 12.5px;
        line-height: 1.6;
        background: #0d1117 !important;
        border: 1px solid #1e293b !important;
        border-radius: 8px;
        color: #e2e8f0;
        position: relative;
        overflow-x: auto;
      }

      .ghost-cursor {
        display: inline-block;
        width: 8px;
        height: 15px;
        background: #3b82f6;
        vertical-align: text-bottom;
        margin-left: 2px;
        box-shadow: 0 0 8px #3b82f6;
        animation: ghost-blink 0.9s infinite cubic-bezier(0.4, 0, 0.6, 1);
      }

      @keyframes ghost-blink {
        0%, 100% { opacity: 1; }
        50% { opacity: 0; }
      }

      .active-typing-line {
        background: linear-gradient(90deg, rgba(59, 130, 246, 0.15) 0%, rgba(59, 130, 246, 0) 100%);
        border-left: 2px solid #3b82f6;
        box-shadow: inset 0 0 12px rgba(59, 130, 246, 0.08);
      }

      /* Live Output Window Frame */
      .live-output-frame {
        width: 100%;
        height: 520px;
        background: #ffffff;
        border: 1px solid var(--border);
        border-radius: 8px;
        box-shadow: 0 12px 32px rgba(0, 0, 0, 0.4);
      }

      .live-output-container {
        position: relative;
        width: 100%;
        border-radius: 10px;
        overflow: hidden;
      }

      .live-output-toolbar {
        display: flex;
        align-items: center;
        justify-content: space-between;
        background: #161b22;
        padding: 6px 12px;
        border: 1px solid var(--border);
        border-bottom: 0;
        border-radius: 8px 8px 0 0;
        font-size: 11px;
        color: var(--muted);
      }

      .browser-dots {
        display: flex;
        gap: 6px;
      }
      .browser-dot {
        width: 9px;
        height: 9px;
        border-radius: 50%;
        background: #334155;
      }
      .browser-dot.red { background: #ef4444; }
      .browser-dot.yellow { background: #eab308; }
      .browser-dot.green { background: #22c55e; }

      .browser-address {
        background: #0a0a0b;
        border: 1px solid #334155;
        border-radius: 4px;
        padding: 2px 12px;
        font-family: 'JetBrains Mono', monospace;
        font-size: 10px;
        color: #94a3b8;
        display: flex;
        align-items: center;
        gap: 6px;
      }

      @media (max-width: 767px) {
        [data-testid="stMainBlockContainer"] { padding: 1rem 0.75rem 3rem; }
        .ide-status-bar { position: static; height: auto; min-height: 30px; flex-wrap: wrap; padding: 6px 8px; }
        .ide-status-group { flex-wrap: wrap; }
        .ide-status-item { padding: 3px 6px; }
        .diff-columns { grid-template-columns: 1fr; }
        .diff-columns section { border-right: 0; border-bottom: 1px solid var(--line); }
        .diff-columns section:last-child { border-bottom: 0; }
      }
      @media (prefers-reduced-motion: reduce) {
        .stButton > button, .card { transform: none !important; }
      }
    </style>

    <script>
      (function() {
        if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
          return;
        }
        if (window.__pointerTrailInitialized) return;
        window.__pointerTrailInitialized = true;

        const count = 6;
        const dots = [];
        const coords = [];
        for (let i = 0; i < count; i++) {
          const dot = document.createElement('div');
          const opacity = (0.10 - (i / count) * 0.05).toFixed(3);
          const size = Math.max(3, 5 - i * 0.4);
          dot.style.cssText = 'position:fixed;top:0;left:0;width:' + size + 'px;height:' + size + 'px;border-radius:50%;background-color:#3b82f6;opacity:' + opacity + ';pointer-events:none;z-index:99999;transform:translate(-50%,-50%);';
          document.body.appendChild(dot);
          dots.push(dot);
          coords.push({ x: -100, y: -100 });
        }
        let mx = -100, my = -100;
        window.addEventListener('mousemove', function(e) {
          mx = e.clientX;
          my = e.clientY;
        }, { passive: true });

        function animate() {
          let px = mx, py = my;
          for (let i = 0; i < count; i++) {
            coords[i].x += (px - coords[i].x) * 0.35;
            coords[i].y += (py - coords[i].y) * 0.35;
            dots[i].style.transform = 'translate(' + coords[i].x + 'px,' + coords[i].y + 'px) translate(-50%,-50%)';
            px = coords[i].x;
            py = coords[i].y;
          }
          requestAnimationFrame(animate);
        }
        requestAnimationFrame(animate);
      })();
    </script>
    """)
