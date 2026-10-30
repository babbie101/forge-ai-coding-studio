import streamlit as st
import streamlit.components.v1 as components
import os


def _is_test_mode() -> bool:
    """Detect if running in Streamlit AppTest or pytest test environment."""
    # AppTest runs without a real ScriptRunContext
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
        if get_script_run_ctx() is None:
            return True
    except Exception:
        pass
    # Also check common test env vars
    return (
        os.getenv("STREAMLIT_TESTING") == "1"
        or os.getenv("PYTEST_CURRENT_TEST") is not None
    )


def get_interactive_ascii_html(dimmed: bool = False):
    """
    Returns the HTML/CSS/JS for the interactive ASCII sphere.
    When dimmed=True, opacity is 0.40, color is #60a5fa (brighter electric blue),
    with enhanced ambient glow text-shadow.
    """
    opacity = "0.40" if dimmed else "0.88"
    color = "#60a5fa" if dimmed else "#79c0ff"
    hint_style = "display:none;" if dimmed else "position:absolute;right:18px;bottom:15px;color:#8b949e;font:10px 'Inter',sans-serif;letter-spacing:.08em;"

    return f"""<!doctype html><html><head><style>
      html,body{{margin:0;padding:0;width:100%;height:100%;overflow:hidden;background:transparent;pointer-events:none;}}
      pre{{position:fixed;inset:0;margin:0;display:grid;place-items:center;color:{color};
          font:11px/9px 'JetBrains Mono',Consolas,monospace;letter-spacing:0;white-space:pre;
          opacity:{opacity};text-shadow:0 0 10px rgba(96,165,250,0.7),0 0 24px rgba(59,130,246,0.4);
          user-select:none;pointer-events:none;}}
      .hint{{{hint_style}}}
    </style></head><body><pre id='sphere'></pre><span class='hint'>MOVE POINTER TO DISTORT FIELD</span>
    <script>
      (function() {{
        const node=document.getElementById('sphere');
        const W=92,H=43,chars=' .,:;irsXA253hMHGS#9B&@';
        let rx=0,ry=0,targetX=0,targetY=0;
        
        function onMove(e) {{
          const win = window.parent || window;
          const w = win.innerWidth || window.innerWidth || 1200;
          const h = win.innerHeight || window.innerHeight || 800;
          targetX = (e.clientX / w - 0.5) * 1.6;
          targetY = (e.clientY / h - 0.5) * 1.1;
        }}

        window.addEventListener('pointermove', onMove, {{ passive: true }});
        try {{
          if (window.parent && window.parent !== window) {{
            window.parent.addEventListener('pointermove', onMove, {{ passive: true }});
          }}
        }} catch(e) {{}}

        function draw() {{
          rx += (targetY - rx) * 0.035 + 0.012;
          ry += (targetX - ry) * 0.035 + 0.018;
          const lines = [];
          const cr = Math.cos(rx), sr = Math.sin(rx), cy = Math.cos(ry), sy = Math.sin(ry);
          for (let y = 0; y < H; y++) {{
            let row = '';
            const py = (y - H / 2) / 18;
            for (let x = 0; x < W; x++) {{
              const px = (x - W / 2) / 37, rr = px * px + py * py;
              if (rr > 1) {{ row += ' '; continue; }}
              const pz = Math.sqrt(1 - rr);
              const nx = px * cy + pz * sy, nz = -px * sy + pz * cy;
              const ny = py * cr - nz * sr, zz = py * sr + nz * cr;
              const l = Math.max(0, nx * 0.35 + ny * (-0.45) + zz * 0.82);
              row += chars[Math.min(chars.length - 1, Math.floor(l * (chars.length - 1)))];
            }}
            lines.push(row);
          }}
          node.textContent = lines.join('\\n');
          requestAnimationFrame(draw);
        }}
        draw();
      }})();
    </script></body></html>"""


def render_ascii_background():
    """Render the interactive ASCII sphere as a full-viewport dimmed background.
    
    Renders an unboxed iframe pinned at fixed position behind all content (z-index -1),
    with pointer-events: none so clicks cleanly pass through to all Streamlit UI layers.
    """
    if _is_test_mode():
        return
    html_content = get_interactive_ascii_html(dimmed=True)
    components.html(html_content, height=0)


def render_bitmap_animation(dimmed: bool = True):
    """Backward compatibility wrapper rendering the background."""
    render_ascii_background()


def render_datastream_pulse(active: bool = False, file_count: int = 1):
    """Renders high-speed luminous data-stream cyber particles flowing from Forge to Output Window.
    
    Triggered when AI patches or file modifications occur. Runs lightweight canvas animation
    with glow particles that dissipate into the right pane.
    """
    if not active or _is_test_mode():
        return
    
    pulse_html = f"""<!doctype html><html><head><style>
      html, body {{ margin:0; padding:0; width:100%; height:100%; overflow:hidden; background:transparent; pointer-events:none; }}
      canvas {{ position:fixed; top:0; left:0; width:100vw; height:100vh; pointer-events:none; z-index:9999; }}
    </style></head><body>
      <canvas id="pulse-canvas"></canvas>
      <script>
        (function() {{
          const c = document.getElementById('pulse-canvas');
          if (!c) return;
          const ctx = c.getContext('2d');
          const dpr = window.devicePixelRatio || 1;
          const W = window.innerWidth || 1200;
          const H = window.innerHeight || 800;
          c.width = W * dpr;
          c.height = H * dpr;
          ctx.scale(dpr, dpr);

          const particles = [];
          const count = Math.min(80, 30 + {file_count} * 20);
          const startX = W * 0.42;
          const startY = H * 0.45;
          const targetX = W * 0.78;
          const targetY = H * 0.45;

          for (let i = 0; i < count; i++) {{
            particles.push({{
              x: startX + (Math.random() - 0.5) * 60,
              y: startY + (Math.random() - 0.5) * 120,
              vx: 5 + Math.random() * 9,
              vy: (Math.random() - 0.5) * 3,
              size: 2 + Math.random() * 3.5,
              alpha: 0.95,
              decay: 0.016 + Math.random() * 0.02,
              hue: Math.random() > 0.4 ? '#3b82f6' : (Math.random() > 0.5 ? '#06b6d4' : '#22c55e')
            }});
          }}

          let start = performance.now();
          function animate(now) {{
            ctx.clearRect(0, 0, W, H);
            let alive = false;
            for (let p of particles) {{
              if (p.alpha > 0.02) {{
                alive = true;
                ctx.save();
                ctx.beginPath();
                ctx.arc(p.x, p.y, p.size, 0, Math.PI * 2);
                ctx.fillStyle = p.hue;
                ctx.shadowColor = p.hue;
                ctx.shadowBlur = 10;
                ctx.globalAlpha = p.alpha;
                ctx.fill();
                ctx.restore();

                p.x += p.vx;
                p.y += p.vy;
                p.alpha -= p.decay;
                p.size = Math.max(0.2, p.size - 0.02);
              }}
            }}
            if (alive && (now - start < 1800)) {{
              requestAnimationFrame(animate);
            }}
          }}
          requestAnimationFrame(animate);
        }})();
      </script>
    </body></html>"""
    components.html(pulse_html, height=0)

