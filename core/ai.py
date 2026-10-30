import os
import json
import re
import html
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen
from pathlib import Path
import streamlit as st
from openai import OpenAI, APIError, RateLimitError, APIConnectionError, APITimeoutError, APIStatusError
from utils.helpers import safe_file_path

# Default Groq model (no "openai/" prefix, which only works on OpenRouter).
# "llama-3.3-70b-versatile" is the verified model on api.groq.com.
_GROQ_DEFAULT_MODEL = "llama-3.3-70b-versatile"

class AIProviderError(Exception):
    """Raised when an AI provider request fails.

    Carries the HTTP status code so callers can render targeted
    inline notifications (e.g. HTTP 429 = rate limit, HTTP 400 = template/role mismatch).
    """
    def __init__(self, message, status_code=None, details=None):
        super().__init__(message)
        self.status_code = status_code
        self.details = details or {}


_ai_providers = {
    "groq": {
        "base_url": "https://api.groq.com/openai/v1/",
        "key_env": "GROQ_API_KEY",
        "label": "Groq AI",
        # Default Groq model chosen to avoid MiniJinja template role errors.
        "models": {
            "GPT-OSS 20B": "gpt-oss-20b",
            "Llama 3.3 70B": "llama-3.3-70b-versatile",
        },
    },
    "nebius": {
        "base_url": "https://api.tokenfactory.nebius.com/v1/",
        "key_env": "NEBIUS_API_KEY",
        "label": "Nebius AI",
        "models": {
            "Nemotron 3 Nano 30B": "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B",
        },
    },
    "ollama": {
        "base_url": "http://localhost:11434/v1/",
        "key_env": "OLLAMA_API_KEY",
        "label": "Ollama (Local)",
        "models": {
            "Llama 3": "llama3",
            "CodeLlama": "codellama",
            "DeepSeek Coder": "deepseek-coder",
        },
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1/",
        "key_env": "OPENROUTER_API_KEY",
        "label": "OpenRouter",
        "models": {
            "North Mini Code (Free)": "cohere/north-mini-code:free",
            "Nemotron Lightning (Free)": "nvidia/nemotron-3.5-lightning:free",
            "Gemma 4 26B (Free)": "google/gemma-4-26b-a4b-it:free",
        },
    },
}


def available_chat_models():
    models = {}
    for prov in _ai_providers.values():
        models.update(prov["models"])
    return models


@st.cache_data(ttl=20, max_entries=8, show_spinner=False)
def _list_available_ollama_models(base_url: str):
    """Cache the local server probe briefly to keep UI reruns responsive."""
    try:
        import urllib.request
        normalized_url = base_url.rstrip("/")
        native_url = normalized_url[:-3] if normalized_url.endswith("/v1") else normalized_url
        with urllib.request.urlopen(f"{native_url}/api/tags", timeout=1.0) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return [model["name"] for model in payload.get("models", []) if model.get("name")]
    except Exception:
        return []


@st.cache_resource(max_entries=8, show_spinner=False)
def _get_openai_client(base_url: str, api_key: str):
    """Reuse HTTP connection pools across chat and generation requests."""
    return OpenAI(base_url=base_url, api_key=api_key)


def list_available_ollama_models():
    """Return the model names currently installed on the local Ollama server.

    Native Ollama serves a plain JSON list of installed models at
    /api/tags. Returns an empty list when the server is down or unreachable.
    """
    base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1/")
    return _list_available_ollama_models(base_url)


def _is_ollama_endpoint(base_url: str) -> bool:
    configured_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1/")
    if base_url.rstrip("/").casefold() != configured_url.rstrip("/").casefold():
        return False
    return urlsplit(configured_url).hostname in {"localhost", "127.0.0.1", "::1"}


