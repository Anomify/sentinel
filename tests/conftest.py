import pytest


@pytest.fixture(autouse=True)
def tmp_data(tmp_path, monkeypatch):
    """Every test gets its own data directory (and therefore its own SQLite DB)."""
    from cimonitor import db, tenancy
    monkeypatch.setenv("SENTINEL_DEMO", "")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(tenancy, "BASE_DATA", tmp_path)
    db.reset_cache()
    yield tmp_path
    db.reset_cache()
