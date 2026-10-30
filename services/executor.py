import ast
import atexit
import mimetypes
import socket
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit
from urllib.request import urlopen

from utils.helpers import safe_file_path


_STATIC_EXTENSIONS = {
    ".css", ".csv", ".gif", ".htm", ".html", ".ico", ".jpeg", ".jpg",
    ".js", ".json", ".map", ".mjs", ".mp3", ".mp4", ".otf", ".pdf",
    ".png", ".svg", ".txt", ".webm", ".webp", ".woff", ".woff2", ".xml",
}
_static_servers = {}
_streamlit_processes = {}
_static_lock = threading.Lock()
_streamlit_lock = threading.Lock()


def _static_preview_handler(root: Path):
    class StaticPreviewHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self._serve_file(send_body=True)

        def do_HEAD(self):
            self._serve_file(send_body=False)

        def _serve_file(self, send_body: bool):
            relative_path = unquote(urlsplit(self.path).path).lstrip("/")
            if not relative_path:
                relative_path = "index.html"
            if any(part.startswith(".") for part in Path(relative_path).parts):
                self.send_error(404)
                return

            target = safe_file_path(root, relative_path)
            if target is None:
                self.send_error(404)
                return
            if target.is_dir():
                target = safe_file_path(root, f"{relative_path.rstrip('/')}/index.html")
            if (
                target is None
                or not target.is_file()
                or target.suffix.lower() not in _STATIC_EXTENSIONS
            ):
                self.send_error(404)
                return

            content_type, _encoding = mimetypes.guess_type(target.name)
            self.send_response(200)
            self.send_header("Content-Type", content_type or "application/octet-stream")
            self.send_header("Content-Length", str(target.stat().st_size))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            if send_body:
                with target.open("rb") as source:
                    while chunk := source.read(64 * 1024):
                        self.wfile.write(chunk)

        def log_message(self, _format, *_args):
            return

    return StaticPreviewHandler


def _get_static_preview_server(root: Path):
    root = root.resolve()
    root_key = str(root)
    with _static_lock:
        server = _static_servers.get(root_key)
        if server is None:
            server = ThreadingHTTPServer(
                ("127.0.0.1", 0), _static_preview_handler(root)
            )
            server.daemon_threads = True
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            _static_servers[root_key] = server
        return server


def _stop_static_preview_servers():
    for server in list(_static_servers.values()):
        server.shutdown()
        server.server_close()
    _static_servers.clear()


atexit.register(_stop_static_preview_servers)


def get_static_preview_url(
    root: str | Path, entry_file: str, cache_bust: str | int = ""
):
    """Return a loopback URL for a safe static preview file in the workspace."""
    root_path = Path(root).resolve()
    target = safe_file_path(root_path, entry_file)
    if (
        target is None
        or not target.is_file()
        or target.suffix.lower() not in _STATIC_EXTENSIONS
        or any(part.startswith(".") for part in Path(entry_file).parts)
    ):
        return None

    server = _get_static_preview_server(root_path)
    relative_path = target.relative_to(root_path).as_posix()
    version = cache_bust or target.stat().st_mtime_ns
    return (
        f"http://127.0.0.1:{server.server_port}/{quote(relative_path, safe='/')}"
        f"?v={quote(str(version))}"
    )


def is_streamlit_app(path: Path | str) -> bool:
    """Identify Streamlit entry points without executing the project code."""
    try:
        source = Path(path).read_text(encoding="utf-8")
        tree = ast.parse(source)
    except (OSError, UnicodeDecodeError, SyntaxError):
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import) and any(
            alias.name == "streamlit" for alias in node.names
        ):
            return True
        if isinstance(node, ast.ImportFrom) and node.module == "streamlit":
            return True
    return False


def _stop_streamlit_preview(preview):
    process = preview["process"]
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)
    preview["log"].close()


def _stop_all_streamlit_previews():
    for preview in list(_streamlit_processes.values()):
        _stop_streamlit_preview(preview)
    _streamlit_processes.clear()


atexit.register(_stop_all_streamlit_previews)


def start_streamlit_preview(
    path: Path | str,
    timeout: float = 15,
    working_directory: Path | str | None = None,
):
    """Start or reuse a Streamlit app bound to loopback for inline preview."""
    script = Path(path).resolve()
    if not script.is_file() or script.suffix.lower() != ".py":
        return None, f"Streamlit entry file not found: {script.name}"

    script_key = str(script)
    with _streamlit_lock:
        existing = _streamlit_processes.get(script_key)
        if existing and existing["process"].poll() is None:
            return existing["url"], None
        if existing:
            _stop_streamlit_preview(existing)
            del _streamlit_processes[script_key]

        with socket.socket() as port_socket:
            port_socket.bind(("127.0.0.1", 0))
            port = port_socket.getsockname()[1]
        log_file = tempfile.TemporaryFile(mode="w+b")
        command = [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            str(script),
            "--server.headless",
            "true",
            "--server.address",
            "127.0.0.1",
            "--server.port",
            str(port),
            "--server.enableCORS",
            "false",
            "--server.enableXsrfProtection",
            "false",
            "--browser.gatherUsageStats",
            "false",
        ]
        try:
            process = subprocess.Popen(
                command,
                cwd=str(Path(working_directory).resolve() if working_directory else script.parent),
                stdout=log_file,
                stderr=subprocess.STDOUT,
            )
        except OSError as error:
            log_file.close()
            return None, f"Could not start the Streamlit preview: {error}"

        url = f"http://127.0.0.1:{port}/"
        preview = {"process": process, "url": url, "log": log_file}
        _streamlit_processes[script_key] = preview
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if process.poll() is not None:
                break
            try:
                with urlopen(f"{url}_stcore/health", timeout=0.5) as response:
                    if response.status == 200:
                        return url, None
            except OSError:
                time.sleep(0.2)

        log_file.seek(0)
        details = log_file.read().decode("utf-8", errors="replace").strip()
        _stop_streamlit_preview(preview)
        del _streamlit_processes[script_key]
        message = (
            details[-1200:]
            if details
            else "The preview did not become ready in time."
        )
        return None, message