def _ollama_chat(
    messages,
    base_url,
    model,
    max_tokens,
    temperature,
    include_metadata,
    stream_callback=None,
):
    endpoint = urlsplit(base_url.rstrip("/"))
    endpoint_path = endpoint.path[:-3] if endpoint.path.endswith("/v1") else endpoint.path
    native_url = urlunsplit(
        (endpoint.scheme, endpoint.netloc, endpoint_path.rstrip("/") + "/api/chat", "", "")
    )
    request_payload = {
        "model": model,
        "messages": messages,
        "stream": stream_callback is not None,
        "options": {
            "num_predict": max_tokens,
            "temperature": temperature,
        },
    }
    if model.casefold().startswith("qwen3.5"):
        request_payload["think"] = False

    request = Request(
        native_url,
        data=json.dumps(request_payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=180) as response:
            if stream_callback:
                chunks = []
                payload = {}
                for line in response:
                    if not line.strip():
                        continue
                    payload = json.loads(line.decode("utf-8"))
                    message = payload.get("message", {})
                    text = message.get("content", "") if isinstance(message, dict) else ""
                    if text:
                        chunks.append(text)
                        stream_callback(text)
                payload["message"] = {"content": "".join(chunks)}
            else:
                payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        details = error.read().decode("utf-8", errors="replace").strip()
        raise AIProviderError(
            f"Ollama request failed (HTTP {error.code})."
            + (f" {details}" if details else ""),
            status_code=error.code,
            details={"provider": "ollama"},
        ) from error
    except (URLError, TimeoutError, OSError) as error:
        raise AIProviderError(
            "Could not reach Ollama. Start the local Ollama server and retry.",
            status_code=503,
            details={"provider": "ollama"},
        ) from error
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise AIProviderError(
            "Ollama returned an invalid response.",
            status_code=502,
            details={"provider": "ollama"},
        ) from error

    message = payload.get("message", {}) if isinstance(payload, dict) else {}
    content = message.get("content", "") if isinstance(message, dict) else ""
    usage = {
        "model": payload.get("model", model),
        "prompt_tokens": payload.get("prompt_eval_count"),
        "completion_tokens": payload.get("eval_count"),
    }
    prompt_tokens = usage["prompt_tokens"] or 0
    completion_tokens = usage["completion_tokens"] or 0
    usage["total_tokens"] = (
        prompt_tokens + completion_tokens
        if usage["prompt_tokens"] is not None or usage["completion_tokens"] is not None
        else None
    )
    return (content, usage) if include_metadata else content


def _http_error_label(status_code):
    labels = {
        400: "Bad Request (HTTP 400) — template/role mismatch",
        401: "Unauthorized (HTTP 401) — invalid API key",
        402: "Payment Required (HTTP 402)",
        404: "Not Found (HTTP 404)",
        413: "Payload Too Large (HTTP 413)",
        429: "Rate Limited (HTTP 429) — slow down your requests",
        500: "Internal Server Error (HTTP 500)",
        502: "Bad Gateway (HTTP 502)",
        503: "Service Unavailable (HTTP 503)",
    }
    return labels.get(status_code, f"HTTP {status_code}")


def ai_chat(
    messages,
    base_url,
    api_key,
    model,
    max_tokens=2048,
    temperature=0.2,
    include_metadata=False,
    stream_callback=None,
):
    """Call an OpenAI-compatible chat endpoint.

    Set ``include_metadata`` for UI callers that need token accounting without
    coupling the rest of the application to an OpenAI response object.
    """
    if _is_ollama_endpoint(base_url):
        result = _ollama_chat(
            messages,
            base_url,
            model,
            max_tokens,
            temperature,
            include_metadata,
            stream_callback=stream_callback,
        )
        content = result[0] if include_metadata else result
        if not content or not content.strip():
            raise AIProviderError("The AI returned an empty response. Please retry.")
        return result

    client = _get_openai_client(base_url, api_key)
    try:
        if stream_callback:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
            )
            chunks = []
            response_model = model
            for chunk in response:
                response_model = getattr(chunk, "model", response_model) or response_model
                choices = getattr(chunk, "choices", [])
                if not choices:
                    continue
                delta = getattr(choices[0], "delta", None)
                text = getattr(delta, "content", None) if delta else None
                if isinstance(text, str) and text:
                    chunks.append(text)
                    stream_callback(text)
            content = "".join(chunks)
            metadata = {
                "model": response_model,
                "prompt_tokens": None,
                "completion_tokens": None,
                "total_tokens": None,
            }
        else:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            content = response.choices[0].message.content or ""
            usage = getattr(response, "usage", None)
            metadata = {
                "model": getattr(response, "model", model),
                "prompt_tokens": getattr(usage, "prompt_tokens", None),
                "completion_tokens": getattr(usage, "completion_tokens", None),
                "total_tokens": getattr(usage, "total_tokens", None),
            }
        if not content or not content.strip():
            raise AIProviderError("The AI returned an empty response. Please retry.")
        return (content, metadata) if include_metadata else content
    except RateLimitError as e:
        raise AIProviderError(
            "Rate limit exceeded (HTTP 429). Please slow down your requests and retry.",
            status_code=429,
            details={"provider": base_url},
        ) from e
    except APIStatusError as e:
        is_nebius = (urlsplit(base_url).hostname or "").casefold() in {
            "api.studio.nebius.ai",
            "api.tokenfactory.nebius.com",
        }
        if is_nebius and e.status_code in {401, 403}:
            raise AIProviderError(
                "Nebius rejected this API key. Confirm NEBIUS_API_KEY is active "
                "in your Token Factory project, then restart the app after updating `.env`.",
                status_code=e.status_code,
                details={"provider": "nebius", "key_problem": True},
            ) from e
        if e.status_code == 404:
            raise AIProviderError(
                "Model not found (HTTP 404). Select a model available from the active provider and retry.",
                status_code=404,
                details={"provider": base_url},
            ) from e
        if e.status_code == 400:
            raise AIProviderError(
                "Invalid request (HTTP 400). Check your prompt format, model compatibility, "
                "or that the model supports the messages API.",
                status_code=400,
                details={"provider": base_url},
            ) from e
        raise AIProviderError(
            f"API error: {_http_error_label(e.status_code)}",
            status_code=e.status_code,
            details={"provider": base_url},
        ) from e
    except APIConnectionError as e:
        raise AIProviderError(
            "Failed to connect to the AI provider. Check your internet connection and API endpoint.",
            status_code=503,
            details={"provider": base_url},
        ) from e
    except APITimeoutError as e:
        raise AIProviderError(
            "Request timed out. Try again with a shorter prompt or a faster model.",
            status_code=408,
            details={"provider": base_url},
        ) from e
    except APIError as e:
        raise AIProviderError(
            f"AI provider error: {str(e)}",
            status_code=getattr(e, "status_code", None),
            details={"provider": base_url},
        ) from e


