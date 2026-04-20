from __future__ import annotations

from pathlib import Path

from vast_ai_mcp.config import load_local_env


def test_load_local_env_merges_cwd_and_repo(monkeypatch, tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[1]
    repo_env = repo_root / ".env"
    original_repo_env = repo_env.read_text(encoding="utf-8") if repo_env.exists() else None

    cwd_env = tmp_path / ".env"
    cwd_env.write_text("UNRELATED_KEY=1\n", encoding="utf-8")
    repo_env.write_text("VAST_API_KEY=test-token-from-repo\n", encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("UNRELATED_KEY", raising=False)
    monkeypatch.delenv("VAST_API_KEY", raising=False)

    try:
        loaded = load_local_env()
        assert loaded == repo_env
        assert "UNRELATED_KEY" in __import__("os").environ
        assert __import__("os").environ["VAST_API_KEY"] == "test-token-from-repo"
    finally:
        if original_repo_env is None:
            repo_env.unlink(missing_ok=True)
        else:
            repo_env.write_text(original_repo_env, encoding="utf-8")
