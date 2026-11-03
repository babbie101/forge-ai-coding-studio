import os
os.environ["STREAMLIT_TEST_MODE"] = "1"
from pathlib import Path
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

from app import (
    _build_chat_context,
    _get_provider_config,
    _model_for_provider,
    _resolve_provider,
    _should_auto_select_ollama,
    apply_ai_response,
    scaffold_project,
)
from core.ai import (
    AIProviderError,
    _ai_providers,
    _extract_json_object,
    ai_chat,
    extract_code_blocks,
    extract_patch_blocks,
    generate_roadmap,
)
from core.state import DEFAULTS
from core.workspace_progress import load_project_progress, save_project_progress
from services.files import (
    build_preview_tree, get_file_path, scan_tree, export_context_md,
    save_workspace_file,
)
from services.executor import (
    detect_workspace_preview_type, get_static_preview_url, is_streamlit_app,
    run_python_preview, start_streamlit_preview, _streamlit_processes,
    _stop_streamlit_preview,
)
from utils.helpers import safe_file_path


APP_FILE = Path(__file__).resolve().parents[1] / "app.py"


@pytest.fixture(autouse=True)
def configure_test_provider(monkeypatch):
    monkeypatch.setenv("NEBIUS_API_KEY", "test-provider-key")


def test_safe_file_path_blocks_path_escape(tmp_path: Path):
    assert safe_file_path(str(tmp_path), "src/main.py") == tmp_path / "src" / "main.py"
    assert safe_file_path(str(tmp_path), "../outside.py") is None
    assert safe_file_path(str(tmp_path), "C:/outside.py") is None
    assert safe_file_path(str(tmp_path), r"C:\\Projects\\outside.py") is None


def test_get_file_path_blocks_path_escape(tmp_path: Path):
    try:
        get_file_path(str(tmp_path), {"path": "../outside.py"})
    except ValueError:
        pass
    else:
        raise AssertionError("Expected an invalid workspace path to be rejected")


def test_scan_tree_includes_max_depth_files_and_prunes_deeper_directories(tmp_path: Path):
    (tmp_path / "one" / "two").mkdir(parents=True)
    (tmp_path / "one" / "two" / "visible.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "one" / "two" / "three").mkdir()
    (tmp_path / "one" / "two" / "three" / "hidden.py").write_text("x = 2\n", encoding="utf-8")
    tree = scan_tree(str(tmp_path), max_depth=2)
    assert "one/two/visible.py" in tree
    assert "one/two/three" not in tree


def test_scan_tree_cache_invalidates_after_workspace_write(tmp_path: Path):
    from services.files import invalidate_scan_tree

    assert "new.py" not in scan_tree(str(tmp_path))
    (tmp_path / "new.py").write_text("print('fresh')\n", encoding="utf-8")
    invalidate_scan_tree(str(tmp_path))

    assert "new.py" in scan_tree(str(tmp_path))


def test_preview_tree_patch_extractors_and_scaffold(tmp_path: Path):
    plan = {
        "summary": "Test workspace",
        "folders": ["src"],
        "files": [{"path": "src/main.py", "description": "Entry point"}],
    }
    assert "src/main.py" in build_preview_tree(plan)
    assert extract_code_blocks("```python\n# filename: demo.py\nprint('ok')\n```")[0][2] == "demo.py"
    assert extract_patch_blocks("# filename: demo.py\n<<<<<<< SEARCH\na\n=======\nb\n>>>>>>> REPLACE")
    scaffold_project(str(tmp_path), plan, "A test application")
    assert (tmp_path / "src" / "main.py").exists()


def test_scaffold_project_rejects_escaping_folders(tmp_path: Path):
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    plan = {"folders": ["../" + outside.name], "files": []}
    scaffold_project(str(tmp_path), plan)
    assert not outside.exists()


def test_scaffold_project_does_not_overwrite_existing_files(tmp_path: Path):
    existing = tmp_path / "src" / "main.py"
    existing.parent.mkdir()
    existing.write_text("keep this file\n", encoding="utf-8")
    plan = {
        "summary": "Test workspace",
        "folders": ["src"],
        "files": [
            {"path": "new.py", "description": "New file"},
            {"path": "src/main.py", "description": "Entry point"},
        ],
    }

    try:
        scaffold_project(str(tmp_path), plan)
    except FileExistsError as error:
        assert "src/main.py" in str(error)
    else:
        raise AssertionError("Expected scaffolding to reject existing output files")

    assert existing.read_text(encoding="utf-8") == "keep this file\n"
    assert not (tmp_path / "new.py").exists()
    assert not (tmp_path / "PROJECT_PLAN.md").exists()


def test_chat_history_drops_internal_metadata():
    from core.ai import run_ai_chat

    history = [
        {"role": "assistant", "content": "Previous answer", "metadata": {"total_tokens": 12}},
        {"role": "user", "content": "Previous question", "metadata": {"private": True}},
        {"role": "tool", "content": "Ignored tool message"},
    ]
    with patch("core.ai.ai_chat", return_value="reply") as mocked_ai_chat:
        run_ai_chat("next question", "app.py", "", history, "model", "url", "key")

    sent_messages = mocked_ai_chat.call_args.args[0]
    assert sent_messages[1:] == [
        {"role": "assistant", "content": "Previous answer"},
        {"role": "user", "content": "Previous question"},
        {"role": "user", "content": "next question"},
    ]


def test_chat_history_is_bounded_and_prior_code_is_not_repeated():
    from core.ai import run_ai_chat

    history = [
        {"role": "user", "content": f"question {index}"}
        for index in range(12)
    ]
    history.append({
        "role": "assistant",
        "content": "Implemented:\n```python\n" + ("x = 1\n" * 1000) + "```",
    })
    with patch("core.ai.ai_chat", return_value="reply") as mocked_ai_chat:
        run_ai_chat("follow up", "app.py", "current file contents", history, "model", "url", "key")

    sent_messages = mocked_ai_chat.call_args.args[0]
    sent_history = sent_messages[1:-1]
    assert len(sent_history) == 8
    assert sent_history[-1]["content"] == (
        "Implemented:\n[previous generated code omitted; use the current workspace file]"
    )
    assert sent_messages[0]["content"].startswith(
        "You are FORGE, a helpful conversational coding partner"
    )


def test_chat_context_includes_selected_file_and_project_docs_only(tmp_path: Path):
    (tmp_path / "README.md").write_text("Project overview", encoding="utf-8")
    (tmp_path / "app.py").write_text("print('selected')", encoding="utf-8")
    (tmp_path / "unrelated.py").write_text("SECRET_CONTEXT", encoding="utf-8")
    tree = {
        "README.md": {"type": "file", "path": "README.md"},
        "app.py": {"type": "file", "path": "app.py"},
        "unrelated.py": {"type": "file", "path": "unrelated.py"},
    }

    context = _build_chat_context(str(tmp_path), tree, "app.py")

    assert "print('selected')" in context
    assert "Project overview" in context
    assert "SECRET_CONTEXT" not in context


def test_apply_ai_response_writes_generated_file(tmp_path: Path):
    result = apply_ai_response(
        str(tmp_path),
        None,
        "```python\n# filename: src/main.py\nprint('applied')\n```",
    )

    assert result["type"] == "success"
    assert (tmp_path / "src" / "main.py").read_text(encoding="utf-8") == "print('applied')"


def test_ai_chat_streams_content_and_returns_metadata():
    from types import SimpleNamespace

    chunks = [
        SimpleNamespace(
            model="test-model",
            choices=[SimpleNamespace(delta=SimpleNamespace(content=content))],
        )
        for content in ("Hello", " there")
    ]
    client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=lambda **_kwargs: iter(chunks))
        )
    )
    received = []
    with patch("core.ai._get_openai_client", return_value=client):
        reply, metadata = ai_chat(
            [{"role": "user", "content": "hello"}],
            "https://example.test/v1/",
            "test-key",
            "test-model",
            include_metadata=True,
            stream_callback=received.append,
        )

    assert reply == "Hello there"
    assert received == ["Hello", " there"]
    assert metadata["model"] == "test-model"