def generate_architecture(topic, model, base_url, api_key):
    system = (
        "You are a software architect. Given a project idea, design a small starter codebase. "
        "Return ONLY a JSON object with this exact shape (no markdown, no commentary):\n\n"
        '{\n  "summary": "one sentence summary",\n  "folders": ["src", "src/routes"],\n'
        '  "files": [\n    {"path": "src/main.py", "description": "FastAPI entry point"}\n  ],\n'
        '  "animations": [\n    {"name": "Fade-in on load", "description": "Elements fade in smoothly when the page loads", "location": "main content area"}\n  ],\n'
        '  "roadmap": [\n    {"phase": "Phase 1", "goal": "Set up structure"}\n  ],\n'
        '  "dependencies": ["package-name"],\n  "run_checklist": ["Install dependencies", "Run the project"]\n}\n\n'
        "For the roadmap, describe 3-6 concrete development phases (setup, core features, polish, deploy) "
        "with a brief goal for each.\n\n"
        "Include concise dependencies, a build/run checklist, and 2-3 light animation suggestions. "
        "Keep it small: 3-8 files total. Ensure the plan fits on one screen with minimal vertical space."
    )
    try:
        raw = ai_chat(
            [{"role": "system", "content": system},
             {"role": "user", "content": f"Project idea: {topic}"}],
            # Free OpenRouter reasoning models may spend several hundred tokens
            # planning internally before they emit their JSON. Keep this budget
            # high enough that a complete small architecture reaches the client.
            base_url=base_url, api_key=api_key, model=model, max_tokens=2400, temperature=0.3,
        )
    except AIProviderError as e:
        raise AIProviderError(f"Architecture generation failed: {e}", status_code=e.status_code) from e
    except Exception as e:
        raise AIProviderError(f"Architecture generation failed: {e}") from e

    cleaned = _extract_json_object(raw)
    try:
        plan = json.loads(cleaned)
        required = {"summary", "folders", "files", "roadmap", "dependencies", "run_checklist"}  # "animations" is optional
        if not isinstance(plan, dict) or not required.issubset(plan):
            raise ValueError("missing required architecture fields")
        return plan
    except json.JSONDecodeError as e:
        raise AIProviderError(
            "Architecture planning returned an incomplete response. Please retry; the free model may be busy.",
            details={"response_preview": raw[:200]},
        ) from e
    except ValueError as e:
        raise AIProviderError(f"Architecture plan is missing required fields: {e}") from e


