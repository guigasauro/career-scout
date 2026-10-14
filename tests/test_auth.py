import importlib

from fastapi.testclient import TestClient


def test_senha(monkeypatch):
    monkeypatch.setenv("SCOUT_PASSWORD", "segredo")
    import career_scout.api as api
    api = importlib.reload(api)
    c = TestClient(api.app)
    assert c.get("/fifa-years").status_code == 401
    assert c.get("/fifa-years", auth=("x", "errada")).status_code == 401
    assert c.get("/fifa-years", auth=("x", "segredo")).status_code == 200
    monkeypatch.delenv("SCOUT_PASSWORD")
    importlib.reload(api)
