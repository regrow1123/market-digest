from fastapi.testclient import TestClient

from market_digest.web.app import create_app


def test_health_endpoint():
    app = create_app(nas_dir=None)
    with TestClient(app) as c:
        resp = c.get("/healthz")
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}