def test_ai_chat_rejects_empty_response():
    from types import SimpleNamespace

    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="  "))],
        model="test-model",
        usage=None,
    )
    client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=lambda **_kwargs: response)
        )
    )
    with patch("core.ai._get_openai_client", return_value=client):
        try:
            ai_chat(
                [{"role": "user", "content": "hello"}],
                "https://example.test/v1/",
                "test-key",
                "test-model",
            )
        except AIProviderError as error:
            assert "empty response" in str(error)
        else:
            raise AssertionError("Expected an empty completion to be rejected")


def test_openai_client_reuses_connection_pool():
    from types import SimpleNamespace
    from core.ai import _get_openai_client

    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="reply"))],
        model="test-model",
        usage=None,
    )
    client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=lambda **_kwargs: response)
        )
    )
    _get_openai_client.clear()
    try:
        with patch("core.ai.OpenAI", return_value=client) as openai_factory:
            ai_chat(
                [{"role": "user", "content": "first"}],
                "https://example.test/v1/",
                "reuse-test-key",
                "test-model",
            )
            ai_chat(
                [{"role": "user", "content": "second"}],
                "https://example.test/v1/",
                "reuse-test-key",
                "test-model",
            )

        assert openai_factory.call_count == 1
    finally:
        _get_openai_client.clear()


def test_architecture_plan_default_is_none():
    assert DEFAULTS.get("architecture_plan") is None


def test_project_roadmap_progress_round_trips_atomically(tmp_path: Path):
    progress = {
        "project_idea": "A recipe finder",
        "architecture_plan": {"summary": "Recipe finder", "files": [{"path": "app.py"}]},
        "plan_steps": [
            {"id": "step_1", "title": "Create search", "status": "done"},
            {"id": "step_2", "title": "Show results", "status": "planned"},
        ],
        "short_plan_steps": [{"id": "step_1", "title": "Search", "status": "planned"}],
        "roadmap_expanded": True,
        "current_step_id": "step_2",
        "plan_scaffolded": True,
        "plan_status": "in_progress",
    }

    save_project_progress(tmp_path, progress)

    saved_file = tmp_path / ".forge" / "roadmap.json"
    assert saved_file.exists()
    assert load_project_progress(tmp_path) == {**progress, "version": 1}
    assert not list(saved_file.parent.glob(".roadmap-*.tmp"))


def test_project_roadmap_progress_rejects_malformed_data(tmp_path: Path):
    progress_file = tmp_path / ".forge" / "roadmap.json"
    progress_file.parent.mkdir()
    progress_file.write_text('{"version": 1, "plan_steps": [null]}', encoding="utf-8")

    try:
        load_project_progress(tmp_path)
    except ValueError as error:
        assert "steps" in str(error)
    else:
        raise AssertionError("Expected malformed roadmap steps to be rejected")


def test_no_provider_is_selected_without_a_configured_key(monkeypatch):
    for variable in ("OPENROUTER_API_KEY", "NEBIUS_API_KEY", "GROQ_API_KEY", "OLLAMA_API_KEY"):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.delenv("FORGE_AI_PROVIDER", raising=False)
    monkeypatch.setattr("app._ollama_is_running", lambda: False)
    assert _resolve_provider() is None


def test_explicit_ollama_preference_avoids_cloud_providers(monkeypatch):
    monkeypatch.setenv("FORGE_AI_PROVIDER", "ollama")
    monkeypatch.setenv("NEBIUS_API_KEY", "nb-test-token")
    monkeypatch.setenv("OPENROUTER_API_KEY", "openrouter-test-token")
    monkeypatch.setattr("app._ollama_is_running", lambda: False)

    assert _resolve_provider() == "ollama"


def test_explicit_nebius_preference_can_be_restored(monkeypatch):
    monkeypatch.setenv("FORGE_AI_PROVIDER", "nebius")
    monkeypatch.setenv("NEBIUS_API_KEY", "nb-test-token")
    monkeypatch.setattr("app._ollama_is_running", lambda: True)

    assert _resolve_provider() == "nebius"


def test_explicit_provider_preference_is_not_overridden_by_ollama(monkeypatch):
    monkeypatch.setenv("FORGE_AI_PROVIDER", "nebius")
    monkeypatch.setattr("app._ollama_is_running", lambda: True)

    assert not _should_auto_select_ollama(None)


