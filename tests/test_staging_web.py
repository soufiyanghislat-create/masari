import json
from datetime import datetime, timedelta

import staging_web


def test_runtime_dir_prefers_explicit_env(monkeypatch, tmp_path):
    monkeypatch.setenv("MASARI_RUNTIME_DIR", str(tmp_path))
    monkeypatch.delenv("RAILWAY_VOLUME_MOUNT_PATH", raising=False)
    assert staging_web.runtime_dir() == tmp_path


def test_runtime_dir_uses_railway_volume(monkeypatch):
    monkeypatch.delenv("MASARI_RUNTIME_DIR", raising=False)
    monkeypatch.setenv("RAILWAY_VOLUME_MOUNT_PATH", "/data")
    assert str(staging_web.runtime_dir()) == "/data/emploi_public"


def test_health_endpoint_is_alive_even_before_first_index(monkeypatch, tmp_path):
    monkeypatch.setenv("MASARI_RUNTIME_DIR", str(tmp_path))
    payload = staging_web.healthz()
    assert payload["ok"] is True
    assert payload["ready"] is False


def test_bootstrap_requires_full_when_index_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("MASARI_RUNTIME_DIR", str(tmp_path))
    now = datetime(2026, 8, 13, 18, 0, tzinfo=staging_web.TZ)
    assert staging_web.bootstrap_mode(now) == "full"


def test_api_search_ambiguous_profession(monkeypatch, tmp_path):
    current = tmp_path / "current"
    current.mkdir(parents=True)
    (current / "search_index.json").write_text(
        json.dumps({"jobs": []}),
        encoding="utf-8",
    )
    monkeypatch.setenv("MASARI_RUNTIME_DIR", str(tmp_path))
    staging_web._cache_index = None
    staging_web._cache_mtime_ns = None

    result = staging_web.api_search("dessinateur", 15)
    assert result["selection_required"] is True
    assert len(result["suggestions"]) >= 2