def generate_roadmap(
    vision: str,
    plan: dict,
    model: str,
    base_url: str,
    api_key: str,
    expanded: bool = False,
):
    """Generate a short roadmap, or detailed coding steps when expanded is true."""
    if expanded:
        scope = (
            "Create 5-8 concrete coding tasks. For each task, include a concise description, "
            "a practical implementation approach, and the relevant planned file paths."
        )
        max_tokens = 2000
    else:
        scope = (
            "Create exactly 3 concise roadmap phases that take the user from setup, through the "
            "core user-facing feature, to testing and polish. Each title should be short; each "
            "description must be one clear sentence. Do not include libraries or detailed design advice."
        )
        max_tokens = 900
    system = (
        "You are a practical product engineer. Given a project vision and its architecture, "
        f"{scope}\n"
        "Make the work specific to the user's idea rather than generic boilerplate. "
        "Map each step to relevant files from the plan when possible.\n"
        "Return ONLY a JSON object with this exact shape:\n"
        '{\n  "steps": [\n'
        '    {\n'
        '      "id": "step_1",\n'
        '      "title": "Short title",\n'
        '      "description": "Concrete action details",\n'
        '      "approach": "Implementation strategy: libraries, patterns, key decisions",\n'
        '      "suggested_file_paths": ["src/models.py"]\n'
        '    }\n'
        '  ]\n}\n'
    )
    plan_summary = json.dumps({
        "summary": plan.get("summary", ""),
        "folders": plan.get("folders", []),
        "files": plan.get("files", []),
    })
    prompt = f"Project Vision: {vision}\n\nArchitecture Plan:\n{plan_summary}"
    try:
        raw = ai_chat(
            [{"role": "system", "content": system},
             {"role": "user", "content": prompt}],
            base_url=base_url, api_key=api_key, model=model, max_tokens=max_tokens, temperature=0.3,
        )
    except AIProviderError as e:
        raise AIProviderError(f"Roadmap generation failed: {e}", status_code=e.status_code) from e
    except Exception as e:
        raise AIProviderError(f"Roadmap generation failed: {e}") from e

    cleaned = _extract_json_object(raw)
    try:
        data = json.loads(cleaned)
        steps = data.get("steps")
        if not isinstance(steps, list) or not steps:
            raise ValueError("the response did not contain any roadmap steps")
        steps = steps[:8 if expanded else 3]
        for idx, step in enumerate(steps, start=1):
            if not isinstance(step, dict):
                raise ValueError(f"roadmap step {idx} was not an object")
            step.setdefault("id", f"step_{idx}")
            step.setdefault("status", "planned")
            step.setdefault(
                "approach",
                "Implement this step against the project plan and verify the result."
                if expanded else "",
            )
            step.setdefault("suggested_file_paths", [])
        if not expanded and len(steps) < 3:
            phase_defaults = [
                ("Set up the project", "Prepare the planned files and project structure."),
                ("Build the core experience", "Implement the main user-facing behavior."),
                ("Test and polish", "Run the project, check its main flow, and fix rough edges."),
            ]
            for idx in range(len(steps), 3):
                title, description = phase_defaults[idx]
                steps.append({
                    "id": f"step_{idx + 1}",
                    "title": title,
                    "description": description,
                    "approach": "Work in small changes and verify the result in the project preview.",
                    "suggested_file_paths": [],
                    "status": "planned",
                })
        if expanded and len(steps) < 5:
            fallback_titles = [
                "Add supporting features",
                "Connect the project components",
                "Handle validation and errors",
                "Test and polish the experience",
            ]
            for idx in range(len(steps), 5):
                steps.append({
                    "id": f"step_{idx + 1}",
                    "title": fallback_titles[idx - 1],
                    "description": "Complete this part of the project and verify it works with the main user flow.",
                    "approach": "Follow the architecture plan and validate the change in the live preview.",
                    "suggested_file_paths": [],
                    "status": "planned",
                })
        return steps
    except Exception as error:
        raise AIProviderError(f"Roadmap response was invalid: {error}") from error