def test_ollama_can_still_be_auto_selected_without_explicit_provider(monkeypatch):
    monkeypatch.delenv("FORGE_AI_PROVIDER", raising=False)
    monkeypatch.setattr("app._ollama_is_running", lambda: True)

    assert _should_auto_select_ollama(None)


def test_running_ollama_is_preferred_over_cloud_keys(monkeypatch):
    monkeypatch.delenv("FORGE_AI_PROVIDER", raising=False)
    monkeypatch.setenv("NEBIUS_API_KEY", "nb-test-token")
    monkeypatch.setenv("GROQ_API_KEY", "gsk-test-token")
    monkeypatch.setattr("app._ollama_is_running", lambda: True)

    assert _resolve_provider() == "ollama"


def test_nebius_provider_autodetects_configured_token(monkeypatch):
    for variable in ("OPENROUTER_API_KEY", "GROQ_API_KEY", "OLLAMA_API_KEY"):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.delenv("FORGE_AI_PROVIDER", raising=False)
    monkeypatch.setattr("app._ollama_is_running", lambda: False)
    monkeypatch.setenv("NEBIUS_API_KEY", "test-token")
    assert _resolve_provider() == "nebius"


def test_nebius_models_and_openai_compatible_endpoint_are_configured():
    nebius = _ai_providers["nebius"]
    assert nebius["base_url"] == "https://api.tokenfactory.nebius.com/v1/"
    assert nebius["models"] == {
        "Nemotron 3 Nano 30B": "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B",
    }


def test_openrouter_uses_only_free_models():
    models = _ai_providers["openrouter"]["models"].values()
    assert models
    assert all(model.endswith(":free") for model in models)


def test_ollama_config_uses_models_discovered_from_the_local_server(monkeypatch):
    monkeypatch.setattr("app._get_active_provider", lambda: "ollama")
    monkeypatch.setattr("app.list_available_ollama_models", lambda: ["qwen2.5-coder:7b"])
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    config = _get_provider_config()
    assert config["api_key"] == "ollama-local"
    assert config["models"] == {"qwen2.5-coder:7b": "qwen2.5-coder:7b"}
    assert config["default_model"] == "qwen2.5-coder:7b"


def test_saved_model_is_reset_when_switching_providers():
    ollama_config = {
        "models": {"qwen3.5:4b": "qwen3.5:4b"},
        "default_model": "qwen3.5:4b",
    }

    assert _model_for_provider("old-nebius-model", ollama_config) == "qwen3.5:4b"
    assert _model_for_provider("qwen3.5:4b", ollama_config) == "qwen3.5:4b"


def test_ollama_qwen_chat_disables_thinking_and_returns_usage(monkeypatch):
    import io
    import json

    from core.ai import ai_chat

    response = {
        "model": "qwen3.5:4b",
        "message": {"role": "assistant", "content": "LOCAL OLLAMA READY"},
        "prompt_eval_count": 12,
        "eval_count": 5,
    }
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434/v1/")
    with patch("core.ai.urlopen", return_value=io.BytesIO(json.dumps(response).encode())) as opened:
        content, metadata = ai_chat(
            [{"role": "user", "content": "Reply with a short message."}],
            "http://localhost:11434/v1/",
            "ollama-local",
            "qwen3.5:4b",
            max_tokens=128,
            include_metadata=True,
        )

    request = opened.call_args.args[0]
    body = json.loads(request.data)
    assert request.full_url == "http://localhost:11434/api/chat"
    assert body["think"] is False
    assert body["options"]["num_predict"] == 128
    assert content == "LOCAL OLLAMA READY"
    assert metadata["total_tokens"] == 17


def test_ollama_chat_streams_tokens_as_they_arrive(monkeypatch):
    import io
    import json

    chunks = [
        {"message": {"content": "Hello"}, "done": False},
        {"message": {"content": " there"}, "done": False},
        {
            "message": {"content": ""},
            "done": True,
            "model": "qwen3.5:4b",
            "prompt_eval_count": 8,
            "eval_count": 2,
        },
    ]
    response_body = "\n".join(json.dumps(chunk) for chunk in chunks).encode("utf-8")
    received = []
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434/v1/")
    with patch("core.ai.urlopen", return_value=io.BytesIO(response_body)) as opened:
        content, metadata = ai_chat(
            [{"role": "user", "content": "Say hello"}],
            "http://localhost:11434/v1/",
            "ollama-local",
            "qwen3.5:4b",
            include_metadata=True,
            stream_callback=received.append,
        )

    request_payload = json.loads(opened.call_args.args[0].data)
    assert request_payload["stream"] is True
    assert received == ["Hello", " there"]
    assert content == "Hello there"
    assert metadata["total_tokens"] == 10


def test_chat_uses_smaller_budget_for_conversation_and_full_budget_for_code():
    from core.ai import run_ai_chat

    with patch("core.ai.ai_chat", return_value="reply") as mocked_ai_chat:
        run_ai_chat("What does this project do?", "app.py", "", [], "model", "url", "key")
        run_ai_chat("Add a health endpoint", "app.py", "", [], "model", "url", "key")

    assert [
        call.kwargs["max_tokens"] for call in mocked_ai_chat.call_args_list
    ] == [1024, 3072]


def test_architecture_json_extraction_accepts_fences_and_a_preface():
    raw = 'Here is your plan:\n```json\n{"summary":"A {small} app","folders":[]}\n```\n'
    assert _extract_json_object(raw) == '{"summary":"A {small} app","folders":[]}'


def test_generate_roadmap_returns_three_short_steps_and_expanded_steps():
    short_response = '{"steps":[{"title":"Build the core feature","description":"Create the primary flow."}]}'
    detailed_response = '{"steps":[' + ",".join(
        f'{{"title":"Task {index}","description":"Implement task {index}."}}'
        for index in range(1, 7)
    ) + ']}'
    with patch("core.ai.ai_chat", side_effect=[short_response, detailed_response]) as ai_chat:
        short_steps = generate_roadmap(
            "A recipe planner", {"files": []}, "test-model", "", ""
        )
        detailed_steps = generate_roadmap(
            "A recipe planner", {"files": []}, "test-model", "", "", expanded=True
        )

    assert len(short_steps) == 3
    assert len(detailed_steps) == 6
    assert [call.kwargs["max_tokens"] for call in ai_chat.call_args_list] == [900, 2000]


