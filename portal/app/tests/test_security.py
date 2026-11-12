"""
Portal security regression tests: HTML sanitizer, response headers, and
scheme validation on the ticket webhook + module URLs.
"""
from app.sanitize import sanitize_html
from app.tests.conftest import auth


def _admin_token(client):
    r = client.post("/api/portal/admin/auth/login",
                    json={"email": "op@acme.test", "password": "x",
                          "base_url": "http://pa.local"})
    return r.json()["access_token"]


def test_sanitizer_strips_scripts_and_handlers():
    dirty = ('<h3>Lesson</h3><script>alert(1)</script>'
             '<img src=x onerror="alert(1)"><a href="javascript:alert(1)">x</a>'
             '<b>keep</b>')
    clean = sanitize_html(dirty)
    assert "<script" not in clean.lower()
    assert "onerror" not in clean.lower()
    assert "javascript:" not in clean.lower()
    assert "<img" not in clean.lower()          # img not on the allowlist
    assert "<h3>" in clean and "<b>keep</b>" in clean   # formatting kept


def test_security_headers_present(client):
    r = client.get("/health")
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
    assert r.headers.get("X-Frame-Options") == "DENY"
    assert "frame-ancestors 'none'" in (r.headers.get("Content-Security-Policy") or "")


def test_ticket_webhook_rejects_non_http(client, fake_pa):
    atok = _admin_token(client)
    r = client.put("/api/portal/admin/ticket-config", headers=auth(atok),
                   json={"enabled": True, "webhook_url": "file:///etc/passwd"})
    assert r.status_code == 400


def test_module_rejects_javascript_urls(client, fake_pa):
    atok = _admin_token(client)
    r = client.post("/api/portal/admin/modules", headers=auth(atok),
                    json={"key": "sec-test", "title": "Sec", "kind": "remediation",
                          "lesson_html": "<b>ok</b><script>bad()</script>",
                          "resource_url": "javascript:alert(1)",
                          "video_embed_url": "http://ok.example/embed"})
    assert r.status_code == 200
    mods = client.get("/api/portal/admin/modules", headers=auth(atok)).json()
    mod = next(x for x in mods if x["key"] == "sec-test")
    assert mod["resource_url"] is None                      # javascript: dropped
    assert mod["video_embed_url"] == "http://ok.example/embed"
