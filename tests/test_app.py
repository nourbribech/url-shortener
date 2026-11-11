from fastapi.testclient import TestClient
from app import app

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_shorten_returns_code():
    r = client.post("/shorten", json={"url": "https://example.com/long/path"})
    assert r.status_code == 201
    body = r.json()
    assert set(body) == {"code"}
    assert len(body["code"]) == 6


def test_redirect_and_click_count():
    code = client.post("/shorten", json={"url": "https://example.com/a"}).json()["code"]
    r = client.get(f"/{code}", follow_redirects=False)
    assert r.status_code == 307
    assert r.headers["location"] == "https://example.com/a"
    assert client.get(f"/stats/{code}").json()["clicks"] == 1


def test_unknown_code_returns_404():
    assert client.get("/nope99", follow_redirects=False).status_code == 404
    assert client.get("/stats/nope99").status_code == 404


def test_invalid_url_returns_422():
    assert client.post("/shorten", json={"url": "not-a-url"}).status_code == 422


def test_metrics_are_exposed():
    client.post("/shorten", json={"url": "https://example.com/metrics"})
    text = client.get("/metrics").text
    assert "http_requests_total" in text
    assert "urls_shortened_total" in text


def test_request_id_header():
    assert "x-request-id" in client.get("/health").headers