def test_python_preview_captures_workspace_output(tmp_path: Path):
    script = tmp_path / "hello.py"
    script.write_text("print('canvas ready')\n", encoding="utf-8")
    stdout, stderr = run_python_preview(script)
    assert "canvas ready" in stdout
    assert not stderr


def test_python_preview_reports_timeout(tmp_path: Path):
    script = tmp_path / "slow.py"
    script.write_text("import time\ntime.sleep(2)\n", encoding="utf-8")
    stdout, stderr = run_python_preview(script, timeout=0.1)
    assert not stdout
    assert "timed out after 0.1 seconds" in stderr


def test_static_preview_serves_project_assets_but_not_code_or_hidden_files(tmp_path: Path):
    import urllib.error
    import urllib.request

    (tmp_path / "index.html").write_text(
        '<link rel="stylesheet" href="assets/site.css"><h1>Preview</h1>',
        encoding="utf-8",
    )
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "site.css").write_text("h1 { color: blue; }", encoding="utf-8")
    (tmp_path / "app.py").write_text("print('private source')", encoding="utf-8")
    (tmp_path / ".env").write_text("PRIVATE_VALUE", encoding="utf-8")

    url = get_static_preview_url(tmp_path, "index.html")
    assert url is not None
    with urllib.request.urlopen(url, timeout=3) as response:
        assert "Preview" in response.read().decode("utf-8")
    with urllib.request.urlopen(url.replace("index.html", "assets/site.css"), timeout=3) as response:
        assert "color: blue" in response.read().decode("utf-8")
    for private_path in ("app.py", ".env"):
        try:
            urllib.request.urlopen(url.replace("index.html", private_path), timeout=3)
        except urllib.error.HTTPError as error:
            assert error.code == 404
        else:
            raise AssertionError(f"Static preview exposed {private_path}")


def test_streamlit_preview_starts_loopback_server_for_streamlit_entry(tmp_path: Path):
    from unittest.mock import MagicMock

    script = tmp_path / "src" / "app.py"
    script.parent.mkdir()
    script.write_text("import streamlit as st\nst.title('Preview')\n", encoding="utf-8")
    process = MagicMock()
    process.poll.return_value = None
    response = MagicMock()
    response.__enter__.return_value.status = 200
    try:
        with patch("services.executor.subprocess.Popen", return_value=process) as popen, patch(
            "services.executor.urlopen", return_value=response
        ):
            url, error = start_streamlit_preview(
                script, timeout=1, working_directory=tmp_path
            )

        assert error is None
        assert url.startswith("http://127.0.0.1:")
        assert is_streamlit_app(script)
        command = popen.call_args.args[0]
        assert popen.call_args.kwargs["cwd"] == str(tmp_path.resolve())
        assert command[command.index("--server.address") + 1] == "127.0.0.1"
        assert command[command.index("--server.port") + 1].isdigit()
    finally:
        preview = _streamlit_processes.pop(str(script.resolve()), None)
        if preview:
            _stop_streamlit_preview(preview)


def test_save_workspace_file_is_atomic_and_rejects_escape(tmp_path: Path):
    saved = save_workspace_file(tmp_path, "src/main.py", "print('saved')\n")
    assert saved.read_text(encoding="utf-8") == "print('saved')\n"
    assert not list(saved.parent.glob(".*.tmp"))
    try:
        save_workspace_file(tmp_path, "../outside.py", "not saved")
    except ValueError:
        pass
    else:
        raise AssertionError("Expected workspace saves to reject paths outside the workspace")


def test_preview_detects_explicit_nested_file(tmp_path: Path):
    nested_html = tmp_path / "web" / "index.html"
    nested_html.parent.mkdir()
    nested_html.write_text("<h1>Preview</h1>", encoding="utf-8")
    info = detect_workspace_preview_type(str(tmp_path), "web/index.html")
    assert info["type"] == "web"
    assert info["entry_file"] == "web/index.html"
    assert info["entry_path"] == nested_html


def test_workspace_renders_local_html_preview(tmp_path: Path):
    (tmp_path / "index.html").write_text("<h1>Preview</h1>", encoding="utf-8")
    with patch("app._active_provider", return_value={
        "provider": None, "api_key": None, "base_url": None,
        "default_model": None, "label": "No AI provider configured", "models": {},
    }):
        at = AppTest.from_file(str(APP_FILE), default_timeout=30)
        at.session_state["app_stage"] = "workspace"
        at.session_state["target_dir"] = str(tmp_path)
        at.session_state["plan_scaffolded"] = True
        at.session_state["workspace_section"] = "Code"
        at.run()

    assert not at.exception


def test_home_opens_existing_workspace(tmp_path: Path):
    at = AppTest.from_file(str(APP_FILE), default_timeout=30).run()
    assert not at.exception
    assert not any(
        button.key and button.key.startswith("provider_")
        for button in at.button
    )
    assert all("AI Provider" not in element.value for element in at.markdown)
    at.text_input(key="existing_path_input").set_value(str(tmp_path))
    at.button(key="open_existing").click().run()
    assert at.session_state["app_stage"] == "workspace"
    assert not at.exception


def test_home_template_fills_project_brief():
    at = AppTest.from_file(str(APP_FILE), default_timeout=30).run()
    at.pills(key="home_template_choice").set_value("Streamlit app").run()

    assert at.text_area(key="project_idea_input").value == (
        "A polished Streamlit app with a clear workflow, responsive layout, "
        "and useful interactive controls."
    )
    assert not at.exception