def run_python_preview(path: Path | str, timeout: int = 30):
    """Run a user-selected workspace script and return its captured output."""
    try:
        resolved_path = Path(path).resolve()
        if not resolved_path.is_file():
            return "", f"Error: File not found at '{resolved_path}'"
        if resolved_path.suffix.lower() == ".html":
            webbrowser.open(resolved_path.as_uri())
            return f"Opened {resolved_path.name} in browser.", ""
        if resolved_path.suffix.lower() != ".py":
            return "", f"Error: Unsupported preview file type '{resolved_path.suffix or '(none)'}'."

        result = subprocess.run(
            [sys.executable, str(resolved_path)],
            cwd=str(resolved_path.parent),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
        return result.stdout, result.stderr
    except subprocess.TimeoutExpired as e:
        stdout = e.stdout or ""
        stderr = e.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        timeout_message = f"Execution timed out after {timeout} seconds."
        return stdout, f"{stderr.rstrip()}\n{timeout_message}".lstrip()
    except Exception as e:
        return "", f"Execution error: {str(e)}"


def detect_workspace_preview_type(target_dir: str, entry_file: str | None = None):
    """Detect the preview mode of the workspace using strictly absolute paths.
    
    Returns a dict with:
      - 'type': 'web' | 'python' | 'markdown' | 'empty'
      - 'entry_file': relative/filename of entry point (e.g. 'index.html', 'app.py')
      - 'entry_path': absolute Path to entry point
      - 'html_content': raw HTML if available, or None
    """
    root = Path(target_dir).resolve()
    if not root.is_dir():
        return {"type": "empty", "entry_file": None, "entry_path": None, "html_content": None}

    if entry_file:
        from utils.helpers import safe_file_path

        selected_path = safe_file_path(root, entry_file)
        if selected_path is None or not selected_path.is_file():
            return {"type": "empty", "entry_file": None, "entry_path": None, "html_content": None}
        suffix = selected_path.suffix.lower()
        if suffix in {".html", ".htm", ".xhtml"}:
            return {
                "type": "web",
                "entry_file": Path(entry_file).as_posix(),
                "entry_path": selected_path,
                "html_content": selected_path.read_text(encoding="utf-8", errors="replace"),
            }
        if suffix == ".py":
            return {
                "type": "python",
                "entry_file": Path(entry_file).as_posix(),
                "entry_path": selected_path,
                "html_content": None,
            }
        if suffix in {".md", ".markdown"}:
            return {
                "type": "markdown",
                "entry_file": Path(entry_file).as_posix(),
                "entry_path": selected_path,
                "html_content": None,
            }
        return {"type": "empty", "entry_file": None, "entry_path": None, "html_content": None}

    # 1. Web application: check for index.html or *.html
    index_html = (root / "index.html").resolve()
    if index_html.is_file():
        try:
            return {
                "type": "web",
                "entry_file": "index.html",
                "entry_path": index_html,
                "html_content": index_html.read_text(encoding="utf-8", errors="replace"),
            }
        except Exception:
            pass

    for html_file in root.glob("*.html"):
        resolved_html = html_file.resolve()
        if resolved_html.is_file():
            try:
                return {
                    "type": "web",
                    "entry_file": resolved_html.name,
                    "entry_path": resolved_html,
                    "html_content": resolved_html.read_text(encoding="utf-8", errors="replace"),
                }
            except Exception:
                pass

    # 2. Python application: check app.py, main.py, or any *.py
    for py_candidate in ["app.py", "main.py", "run.py"]:
        candidate_path = (root / py_candidate).resolve()
        if candidate_path.is_file():
            return {
                "type": "python",
                "entry_file": py_candidate,
                "entry_path": candidate_path,
                "html_content": None,
            }
    
    first_py = next(root.glob("*.py"), None)
    if first_py:
        resolved_py = first_py.resolve()
        return {
            "type": "python",
            "entry_file": resolved_py.name,
            "entry_path": resolved_py,
            "html_content": None,
        }

    # 3. Markdown / text documentation
    first_md = next(root.glob("*.md"), None)
    if first_md:
        resolved_md = first_md.resolve()
        return {
            "type": "markdown",
            "entry_file": resolved_md.name,
            "entry_path": resolved_md,
            "html_content": None,
        }

    return {"type": "empty", "entry_file": None, "entry_path": None, "html_content": None}