def ask_whats_next(vision: str, plan: dict, steps: list, completed_steps: list, selected_file: str | None, model: str, base_url: str, api_key: str) -> str:
    """Advise the user on what to do next based on roadmap progress."""
    system = (
        "You are a development coach. Given a project vision, architecture plan, "
        "current roadmap steps, and which steps are already completed, advise the user on what "
        "to do next. Be specific: name the file, describe what to implement, suggest a code "
        "approach. Return plain text (not JSON) - 2-3 sentences max."
    )
    step_details = []
    for s in steps:
        approach = s.get('approach', '')
        detail = s.get('title', '')
        if approach:
            detail += f" (Approach: {approach})"
        step_details.append(detail)
    prompt = (
        f"Project vision: {vision}\n"
        f"Architecture summary: {plan.get('summary', '') if plan else 'Active project'}\n"
        f"Completed steps: {completed_steps}\n"
        f"All steps: {step_details}\n"
        f"Currently selected file: {selected_file or 'None'}\n"
        "What is the next single best action for the user to take? Be specific and reference the approach strategy for the next step."
    )
    try:
        reply = ai_chat(
            [{"role": "system", "content": system},
             {"role": "user", "content": prompt}],
            base_url=base_url, api_key=api_key, model=model, max_tokens=300, temperature=0.3,
        )
        return reply.strip()
    except Exception as e:
        remaining = [s for s in steps if s.get("id") not in completed_steps and s.get("status") != "done"]
        if remaining:
            next_step = remaining[0]
            files_str = ", ".join(next_step.get("suggested_file_paths", [])) or "target files"
            return f"Next up: {next_step.get('title')}. Focus on implementing {files_str} as specified in your roadmap."
        return "All roadmap steps are complete! Test your application and run python preview."


def _extract_json_object(text: str) -> str:
    """Extract the first complete JSON object from an LLM response.

    OpenRouter models sometimes add a language fence or a one-line preface
    despite being asked for JSON only. This scanner respects quoted strings and
    escaped quotes, so braces within descriptions do not corrupt the plan.
    """
    text = (text or "").strip()
    start = text.find("{")
    if start < 0:
        return text
    depth = 0
    quoted = False
    escaped = False
    for index, char in enumerate(text[start:], start=start):
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
            continue
        if char == '"':
            quoted = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start:index + 1]
    return text[start:]


def extract_code_blocks(text):
    blocks = []
    cursor = 0
    while True:
        start = text.find("```", cursor)
        if start == -1:
            break
        fence_end = start + 3
        nl = text.find("\n", fence_end)
        if nl == -1:
            lang = text[fence_end:].strip() or None
            code_start = len(text)
        else:
            lang = text[fence_end:nl].strip() or None
            code_start = nl + 1
        end = text.find("```", code_start)
        if end == -1:
            break
        code = text[code_start:end].strip("\n")
        filename_hint = None
        if code:
            first_line = code.split("\n", 1)[0].strip()
            # Match explicit markers e.g. # filename: foo.py, // file: bar.ts
            m_fn = re.search(r"(?:filename|filepath|file)\s*[:=]\s*([a-zA-Z0-9_\-\./\\]+\.[a-zA-Z0-9]+)", first_line, re.I)
            if m_fn:
                filename_hint = m_fn.group(1).strip()
                code = code.split("\n", 1)[1] if "\n" in code else ""
            else:
                for marker in ("#", "//", "/*"):
                    if first_line.startswith(marker):
                        candidate = first_line.lstrip("#/* ").rstrip("*/ ").strip()
                        if candidate and "." in candidate and " " not in candidate:
                            filename_hint = candidate
                            code = code.split("\n", 1)[1] if "\n" in code else ""
                            break

        # Fallback: check text immediately preceding the fence for a filename header
        if not filename_hint and start > 0:
            preceding = text[max(0, start - 150):start].strip()
            if preceding:
                last_line = preceding.split("\n")[-1].strip()
                m_prec = re.search(r"(?:###|##|#|\*\*|`|File:?|Filename:?)\s*([a-zA-Z0-9_\-\./\\]+\.[a-zA-Z0-9]+)", last_line, re.I)
                if m_prec:
                    filename_hint = m_prec.group(1).strip("`*# ")
        blocks.append((lang, code, filename_hint))
        cursor = end + 3
    return blocks


def extract_code_block(text):
    blocks = extract_code_blocks(text)
    return blocks[0][1] if blocks else None