def test_new_workspace_rejects_traversal_and_existing_folder(tmp_path: Path):
    existing_workspace = tmp_path / "existing"
    existing_workspace.mkdir()
    existing_file = existing_workspace / "keep.txt"
    existing_file.write_text("unchanged", encoding="utf-8")

    at = AppTest.from_file(str(APP_FILE), default_timeout=30).run()
    at.text_input(key="new_parent_input").set_value(str(tmp_path))
    at.text_input(key="new_workspace_name").set_value("..")
    at.text_area(key="project_idea_input").set_value("Test project")
    at.button(key="plan_from_home").click().run()
    assert at.session_state["app_stage"] == "home"
    assert at.error
    assert not at.exception

    at.text_input(key="new_workspace_name").set_value("existing")
    at.button(key="quick_build_from_home").click().run()
    assert at.session_state["app_stage"] == "home"
    assert existing_file.read_text(encoding="utf-8") == "unchanged"
    assert not at.exception


def test_new_workspace_opens_the_live_workspace(tmp_path: Path):
    fake_plan = {
        "summary": "Test workspace",
        "folders": ["src"],
        "files": [{"path": "src/main.py", "description": "Entry point"}],
        "roadmap": [],
        "dependencies": [],
        "run_checklist": [],
    }
    fake_steps = [
        {
            "id": "step_1",
            "title": "Implement src/main.py",
            "description": "Create and test src/main.py",
            "approach": "Implement the file as specified in the architecture plan.",
            "suggested_file_paths": ["src/main.py"],
            "status": "planned"
        }
    ]
    with patch("core.ai.generate_architecture", return_value=fake_plan), patch(
        "app.generate_architecture", return_value=fake_plan
    ), patch("core.ai.generate_roadmap", return_value=fake_steps), patch(
        "app.generate_roadmap", return_value=fake_steps
    ):
        at = AppTest.from_file(str(APP_FILE), default_timeout=30).run()
        at.text_input(key="new_parent_input").set_value(str(tmp_path))
        at.text_input(key="new_workspace_name").set_value("project-planner")
        at.text_area(key="project_idea_input").set_value("A local project planning dashboard")
        at.button(key="plan_from_home").click().run()
    assert at.session_state["app_stage"] == "workspace"
    assert at.session_state["project_idea"] == "A local project planning dashboard"
    assert at.session_state["short_plan_steps"] == fake_steps
    assert at.session_state["roadmap_expanded"] is False
    assert (tmp_path / "project-planner").is_dir()
    assert load_project_progress(tmp_path / "project-planner")["plan_steps"] == fake_steps
    assert not at.exception


def test_empty_workspace_can_be_created_and_edited_without_ai(tmp_path: Path):
    with patch("app._active_provider", return_value={
        "provider": None, "api_key": None, "base_url": None,
        "default_model": None, "label": "No AI provider configured", "models": {},
    }):
        at = AppTest.from_file(str(APP_FILE), default_timeout=30).run()
        at.text_input(key="new_parent_input").set_value(str(tmp_path))
        at.text_input(key="new_workspace_name").set_value("manual-project")
        at.button(key="empty_workspace_from_home").click().run()

        assert at.session_state["app_stage"] == "workspace"
        assert at.session_state["architecture_plan"] is None
        assert at.session_state["plan_steps"] == []
        assert at.session_state["workspace_section"] == "Code"
        assert not at.exception

        at.text_input(key="new_workspace_file_name").set_value("index.html")
        at.button(key="add_workspace_file").click().run()

    created_file = tmp_path / "manual-project" / "index.html"
    assert created_file.exists()
    assert "<h1>It works</h1>" in created_file.read_text(encoding="utf-8")
    assert at.session_state["selected_id"] == "index.html"
    assert not at.exception


def test_empty_workspace_offers_starter_files(tmp_path: Path):
    with patch("app._active_provider", return_value={
        "provider": None, "api_key": None, "base_url": None,
        "default_model": None, "label": "No AI provider configured", "models": {},
    }):
        at = AppTest.from_file(str(APP_FILE), default_timeout=30)
        at.session_state["app_stage"] = "workspace"
        at.session_state["target_dir"] = str(tmp_path)
        at.session_state["plan_scaffolded"] = True
        at.session_state["workspace_section"] = "Code"
        at.run()
        at.button(key="starter_file_web").click().run()

    starter = tmp_path / "index.html"
    assert starter.exists()
    assert "Try an interaction" in starter.read_text(encoding="utf-8")
    assert at.session_state["selected_id"] == "index.html"
    assert not at.exception


def test_workspace_restores_saved_roadmap_and_selected_step(tmp_path: Path):
    steps = [
        {"id": "step_1", "title": "Plan interface", "description": "Sketch the page.", "status": "done"},
        {"id": "step_2", "title": "Build search", "description": "Add recipe search.", "status": "planned"},
    ]
    save_project_progress(tmp_path, {
        "project_idea": "A recipe finder",
        "architecture_plan": {"summary": "Recipe finder", "files": [{"path": "index.html"}]},
        "plan_steps": steps,
        "short_plan_steps": [steps[0]],
        "roadmap_expanded": True,
        "current_step_id": "step_2",
        "plan_scaffolded": True,
        "plan_status": "in_progress",
    })
    with patch("app._active_provider", return_value={
        "provider": None, "api_key": None, "base_url": None,
        "default_model": None, "label": "No AI provider configured", "models": {},
    }):
        at = AppTest.from_file(str(APP_FILE), default_timeout=30)
        at.session_state["app_stage"] = "workspace"
        at.session_state["target_dir"] = str(tmp_path)
        at.session_state["plan_scaffolded"] = True
        at.run()

    assert at.session_state["project_idea"] == "A recipe finder"
    assert at.session_state["plan_steps"] == steps
    assert at.session_state["current_step"]["id"] == "step_2"
    assert at.session_state["roadmap_expanded"] is True
    assert not at.exception


