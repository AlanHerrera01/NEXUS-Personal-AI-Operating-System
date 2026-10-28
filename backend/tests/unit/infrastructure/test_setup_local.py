import hashlib
import importlib.util
from pathlib import Path

import pytest


@pytest.fixture
def setup_module(tmp_path):
    source = Path(__file__).resolve().parents[4] / "scripts" / "setup_local.py"
    spec = importlib.util.spec_from_file_location("nexus_setup_local", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.ROOT = tmp_path
    (tmp_path / "backend").mkdir()
    (tmp_path / "backend" / ".env.example").write_text("TRUST_DEFAULT_DECISION=DENY\n", encoding="utf-8")
    return module


def test_setup_generates_matching_credentials_without_printing_key(setup_module, capsys):
    setup_module.main()
    root = setup_module.ROOT
    key = (root / ".nexus-access-key").read_text()
    digest = hashlib.sha256(key.encode()).hexdigest()
    assert len(key) >= 43
    assert setup_module.env_values(root / ".env")["AUTH_TOKEN_HASH"] == digest
    assert setup_module.env_values(root / "backend" / ".env")["AUTH_TOKEN_HASH"] == digest
    assert key not in capsys.readouterr().out
    assert len(setup_module.env_values(root / ".env")["POSTGRES_PASSWORD"]) > 1
    before = (root / ".env").read_text()
    setup_module.main()
    assert (root / ".env").read_text() == before
    assert (root / ".nexus-access-key").read_text() == key


def test_setup_fills_empty_templates_and_preserves_existing_database_and_provider(setup_module):
    root = setup_module.ROOT
    (root / ".env").write_text("POSTGRES_PASSWORD=existing-private-password\nAUTH_TOKEN_HASH=\n", encoding="utf-8")
    (root / "backend" / ".env").write_text("NEBIUS_API_KEY=existing-provider-secret\nAUTH_TOKEN_HASH=\n", encoding="utf-8")
    setup_module.main()
    assert setup_module.env_values(root / ".env")["POSTGRES_PASSWORD"] == "existing-private-password"
    assert setup_module.env_values(root / "backend" / ".env")["NEBIUS_API_KEY"] == "existing-provider-secret"
    assert setup_module.env_values(root / ".env")["AUTH_TOKEN_HASH"]


def test_setup_refuses_to_replace_an_existing_operator_hash(setup_module):
    (setup_module.ROOT / ".env").write_text("AUTH_TOKEN_HASH=" + "a" * 64 + "\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="does not match"):
        setup_module.main()
    assert setup_module.env_values(setup_module.ROOT / ".env")["AUTH_TOKEN_HASH"] == "a" * 64