PATCH_RE = re.compile(
    r"(?:^[ \t]*(?:###|(?:#\s*)?(?:filename|file):)\s*(.*?)\s*\n)?^[ \t]*<<<<<<< SEARCH\s*?\n(.*?)\n[ \t]*=======\s*?\n(.*?)\n[ \t]*>>>>>>> REPLACE\s*?$",
    re.MULTILINE | re.DOTALL,
)


def extract_patch_blocks(text):
    results = []
    for m in PATCH_RE.finditer(text):
        hint = m.group(1).strip().strip("`").strip() if m.group(1) else None
        results.append((hint, m.group(2), m.group(3)))
    return results


def generate_diff_html(search: str, replace: str, filename_hint: str = None) -> str:
    fn = filename_hint or "Active File"
    removed = "".join(f'<div class="diff-line removed">{html.escape(line) or "&nbsp;"}</div>' for line in search.split("\n"))
    added = "".join(f'<div class="diff-line added">{html.escape(line) or "&nbsp;"}</div>' for line in replace.split("\n"))
    return (
        f'<div class="diff-container"><div class="diff-header"><strong>Proposed change · {html.escape(fn)}</strong></div>'
        '<div class="diff-columns"><section><span class="diff-label">Current</span>'
        f'{removed}</section><section><span class="diff-label">Proposed</span>{added}</section></div></div>'
    )


def apply_patch(root, selected_id, search, replace, filename_hint):
    target_name = filename_hint or selected_id
    if not target_name:
        return False, "No target file."
    target_path = safe_file_path(root, target_name)
    if target_path is None:
        return False, f"Invalid filename: `{target_name}`"
    if not target_path.exists():
        return False, f"File does not exist: `{target_name}`"
    try:
        current = target_path.read_text(encoding="utf-8")
    except Exception as e:
        return False, f"Could not read `{target_name}`: {e}"

    # 1. Normalize line endings
    current_norm = current.replace("\r\n", "\n")
    search_norm = search.replace("\r\n", "\n")
    replace_norm = replace.replace("\r\n", "\n")

    # Strategy A: Direct exact match
    if search_norm in current_norm:
        new_content = current_norm.replace(search_norm, replace_norm, 1)
    elif search_norm.rstrip("\n") in current_norm:
        # Strategy B: Search without trailing newline
        sn = search_norm.rstrip("\n")
        rn = replace_norm.rstrip("\n") if not replace_norm.endswith("\n") else replace_norm
        new_content = current_norm.replace(sn, rn, 1)
    else:
        # Strategy C: Line-by-line whitespace-tolerant matching
        curr_lines = current_norm.split("\n")
        search_lines = [line.rstrip() for line in search_norm.split("\n")]
        # Trim leading and trailing blank lines from search
        while search_lines and not search_lines[0]:
            search_lines.pop(0)
        while search_lines and not search_lines[-1]:
            search_lines.pop()

        matched_idx = -1
        if search_lines:
            n_search = len(search_lines)
            for i in range(len(curr_lines) - n_search + 1):
                window = [curr_lines[i + k].rstrip() for k in range(n_search)]
                if window == search_lines:
                    matched_idx = i
                    break
                # Fallback: check stripped lines (indent tolerance)
                window_stripped = [w.lstrip() for w in window]
                search_stripped = [s.lstrip() for s in search_lines]
                if window_stripped == search_stripped:
                    matched_idx = i
                    break

        if matched_idx != -1:
            replace_lines = replace_norm.split("\n")
            before = curr_lines[:matched_idx]
            after = curr_lines[matched_idx + n_search:]
            new_lines = before + replace_lines + after
            new_content = "\n".join(new_lines)
        else:
            return False, f"Search text not found in `{target_name}`"

    try:
        if "\r\n" in current and not current.startswith("\n"):
            new_content = new_content.replace("\n", "\r\n")
        target_path.write_text(new_content, encoding="utf-8")
        rel = os.path.relpath(target_path.resolve(), Path(root).resolve())
        return True, rel.replace("\\", "/")
    except Exception as e:
        return False, f"Failed to write `{target_name}`: {e}"