def test_completing_roadmap_step_persists_and_advances(tmp_path: Path):
    steps = [
        {"id": "step_1", "title": "Plan interface", "description": "Sketch the page.", "status": "planned"},
        {"id": "step_2", "title": "Build search", "description": "Add recipe search.", "status": "planned"},
    ]
    save_project_progress(tmp_path, {
        "project_idea": "A recipe finder",
        "architecture_plan": {"summary": "Recipe finder", "files": []},
        "plan_steps": steps,
        "short_plan_steps": steps,
        "roadmap_expanded": False,
        "current_step_id": "step_1",
        "plan_scaffolded": True,
        "plan_status": "in_progress",
    })
    with patch("app._active_provider", return_value={
        "provider": "nebius", "api_key": "nb-fake", "base_url": "https://api.tokenfactory.nebius.com/v1/",
        "default_model": "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B", "label": "FORGE", "models": {},
    }):
        at = AppTest.from_file(str(APP_FILE), default_timeout=30)
        at.session_state["app_stage"] = "workspace"
        at.session_state["target_dir"] = str(tmp_path)
        at.session_state["plan_scaffolded"] = True
        at.run()
        at.button(key="toggle_roadmap_step_done").click().run()

    saved = load_project_progress(tmp_path)
    assert saved["plan_steps"][0]["status"] == "done"
    assert saved["current_step_id"] == "step_2"
    assert at.session_state["current_step"]["id"] == "step_2"
    assert load_project_progress(tmp_path)["current_step_id"] == "step_2"
    assert not at.exception


def test_workspace_skips_legacy_scaffold_preview(tmp_path: Path):
    fake_steps = [
        {
            "id": "step_1",
            "title": "Implement src/main.py",
            "description": "Create and test src/main.py",
            "approach": "Implement the file as specified in the architecture plan.",
            "suggested_file_paths": ["src/main.py"],
            "status": "planned"
        }
    ]
    with patch("core.ai.generate_roadmap", return_value=fake_steps), patch(
        "app.generate_roadmap", return_value=fake_steps
    ):
        at = AppTest.from_file(str(APP_FILE), default_timeout=30)
        at.session_state["app_stage"] = "workspace"
        at.session_state["target_dir"] = str(tmp_path)
        at.session_state["architecture_plan"] = {
            "summary": "Test project",
            "folders": ["src"],
            "files": [{"path": "src/main.py", "description": "Application entry point"}],
        }
        at.session_state["plan_scaffolded"] = False
        at.session_state["roadmap_loaded_for"] = str(tmp_path.resolve())
        at.run()
    assert not at.exception
    assert all(button.key != "scaffold" for button in at.button)


def test_plan_review_can_expand_roadmap(tmp_path: Path):
    short_steps = [
        {"id": "step_1", "title": "Set up", "description": "Set up the project.", "status": "planned"},
        {"id": "step_2", "title": "Build", "description": "Build the core feature.", "status": "planned"},
        {"id": "step_3", "title": "Polish", "description": "Test and polish.", "status": "planned"},
    ]
    detailed_steps = [
        {"id": f"step_{index}", "title": f"Task {index}", "description": "A coding task.", "status": "planned"}
        for index in range(1, 6)
    ]
    plan = {
        "summary": "A test project",
        "files": [{"path": "app.py", "description": "Entry point"}],
    }
    save_project_progress(tmp_path, {
        "project_idea": "A project for organizing recipes",
        "architecture_plan": plan,
        "plan_steps": short_steps,
        "short_plan_steps": short_steps,
        "roadmap_expanded": False,
        "current_step_id": "step_1",
        "plan_scaffolded": False,
        "plan_status": "review",
    })
    with patch("app._active_provider", return_value={
        "provider": "nebius", "api_key": "nb-fake", "base_url": "https://api.tokenfactory.nebius.com/v1/",
        "default_model": "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B", "label": "Nebius AI", "models": {}
    }), patch("core.ai.generate_roadmap", return_value=detailed_steps), patch(
        "app.generate_roadmap", return_value=detailed_steps
    ):
        at = AppTest.from_file(str(APP_FILE), default_timeout=30)
        at.session_state["app_stage"] = "workspace"
        at.session_state["target_dir"] = str(tmp_path)
        at.session_state["architecture_plan"] = plan
        at.session_state["plan_scaffolded"] = False
        at.session_state["project_idea"] = "A project for organizing recipes"
        at.session_state["plan_steps"] = short_steps
        at.session_state["short_plan_steps"] = short_steps
        at.run()
        next(button for button in at.button if button.key == "expand_roadmap_btn").click().run()

    assert at.session_state["plan_steps"] == detailed_steps
    assert at.session_state["roadmap_expanded"] is True
    assert not at.exception


def test_plan_review_can_select_a_roadmap_step(tmp_path: Path):
    steps = [
        {"id": "step_1", "title": "Set up", "description": "Set up the project.", "status": "planned"},
        {"id": "step_2", "title": "Build search", "description": "Add the main search flow.", "status": "planned"},
        {"id": "step_3", "title": "Polish", "description": "Test and polish.", "status": "planned"},
    ]
    plan = {
        "summary": "A recipe finder",
        "files": [{"path": "index.html", "description": "Main interface"}],
    }
    save_project_progress(tmp_path, {
        "project_idea": "A recipe finder",
        "architecture_plan": plan,
        "plan_steps": steps,
        "short_plan_steps": steps,
        "roadmap_expanded": False,
        "current_step_id": "step_1",
        "plan_scaffolded": False,
        "plan_status": "review",
    })
    with patch("app._active_provider", return_value={
        "provider": "nebius", "api_key": "nb-fake", "base_url": "https://api.tokenfactory.nebius.com/v1/",
        "default_model": "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B", "label": "Nebius AI", "models": {}
    }):
        at = AppTest.from_file(str(APP_FILE), default_timeout=30)
        at.session_state["app_stage"] = "workspace"
        at.session_state["target_dir"] = str(tmp_path)
        at.session_state["architecture_plan"] = plan
        at.session_state["plan_scaffolded"] = False
        at.session_state["project_idea"] = "A recipe finder"
        at.session_state["plan_steps"] = steps
        at.session_state["short_plan_steps"] = steps
        at.session_state["current_step"] = steps[0]
        at.run()
        next(button for button in at.button if button.key == "choose_roadmap_step_step_2_1").click().run()

    assert at.session_state["current_step"]["id"] == "step_2"
    assert not at.exception


