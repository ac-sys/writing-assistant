import io
import time

from fastapi.testclient import TestClient

from app.main import app

c = TestClient(app)


def wait(jid):
    for _ in range(200):
        j = c.get(f"/api/jobs/{jid}").json()
        if j["status"] in ("done", "error"):
            return j
        time.sleep(0.05)
    raise AssertionError("job timeout")


def test_health_and_index():
    assert c.get("/api/health").json()["ok"]
    r = c.get("/")
    assert r.status_code == 200 and "Editing aid" in r.text


def test_rewrite_job_and_diff(sample):
    jid = c.post("/api/rewrite", json={"text": sample, "tone": "formal", "strength": "full", "british": True, "seed": 1}).json()["job_id"]
    j = wait(jid)
    assert j["status"] == "done"
    res = j["result"]
    assert res["diff"]["right"] and res["label"].startswith("Edited with Writing Assistant")


def test_feedback_endpoint_returns_normalised_text():
    r = c.post("/api/feedback", json={"text": "It is important to note that we   utilize tools."}).json()
    assert r["text"] == "It is important to note that we utilize tools."
    assert any(i["category"] == "wordy" for i in r["issues"])


def test_extract_endpoint_and_errors():
    r = c.post("/api/extract", files={"file": ("a.txt", b"Hello world.", "text/plain")})
    assert r.json()["text"] == "Hello world."
    assert c.post("/api/extract", files={"file": ("a.exe", b"x", "application/octet-stream")}).status_code == 400
    assert c.post("/api/feedback", json={"text": "  "}).status_code == 400


def test_rules_crud_toggle_import_export():
    n = len(c.get("/api/rules").json()["rules"])
    rule = {"id": "my-rule", "name": "a lot of", "type": "replace", "pattern": "a lot of", "alternatives": ["many"]}
    assert c.post("/api/rules", json=rule).status_code == 200
    assert len(c.get("/api/rules").json()["rules"]) == n + 1
    rule["alternatives"] = ["plenty of"]
    c.post("/api/rules", json=rule)
    got = [r for r in c.get("/api/rules").json()["rules"] if r["id"] == "my-rule"][0]
    assert got["alternatives"] == ["plenty of"]
    assert c.post("/api/rules/test", json={"text": "A lot of people."}).json()["text"] == "Plenty of people."
    assert c.post("/api/rules/my-rule/toggle", json={"enabled": False}).json()["enabled"] is False
    assert c.post("/api/rules/test", json={"text": "A lot of people."}).json()["text"] == "A lot of people."
    assert c.post("/api/rules", json={"type": "check", "pattern": "("}).status_code == 400
    exported = c.get("/api/rules/export").content
    assert c.delete("/api/rules/my-rule").status_code == 200
    r = c.post("/api/rules/import?mode=merge", files={"file": ("r.json", exported, "application/json")})
    assert r.json()["count"] == n + 1
    assert c.post("/api/rules/import", files={"file": ("r.json", b"{bad", "application/json")}).status_code == 400
    assert len(c.post("/api/rules/reset", json={}).json()["rules"]) == n


def test_user_rule_changes_rewrite_and_feedback():
    c.post("/api/rules", json={"id": "ban-synergy", "type": "ban", "phrases": ["synergy"], "action": "remove",
                               "message": "Jargon"})
    fb = c.post("/api/feedback", json={"text": "We value synergy here."}).json()
    assert any(i["rule"] == "ban-synergy" for i in fb["issues"])
    j = wait(c.post("/api/rewrite", json={"text": "We value synergy here."}).json()["job_id"])
    assert "synergy" not in j["result"]["text"]


def test_settings_mask_key():
    s = c.post("/api/settings", json={"api_key": "sk-secret", "api_model": "m", "use_api": False}).json()
    assert s["api_key"] == "********"
    s = c.post("/api/settings", json={"api_key": "********"}).json()
    from app import config
    assert config.load()["api_key"] == "sk-secret"


def test_export_docx():
    r = c.post("/api/export/docx", json={"text": "One.\nTwo."})
    import docx
    d = docx.Document(io.BytesIO(r.content))
    assert [p.text for p in d.paragraphs] == ["One.", "Two."]


def test_api_backend_fallback_when_unreachable(sample, monkeypatch):
    c.post("/api/settings", json={"use_api": True, "api_key": "x", "api_base": "http://127.0.0.1:9/v1", "api_timeout": 2})
    j = wait(c.post("/api/rewrite", json={"text": "We utilize tools in order to learn."}).json()["job_id"])
    res = j["result"]
    assert res["backends"] == ["rules"] and any("api failed" in n for n in res["notes"])
    assert res["text"] == "We use tools to learn."
