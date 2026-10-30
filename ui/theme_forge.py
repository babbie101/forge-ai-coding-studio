import streamlit as st


def inject_theme():
    """Apply FORGE's dark editorial interface with restrained blue accents."""
    st.html("""
    <style>
      @import url('https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,400;0,500;1,400;1,500&family=Space+Mono:wght@400;700&display=swap');

      :root {
        --ink: #000000;
        --surface: #080808;
        --surface-raised: #111111;
        --line: #2c2c2c;
        --white: #f5f5f2;
        --gray: #9a9a9a;
        --gray-dim: #5a5a5a;
        --accent: #79aee8;
        --accent-soft: #172436;
        --green: #9bb9a5;
        --red: #d78c8c;
      }

      html, body, .stApp {
        background: var(--ink) !important;
        color: var(--white) !important;
        font-family: 'Space Mono', monospace !important;
        font-size: 13px !important;
      }
      [data-testid="stAppViewContainer"],
      [data-testid="stMain"],
      [data-testid="stMainBlockContainer"] {
        background: var(--ink) !important;
      }
      [data-testid="stMainBlockContainer"] {
        max-width: 1280px;
        padding-top: 2rem;
        padding-bottom: 4rem;
      }

      h1, h2, h3, h4, h5, h6 {
        color: var(--white) !important;
        font-family: 'Cormorant Garamond', Georgia, serif !important;
        font-style: italic !important;
        font-weight: 400 !important;
        letter-spacing: 0 !important;
      }
      h1 { font-size: clamp(2.8rem, 6vw, 5rem) !important; line-height: 0.98 !important; }
      h2 { font-size: clamp(2rem, 4vw, 3rem) !important; }
      h3 { font-size: clamp(1.45rem, 2.8vw, 2rem) !important; }
      p, label, [data-testid="stCaptionContainer"] {
        font-family: 'Space Mono', monospace !important;
      }
      [data-testid="stCaptionContainer"] {
        color: var(--gray) !important;
        line-height: 1.8 !important;
      }
      a { color: var(--accent) !important; text-decoration-color: #42658a !important; }
      a:hover { color: #a7ccf5 !important; text-decoration-color: var(--accent) !important; }
      ::selection { background: var(--white); color: var(--ink); }

      [data-testid="stSidebar"] {
        background: var(--ink) !important;
        border-right: 1px solid var(--line) !important;
      }
      [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p {
        color: var(--gray);
      }
      .forge-sidebar-brand {
        padding: 0.35rem 0 0.8rem;
        color: var(--white);
        font: italic 1.85rem/1 'Cormorant Garamond', Georgia, serif;
      }
      .forge-sidebar-brand span {
        display: block;
        margin-top: 0.65rem;
        color: var(--gray-dim);
        font: 0.58rem/1.6 'Space Mono', monospace;
        letter-spacing: 0.16em;
        text-transform: uppercase;
      }

      [data-testid="stVerticalBlockBorderWrapper"],
      .blueprint-grid, .card, .studio-pane {
        background: var(--surface) !important;
        border: 1px solid var(--line) !important;
        border-radius: 2px !important;
        box-shadow: none !important;
      }
      .stButton > button {
        min-height: 2.55rem;
        padding: 0.45rem 0.85rem !important;
        border: 1px solid var(--line) !important;
        border-radius: 1px !important;
        background: var(--ink) !important;
        color: var(--white) !important;
        font: 400 0.7rem 'Space Mono', monospace !important;
        letter-spacing: 0.06em;
        text-transform: uppercase;
        transition: background 150ms ease, color 150ms ease, border-color 150ms ease !important;
      }
      .stButton > button:hover {
        border-color: var(--accent) !important;
        background: var(--accent-soft) !important;
        color: #c5ddfa !important;
        transform: none !important;
        box-shadow: none !important;
      }
      button[kind^="primary"] {
        border-color: var(--accent) !important;
        background: var(--accent-soft) !important;
        color: #c5ddfa !important;
        font-weight: 700 !important;
      }
      button[kind^="primary"]:hover {
        border-color: #a7ccf5 !important;
        background: #203652 !important;
        color: #ffffff !important;
      }
      input, textarea, [data-baseweb="select"] > div {
        border: 1px solid var(--line) !important;
        border-radius: 1px !important;
        background: var(--surface-raised) !important;
        color: var(--white) !important;
        font-family: 'Space Mono', monospace !important;
      }
      input::placeholder, textarea::placeholder {
        color: var(--gray-dim) !important;
      }
      input:focus, textarea:focus, [data-baseweb="select"] > div:focus-within,
      .stButton > button:focus-visible {
        outline: 1px solid var(--accent) !important;
        outline-offset: 2px !important;
        border-color: var(--accent) !important;
        box-shadow: none !important;
      }

      [data-testid="stTabs"] [data-baseweb="tab"] {
        color: var(--gray) !important;
        font: 400 0.7rem 'Space Mono', monospace !important;
        letter-spacing: 0.08em;
        text-transform: uppercase;
      }
      [data-testid="stTabs"] [aria-selected="true"] {
        color: var(--accent) !important;
        border-bottom-color: var(--accent) !important;
      }
      [data-testid="stProgressBar"] > div > div {
        background: var(--accent) !important;
      }
      [data-testid="stProgress"] [data-testid="stMarkdownContainer"] p {
        color: var(--gray) !important;
      }
      [data-testid="stCodeBlock"], code, pre, .ide-console {
        font-family: 'Space Mono', monospace !important;
      }
      .ide-console {
        padding: 1rem;
        border: 1px solid var(--line);
        background: var(--surface);
        color: #d0d0d0;
        white-space: pre-wrap;
      }
      .live-output-frame {
        border: 1px solid var(--line);
        border-radius: 1px;
        background: var(--surface);
      }
      .geo-line, .forge-rule {
        height: 1px;
        margin: 1.25rem 0;
        background: linear-gradient(90deg, transparent, var(--line) 12%, var(--line) 88%, transparent);
      }
      .forge-steps {
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        gap: 0.55rem 1.2rem;
        color: var(--gray);
        font: 400 0.66rem/1.8 'Space Mono', monospace;
        letter-spacing: 0.06em;
        text-transform: uppercase;
      }
      .forge-steps strong {
        color: var(--white);
        font-weight: 400;
      }
      .roadmap-track {
        display: flex;
        flex-wrap: wrap;
        gap: 0.5rem;
        padding: 0.9rem 0 1.1rem;
      }
      .roadmap-node {
        display: flex;
        flex: 1 1 145px;
        min-width: 125px;
        align-items: center;
        gap: 0.65rem;
        padding: 0.7rem 0.8rem;
        border: 1px solid var(--line);
        border-radius: 1px;
        background: var(--surface);
        animation: roadmap-arrive 280ms ease-out both;
      }
      .roadmap-node:nth-child(2) { animation-delay: 35ms; }
      .roadmap-node:nth-child(3) { animation-delay: 70ms; }
      .roadmap-node:nth-child(4) { animation-delay: 105ms; }
      .roadmap-node:nth-child(5) { animation-delay: 140ms; }
      .roadmap-node.active { border-color: var(--white); }
      .roadmap-node.done { border-color: #53675a; }
      .roadmap-node-icon {
        display: grid;
        flex: 0 0 2rem;
        width: 2rem;
        height: 2rem;
        place-items: center;
        border: 1px solid var(--line);
        border-radius: 50%;
        color: var(--gray);
        font: 400 0.68rem 'Space Mono', monospace;
      }
      .roadmap-node.active .roadmap-node-icon {
        border-color: var(--white);
        background: var(--white);
        color: var(--ink);
      }
      .roadmap-node.done .roadmap-node-icon {
        border-color: #53675a;
        color: var(--green);
      }
      .roadmap-node-title {
        overflow: hidden;
        color: #d0d0d0;
        font: 400 0.66rem/1.55 'Space Mono', monospace;
        text-overflow: ellipsis;
      }
      .roadmap-node.active .roadmap-node-title { color: var(--white); }
      .status-pill {
        display: inline-flex;
        align-items: center;
        gap: 0.45rem;
        padding: 0.3rem 0.6rem;
        border: 1px solid var(--line);
        border-radius: 1px;
        background: var(--surface);
        color: var(--white) !important;
        font: 400 0.66rem 'Space Mono', monospace;
      }
      .connection-dot, .status-dot {
        display: inline-block;
        width: 7px;
        height: 7px;
        border-radius: 50%;
        background: var(--gray);
      }
      .status-dot.green { background: var(--green); }
      .status-dot.blue { background: var(--accent); }
      .status-dot.yellow, .status-dot.pink, .status-dot.purple { background: var(--gray-dim); }
      .recent-projects-header {
        margin-bottom: 8px;
        color: var(--gray-dim);
        font: 400 0.64rem 'Space Mono', monospace;
        letter-spacing: 0.16em;
        text-transform: uppercase;
      }
      [data-testid="stHeader"], [data-testid="stToolbar"] {
        background: var(--ink) !important;
      }

      @keyframes roadmap-arrive {
        from { opacity: 0; transform: translateY(4px); }
        to { opacity: 1; transform: translateY(0); }
      }
      @media (max-width: 767px) {
        [data-testid="stMainBlockContainer"] { padding: 1.2rem 0.8rem 3rem; }
        .ide-status-bar { position: static; height: auto; min-height: 30px; flex-wrap: wrap; padding: 6px 8px; }
        .ide-status-group { flex-wrap: wrap; }
        .ide-status-item { padding: 3px 6px; }
        .diff-columns { grid-template-columns: 1fr; }
        .diff-columns section { border-right: 0; border-bottom: 1px solid var(--line); }
        .diff-columns section:last-child { border-bottom: 0; }
      }
      @media (prefers-reduced-motion: reduce) {
        .roadmap-node { animation: none; }
        .stButton > button { transition: none !important; }
      }
    </style>
    """)