def test_quick_build_autorun(tmp_path: Path):
    fake_plan = {
        "summary": "Quick Build test",
        "folders": ["src"],
        "files": [{"path": "src/main.py", "description": "Entry point"}],
        "roadmap": [],
        "dependencies": [],
        "run_checklist": [],
    }
    fake_steps = [
        {
            "id": "step_1",
            "title": "Implement src/main.py",
            "description": "Create and test src/main.py",
            "approach": "Implement the file as specified in the architecture plan.",
            "suggested_file_paths": ["src/main.py"],
            "status": "planned"
        }
    ]
    fake_code = "```python\n# filename: src/main.py\nprint('quick build autorun')\n```"
    save_project_progress(tmp_path, {
        "project_idea": "Quick Build test",
        "architecture_plan": fake_plan,
        "plan_steps": fake_steps,
        "short_plan_steps": fake_steps,
        "roadmap_expanded": False,
        "current_step_id": "step_1",
        "plan_scaffolded": False,
        "plan_status": "review",
    })
    with patch("core.ai.generate_file_content", return_value=fake_code), patch(
        "app.generate_file_content", return_value=fake_code
    ), patch("core.ai.generate_roadmap", return_value=fake_steps), patch(
        "app.generate_roadmap", return_value=fake_steps
    ), patch("app._active_provider", return_value={
        "provider": "nebius", "api_key": "nb-fake", "base_url": "https://api.tokenfactory.nebius.com/v1/",
        "default_model": "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B", "label": "Nebius AI", "models": {}
    }):
        at = AppTest.from_file(str(APP_FILE), default_timeout=30)
        at.session_state["app_stage"] = "workspace"
        at.session_state["target_dir"] = str(tmp_path)
        at.session_state["architecture_plan"] = fake_plan
        at.session_state["plan_scaffolded"] = False
        at.session_state["quick_build"] = True
        at.run()
        # Need a second run for auto_run_file to execute
        at.run()

    entry_file = tmp_path / "src" / "main.py"
    assert entry_file.exists()
    assert "print('quick build autorun')" in entry_file.read_text(encoding="utf-8")
    assert any("quick build autorun" in entry for entry in at.session_state.get("console_history", []))
    assert at.session_state.get("plan_scaffolded") is True
    assert not at.exception


def test_chat_submits_on_enter(tmp_path: Path):
    fake_reply = "```python\n# filename: hello.py\nprint('hello world')\n```"
    with patch("core.ai.run_ai_chat", return_value=(fake_reply, {})), patch(
        "app.run_ai_chat", return_value=(fake_reply, {})
    ), patch("app._active_provider", return_value={
        "provider": "nebius", "api_key": "nb-fake", "base_url": "https://api.tokenfactory.nebius.com/v1/",
        "default_model": "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B", "label": "Nebius AI", "models": {}
    }):
        at = AppTest.from_file(str(APP_FILE), default_timeout=30)
        at.session_state["app_stage"] = "workspace"
        at.session_state["target_dir"] = str(tmp_path)
        at.session_state["plan_scaffolded"] = True
        at.session_state["messages"] = []
        at.run()
        at.chat_input[0].set_value("Generate hello.py").run()

    assert any(msg["role"] == "user" and msg["content"] == "Generate hello.py" for msg in at.session_state["messages"])
    assert any(button.key.startswith("save_response_") for button in at.button)
    assert not at.exception


def test_chat_retry_resubmits_failed_prompt(tmp_path: Path):
    with patch(
        "core.ai.run_ai_chat",
        side_effect=[AIProviderError("temporary provider error"), ("Retry worked.", {})],
    ) as mocked_chat, patch("app.run_ai_chat", mocked_chat), patch(
        "app._active_provider", return_value={
        "provider": "nebius", "api_key": "nb-fake", "base_url": "https://api.tokenfactory.nebius.com/v1/",
        "default_model": "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B", "label": "FORGE", "models": {}
    }):
        at = AppTest.from_file(str(APP_FILE), default_timeout=30)
        at.session_state["app_stage"] = "workspace"
        at.session_state["target_dir"] = str(tmp_path)
        at.session_state["plan_scaffolded"] = True
        at.session_state["messages"] = []
        at.run()
        at.chat_input[0].set_value("Explain the project").run()

        assert any("temporary provider error" in error.value for error in at.error), (
            f"chat calls={mocked_chat.call_count}, "
            f"messages={at.session_state.get('messages')!r}, "
            f"chat_inputs={[item.value for item in at.chat_input]!r}, "
            f"stage={at.session_state.get('app_stage')!r}, "
            f"provider={at.session_state.get('provider_override')!r}, "
            f"failed_request={at.session_state.get('last_failed_ai_request')!r}, "
            f"errors={[error.value for error in at.error]!r}, "
            f"exceptions={[exception.value for exception in at.exception]!r}"
        )
        next(button for button in at.button if button.key == "retry_last_chat_message").click().run()

    assert mocked_chat.call_count == 2
    assert at.session_state["messages"][-1]["content"] == "Retry worked."
    assert not at.exception


def test_chat_history_loads_older_messages_without_dropping_history(tmp_path: Path):
    messages = [
        {"role": "user", "content": f"Question {index}"}
        for index in range(35)
    ]
    at = AppTest.from_file(str(APP_FILE), default_timeout=30)
    at.session_state["app_stage"] = "workspace"
    at.session_state["target_dir"] = str(tmp_path)
    at.session_state["plan_scaffolded"] = True
    at.session_state["messages"] = messages
    at.run()

    next(button for button in at.button if button.key == "load_earlier_chat_messages").click().run()

    assert at.session_state["chat_visible_message_count"] == 35
    assert len(at.session_state["messages"]) == 35
    assert not at.exception


def test_build_roadmap_step_submits_focused_prompt(tmp_path: Path):
    fake_reply = "I will build the requested step."
    step = {
        "id": "step_1",
        "title": "Create recipe search",
        "description": "Let users search saved recipes by name.",
        "approach": "Add a small search form and filter the recipe list.",
        "suggested_file_paths": ["index.html"],
        "status": "planned",
    }
    with patch("core.ai.run_ai_chat", return_value=(fake_reply, {})), patch(
        "app.run_ai_chat", return_value=(fake_reply, {})
    ), patch("app._active_provider", return_value={
        "provider": "nebius", "api_key": "nb-fake", "base_url": "https://api.tokenfactory.nebius.com/v1/",
        "default_model": "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B", "label": "Nebius AI", "models": {}
    }):
        at = AppTest.from_file(str(APP_FILE), default_timeout=30)
        at.session_state["app_stage"] = "workspace"
        at.session_state["target_dir"] = str(tmp_path)
        at.session_state["plan_scaffolded"] = True
        at.session_state["plan_steps"] = [step]
        at.session_state["current_step"] = step
        at.session_state["roadmap_loaded_for"] = str(tmp_path.resolve())
        at.session_state["messages"] = []
        at.run()
        next(button for button in at.button if button.key == "build_roadmap_step").click().run()

    user_message = next(message["content"] for message in at.session_state["messages"] if message["role"] == "user")
    assert "Create recipe search" in user_message
    assert "index.html" in user_message
    assert not at.exception


