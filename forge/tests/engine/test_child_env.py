from forge.engine import _child_env


def test_child_env_drops_secrets(monkeypatch):
    monkeypatch.setenv("FORGE_DB_URL", "postgresql://u:secret@h/db")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "x")
    monkeypatch.setenv("VAULT_TOKEN", "x")
    env = _child_env()
    for name in ("FORGE_DB_URL", "AWS_SECRET_ACCESS_KEY", "VAULT_TOKEN"):
        assert name not in env
    assert "PYTHONPATH" in env
    assert env["LC_ALL"]
