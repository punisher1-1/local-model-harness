from pathlib import Path
import shutil
import yaml
from fastapi.testclient import TestClient
from app import create_app, Settings
from test_app import KEY, HEADERS

ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "examples/school-and-general-profiles.yaml"


def test_pack_settings():
    settings = Settings.model_validate(yaml.safe_load(PACK.read_text()))
    school, general = settings.profiles["local-school"], settings.profiles["local-general"]
    for profile in (school, general):
        assert profile.client_tools and profile.chat_memory and profile.memory_recall.enabled
        assert set(profile.mcp_servers) == {"vault", "code", "web", "rag", "kb"}
        assert profile.backend_model == "auto"
        preset = profile.backend_presets["qwen3.8-27b"]
        assert preset.context_window == 131072
        assert preset.backend_options["chat_template_kwargs"]["enable_thinking"] is True
    assert school.memory_recall.scope == "school" and general.memory_recall.scope == "home"
    assert school.backend_presets["qwen3.8-27b"].temperature < general.backend_presets["qwen3.8-27b"].temperature


def test_pack_loads_with_prompts_and_skills(tmp_path, monkeypatch):
    # Tool servers only need configured URLs to start; nothing is contacted.
    for var, url in {"HARNESS_VAULT_MCP_URL": "http://vault/mcp", "HARNESS_CODE_MCP_URL": "http://sandbox/mcp",
                     "HARNESS_WEB_MCP_URL": "http://web/mcp", "HARNESS_RAG_URL": "http://rag:8100"}.items():
        monkeypatch.setenv(var, url)
    for var in ("HARNESS_RAG_TOKEN", "HARNESS_CODE_MCP_TOKEN", "HARNESS_WEB_MCP_TOKEN", "HARNESS_VAULT_MCP_TOKEN"):
        monkeypatch.setenv(var, "t" * 32)
    monkeypatch.setenv("HARNESS_CHAT_DB", str(tmp_path / "chat.sqlite3"))
    pack = yaml.safe_load(PACK.read_text())
    (tmp_path / "prompts").mkdir()
    for name in ("school.md", "general.md"):
        shutil.copyfile(ROOT / "prompts" / name, tmp_path / "prompts" / name)
    shutil.copytree(ROOT / "skills", tmp_path / "skills")
    config = tmp_path / "profiles.yaml"
    config.write_text(yaml.safe_dump(pack))
    app = create_app(config, KEY, "http://backend/v1")
    with TestClient(app) as client:
        assert client.get("/v1/identity", headers=HEADERS).status_code == 200
        assert "APA CITATION CHECK" in app.state.prompts["local-school"]
        assert "study partner" in app.state.prompts["local-school"]
        assert "general knowledge assistant" in app.state.prompts["local-general"]