def test_moodboard_feed_refines_architecture(tmp_path: Path):
    fake_plan = {
        "summary": "Moodboard review",
        "folders": ["src"],
        "files": [{"path": "src/main.py", "description": "Entry point"}],
        "roadmap": [],
        "dependencies": [],
        "run_checklist": [],
    }
    fake_steps = [
        {
            "id": "step_1",
            "title": "Implement src/main.py",
            "description": "Create and test src/main.py",
            "approach": "Implement the file as specified in the architecture plan.",
            "suggested_file_paths": ["src/main.py"],
            "status": "planned"
        }
    ]
    refined_plan = {**fake_plan, "summary": "Architecture refined with cache notes"}
    with patch("app._active_provider", return_value={
        "provider": "nebius", "api_key": "nb-fake", "base_url": "https://api.tokenfactory.nebius.com/v1/",
        "default_model": "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B", "label": "Nebius AI", "models": {}
    }), patch("core.ai.generate_roadmap", return_value=fake_steps), patch(
        "app.generate_roadmap", return_value=fake_steps
    ), patch("core.ai.generate_architecture", return_value=refined_plan) as generate_plan, patch(
        "app.generate_architecture", return_value=refined_plan
    ):
        at = AppTest.from_file(str(APP_FILE), default_timeout=30)
        at.session_state["app_stage"] = "workspace"
        at.session_state["target_dir"] = str(tmp_path)
        at.session_state["architecture_plan"] = fake_plan
        at.session_state["plan_scaffolded"] = False
        at.session_state["roadmap_loaded_for"] = str(tmp_path.resolve())
        at.session_state["moodboard_items"] = [
            {"id": "mb_test", "type": "Architecture", "title": "Cache Layer", "content": "Use Redis for session caching"}
        ]
        at.session_state["messages"] = []
        at.run()
        feed_btn = next(b for b in at.button if "Feed moodboard" in b.label)
        feed_btn.click().run()

    assert at.session_state["architecture_plan"]["summary"] == "Architecture refined with cache notes"
    assert "Cache Layer" in generate_plan.call_args.args[0]
    assert "Use Redis for session caching" in generate_plan.call_args.args[0]
    saved = load_project_progress(tmp_path)
    assert saved["architecture_plan"]["summary"] == "Architecture refined with cache notes"
    assert saved["plan_steps"] == fake_steps
    assert not at.exception


def test_node_editor_saves_file(tmp_path: Path):
    test_file = tmp_path / "hello.py"
    test_file.write_text("print('initial')", encoding="utf-8")
    with patch("app._active_provider", return_value={
        "provider": "nebius", "api_key": "nb-fake", "base_url": "https://api.tokenfactory.nebius.com/v1/",
        "default_model": "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B", "label": "Nebius AI", "models": {}
    }):
        at = AppTest.from_file(str(APP_FILE), default_timeout=30)
        at.session_state["app_stage"] = "workspace"
        at.session_state["target_dir"] = str(tmp_path)
        at.session_state["selected_id"] = "hello.py"
        at.session_state["plan_scaffolded"] = True
        at.run()
        at.text_area(key="editor_hello_py").set_value("print('updated content')")
        at.button(key="save_hello_py").click().run()

    assert test_file.read_text(encoding="utf-8") == "print('updated content')"
    assert not at.exception


def test_workspace_preview_runs_selected_python_file(tmp_path: Path):
    (tmp_path / "index.html").write_text("<h1>Project preview</h1>", encoding="utf-8")
    (tmp_path / "demo.py").write_text("print('preview works')\n", encoding="utf-8")
    with patch("app._active_provider", return_value={
        "provider": None, "api_key": None, "base_url": None,
        "default_model": None, "label": "No AI provider configured", "models": {},
    }):
        at = AppTest.from_file(str(APP_FILE), default_timeout=30)
        at.session_state["app_stage"] = "workspace"
        at.session_state["target_dir"] = str(tmp_path)
        at.session_state["plan_scaffolded"] = True
        at.run()
        at.selectbox(key="preview_entry_file").set_value("demo.py").run()
        at.button(key="live_run_output_btn").click().run()

    assert any("preview works" in entry for entry in at.session_state["console_history"])
    assert not at.exception


def test_workspace_launches_streamlit_app_in_preview(tmp_path: Path):
    (tmp_path / "app.py").write_text(
        "import streamlit as st\nst.title('Preview app')\n", encoding="utf-8"
    )
    with patch("app._active_provider", return_value={
        "provider": None, "api_key": None, "base_url": None,
        "default_model": None, "label": "No AI provider configured", "models": {},
    }), patch("ui.components.start_streamlit_preview", return_value=(
        "http://127.0.0.1:45678/", None
    )):
        at = AppTest.from_file(str(APP_FILE), default_timeout=30)
        at.session_state["app_stage"] = "workspace"
        at.session_state["target_dir"] = str(tmp_path)
        at.session_state["plan_scaffolded"] = True
        at.run()
        at.button(key="live_run_streamlit_app_btn").click().run()

    assert at.session_state["streamlit_preview_url"] == "http://127.0.0.1:45678/"
    assert not at.exception


def test_export_context_md(tmp_path: Path):
    sample = tmp_path / "demo.py"
    sample.write_text("def hello():\n    return 'world'\n", encoding="utf-8")
    tree = scan_tree(str(tmp_path))
    exported = export_context_md(str(tmp_path), tree)
    assert Path(exported).is_file()
    text = Path(exported).read_text(encoding="utf-8")
    assert "# CONTEXT.md" in text
    assert "## File tree" in text
    assert "demo.py" in text
    assert "## File previews" in text
    assert "return 'world'" in text
