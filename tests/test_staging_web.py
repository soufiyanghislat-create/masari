import json
from datetime import datetime

import staging_web


def reset_cache():
    staging_web._cache_index = None
    staging_web._cache_key = None


def test_runtime_dir_prefers_explicit_env(monkeypatch, tmp_path):
    monkeypatch.setenv("MASARI_RUNTIME_DIR", str(tmp_path))
    monkeypatch.delenv("RAILWAY_VOLUME_MOUNT_PATH", raising=False)
    assert staging_web.runtime_dir() == tmp_path


def test_active_index_falls_back_to_bootstrap(monkeypatch, tmp_path):
    monkeypatch.setenv("MASARI_RUNTIME_DIR", str(tmp_path / "runtime"))
    seed = tmp_path / "bootstrap-search-index.json"
    seed.write_text(json.dumps({"jobs": []}), encoding="utf-8")
    monkeypatch.setattr(staging_web, "bootstrap_index_path", lambda: seed)

    path, source = staging_web.active_index_path()
    assert path == seed
    assert source == "bootstrap"


def test_runtime_index_wins_over_bootstrap(monkeypatch, tmp_path):
    runtime = tmp_path / "runtime"
    current = runtime / "current"
    current.mkdir(parents=True)
    runtime_index = current / "search_index.json"
    runtime_index.write_text(json.dumps({"jobs": []}), encoding="utf-8")

    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps({"jobs": [{"uuid": "seed"}]}), encoding="utf-8")

    monkeypatch.setenv("MASARI_RUNTIME_DIR", str(runtime))
    monkeypatch.setattr(staging_web, "bootstrap_index_path", lambda: seed)

    path, source = staging_web.active_index_path()
    assert path == runtime_index
    assert source == "runtime"


def test_health_ready_with_bootstrap(monkeypatch, tmp_path):
    monkeypatch.setenv("MASARI_RUNTIME_DIR", str(tmp_path / "runtime"))
    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps({"jobs": []}), encoding="utf-8")
    monkeypatch.setattr(staging_web, "bootstrap_index_path", lambda: seed)

    payload = staging_web.healthz()
    assert payload["ok"] is True
    assert payload["ready"] is True
    assert payload["index_source"] == "bootstrap"


def test_bootstrap_still_triggers_full_background_refresh(monkeypatch, tmp_path):
    monkeypatch.setenv("MASARI_RUNTIME_DIR", str(tmp_path / "runtime"))
    now = datetime(2026, 8, 13, 18, 0, tzinfo=staging_web.TZ)
    assert staging_web.bootstrap_mode(now) == "full"


def test_api_search_ambiguous_profession_uses_bootstrap(monkeypatch, tmp_path):
    runtime = tmp_path / "runtime"
    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps({"jobs": []}), encoding="utf-8")

    monkeypatch.setenv("MASARI_RUNTIME_DIR", str(runtime))
    monkeypatch.setattr(staging_web, "bootstrap_index_path", lambda: seed)
    reset_cache()

    result = staging_web.api_search("dessinateur", 15)
    assert result["selection_required"] is True
    assert result["index_source"] == "bootstrap"
    assert len(result["suggestions"]) >= 2


def test_public_meta_does_not_expose_refresh_error_text(monkeypatch, tmp_path):
    runtime = tmp_path / "runtime"
    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps({"jobs": []}), encoding="utf-8")

    monkeypatch.setenv("MASARI_RUNTIME_DIR", str(runtime))
    monkeypatch.setattr(staging_web, "bootstrap_index_path", lambda: seed)
    reset_cache()

    staging_web._set_refresh_state(
        running=False,
        last_error="/internal/path secret-ish diagnostic",
    )
    payload = staging_web.api_meta()

    assert payload["refresh"]["last_failed"] is True
    assert "last_error" not in payload["refresh"]