def run_ai_chat(
    user_prompt,
    context_path,
    context_text,
    history,
    model,
    base_url,
    api_key,
    plan=None,
    tree=None,
    project_idea="",
    include_metadata=False,
    stream_callback=None,
):
    try:
        code_change_requested = bool(
            re.search(
                r"\b(?:add|build|change|create|debug|edit|fix|implement|modify|"
                r"refactor|remove|rewrite|write)\b",
                user_prompt,
                re.IGNORECASE,
            )
        )
        response_token_budget = 3072 if code_change_requested else 1024
        file_list = []
        if tree and isinstance(tree, dict):
            for ni, info in tree.items():
                if isinstance(info, dict) and info.get("type") == "file":
                    file_list.append(info.get("path", ni))
        file_list = sorted(file_list)[:80]

        plan_summary = "No architecture summary available."
        plan_files = ""
        roadmap = ""
        if isinstance(plan, dict):
            plan_summary = plan.get("summary", plan_summary)
            plan_files = "\n".join(
                f"- `{f.get('path', f)}`: {f.get('description', '')}"
                for f in plan.get("files", [])[:30]
                if isinstance(f, dict)
            )
            roadmap = "\n".join(
                f"- {i.get('phase', 'Phase')}: {i.get('goal', '')}"
                for i in plan.get("roadmap", [])[:10]
                if isinstance(i, dict)
            )
        detailed_steps = "\n".join(
            f"- {s.get('title', '')}: {s.get('description', '')} [Approach: {s.get('approach', '')}]"
            for s in (plan.get("_steps", [])[:10] if isinstance(plan, dict) else [])
            if isinstance(s, dict)
        )

        system = {
            "role": "system", "content": (
                "You are FORGE, a helpful conversational coding partner working in the user's "
                "current project. Answer questions and discuss ideas naturally and concisely. "
                "Do not output code or claim to edit files unless the user asks for a code change. "
                "When asked to implement a change, return one complete file in a fenced code block, "
                "with `# filename: relative/path` as its first line; prefer the selected file and "
                "make the smallest complete change. Explain briefly what changed. Never claim a "
                "file was saved: the user applies generated changes in the chat UI. Use the recent "
                "conversation and supplied workspace context; do not ask for details already provided.\n\n"
                f"Project Vision: {project_idea or 'Not provided'}\n\n"
                f"Architecture Summary: {plan_summary}\n\n"
                f"Planned Architecture Files:\n{plan_files or 'None'}\n\n"
                f"Roadmap:\n{roadmap or 'None'}\n"
                f"Detailed Development Steps:\n{detailed_steps or 'None (no detailed steps provided)'}\n\n"
                f"Current Workspace Files on Disk:\n" + (
                    "\n".join(f"- `{p}`" for p in file_list) if file_list else "No files created on disk yet."
                ) + "\n\n"
                f"--- Active Inspected File: {context_path} ---\n{context_text or '(Empty or no file selected)'}\n--- End Active File ---"
            ),
        }
        clean_history = []
        for message in (history or [])[-8:]:
            if not (
                isinstance(message, dict)
                and message.get("role") in {"user", "assistant"}
                and isinstance(message.get("content"), str)
            ):
                continue
            content = message["content"]
            if message["role"] == "assistant":
                content = re.sub(
                    r"```[\s\S]*?```",
                    "[previous generated code omitted; use the current workspace file]",
                    content,
                )
            clean_history.append({
                "role": message["role"],
                "content": content[-2000:],
            })
        messages = [system] + clean_history + [{"role": "user", "content": user_prompt}]
        return ai_chat(
            messages, base_url=base_url, api_key=api_key, model=model,
            max_tokens=response_token_budget,
            temperature=0.2,
            include_metadata=include_metadata,
            stream_callback=stream_callback,
        )
    except AIProviderError:
        raise
    except Exception as e:
        raise AIProviderError(f"Unexpected error generating response: {e}") from e


def generate_file_content(filename, prompt, model, base_url, api_key):
    system = (
        "You are an expert code generator. Produce clean, complete, robust, runnable file content. "
        "Do not omit any code. Return the code inside one fenced markdown block with the filename marker."
    )
    user = f"Create the complete runnable file named `{filename}`.\n\nRequirements:\n{prompt}"
    try:
        return ai_chat(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            base_url=base_url, api_key=api_key, model=model, max_tokens=4096,
        )
    except AIProviderError as e:
        raise AIProviderError(f"File generation failed: {e}", status_code=e.status_code) from e
    except Exception as e:
        raise AIProviderError(f"File generation failed: {e}") from e
