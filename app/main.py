"""Writing Assistant - FastAPI app. Run: uvicorn app.main:app --port 8200"""
import io
import json
import logging
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile, Body
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import config, jobs, plain as P, rules as R
from .feedback import readability
from .diff import word_diff
from .feedback import analyse
from .rewrite import rewrite, test_api, TONES, STRENGTH
from .textutils import extract_text, normalise

logging.basicConfig(level=logging.INFO)
STATIC = Path(__file__).resolve().parent.parent / "static"
MAX_CHARS = 60000
app = FastAPI(title="Writing Assistant", version="1.1",
              description="Self-hosted editing aid: rewrite for clarity and natural flow, plus style feedback.")


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/api/health")
def health():
    s = config.load()
    return {"ok": True, "local_model": None if config.no_model() else s["local_model"],
            "api_enabled": bool(s.get("use_api") and s.get("api_key")), "tones": list(TONES), "strengths": list(STRENGTH)}


def _text(payload):
    t = normalise(str(payload.get("text", "")))
    if not t:
        raise HTTPException(400, "No text provided")
    if len(t) > MAX_CHARS:
        raise HTTPException(413, f"Text too long (max {MAX_CHARS} characters). Split it into parts.")
    return t


@app.post("/api/extract")
async def extract(file: UploadFile = File(...)):
    data = await file.read()
    if len(data) > 15 * 1024 * 1024:
        raise HTTPException(413, "File too large (max 15 MB)")
    try:
        text = extract_text(file.filename, data)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(400, f"Could not read the file: {e}")
    return {"filename": file.filename, "text": text, "chars": len(text)}


@app.post("/api/rewrite")
def start_rewrite(payload: dict = Body(...)):
    text = _text(payload)
    opts = dict(tone=payload.get("tone", "academic"), strength=payload.get("strength", "light"),
                british=bool(payload.get("british", True)), seed=payload.get("seed"),
                plain_words=bool(payload.get("plain_words", True)),
                readability_check=bool(payload.get("readability_check", True)))

    def work(progress=None):
        res = rewrite(text, progress=progress, **opts)
        res["original"] = text
        res["diff"] = word_diff(text, res["text"])
        return res
    return {"job_id": jobs.submit(work)}


@app.get("/api/jobs/{jid}")
def job(jid: str):
    j = jobs.JOBS.get(jid)
    if not j:
        raise HTTPException(404, "Unknown job")
    return j


@app.post("/api/feedback")
def feedback(payload: dict = Body(...)):
    t = _text(payload)
    style = payload.get("citation_style", "auto")
    res = analyse(t, citation_style=style if style in ("auto", "apa", "harvard", "off") else "auto")
    res["text"] = t  # offsets refer to this normalised text
    return res


@app.post("/api/diff")
def diff(payload: dict = Body(...)):
    return word_diff(str(payload.get("a", "")), str(payload.get("b", "")))


@app.post("/api/export/docx")
def export_docx(payload: dict = Body(...)):
    import docx
    d = docx.Document()
    for p in str(payload.get("text", "")).split("\n"):
        if p.strip():
            d.add_paragraph(p.strip())
    buf = io.BytesIO()
    d.save(buf)
    return Response(buf.getvalue(), media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    headers={"Content-Disposition": 'attachment; filename="edited.docx"'})


# ---------------- settings
@app.get("/api/settings")
def get_settings():
    return config.public()


@app.post("/api/settings")
def set_settings(payload: dict = Body(...)):
    return config.public(config.save(payload))


@app.post("/api/settings/test")
def settings_test():
    s = config.load()
    if not s.get("api_key"):
        raise HTTPException(400, "No API key saved")
    try:
        return test_api(s)
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"{type(e).__name__}: {str(e)[:200]}"}, status_code=502)


# ---------------- style rules
@app.get("/api/rules")
def list_rules():
    return {"rules": R.load_rules(), "types": R.RULE_TYPES, "path": str(R.rules_path())}


@app.put("/api/rules")
def replace_rules(payload: dict = Body(...)):
    try:
        return {"rules": R.save_rules(payload.get("rules", []))}
    except R.RuleError as e:
        raise HTTPException(400, str(e))


@app.post("/api/rules")
def add_or_update_rule(rule: dict = Body(...)):
    try:
        rule = R.validate_rule(rule)
    except R.RuleError as e:
        raise HTTPException(400, str(e))
    cur = R.load_rules()
    for i, r in enumerate(cur):
        if r["id"] == rule["id"]:
            cur[i] = rule
            break
    else:
        cur.append(rule)
    R.save_rules(cur)
    return rule


@app.delete("/api/rules/{rid}")
def delete_rule(rid: str):
    cur = R.load_rules()
    new = [r for r in cur if r["id"] != rid]
    if len(new) == len(cur):
        raise HTTPException(404, "No such rule")
    R.save_rules(new)
    return {"deleted": rid}


@app.post("/api/rules/{rid}/toggle")
def toggle_rule(rid: str, payload: dict = Body(default={})):
    cur = R.load_rules()
    for r in cur:
        if r["id"] == rid:
            r["enabled"] = bool(payload.get("enabled", not r.get("enabled", True)))
            R.save_rules(cur)
            return r
    raise HTTPException(404, "No such rule")


@app.get("/api/rules/export")
def export_rules():
    return Response(R.export_json(R.load_rules()), media_type="application/json",
                    headers={"Content-Disposition": 'attachment; filename="style_rules.json"'})


@app.post("/api/rules/import")
async def import_rules(file: UploadFile = File(...), mode: str = "merge"):
    try:
        rules = R.import_json((await file.read()).decode("utf-8-sig"), mode=mode)
    except (R.RuleError, ValueError, KeyError, json.JSONDecodeError) as e:
        raise HTTPException(400, f"Import failed: {e}")
    return {"rules": rules, "count": len(rules)}


@app.post("/api/rules/reset")
def reset_rules():
    return {"rules": R.reset_rules()}


@app.post("/api/rules/test")
def test_rules(payload: dict = Body(...)):
    """Preview what the replace rules do to a sample, without the language model."""
    import random
    rules = payload.get("rules") or R.load_rules()
    try:
        rules = [R.validate_rule(r) for r in rules]
    except R.RuleError as e:
        raise HTTPException(400, str(e))
    out, changes = R.apply_replacements(str(payload.get("text", "")), rules, rng=random.Random(payload.get("seed")))
    return {"text": out, "changes": changes}


# ---------------- plain-words list (complex -> plain), used by the post-processing pass
@app.get("/api/plainwords")
def get_plain_words():
    return {"words": P.load_words(), "path": str(P.words_path())}


@app.put("/api/plainwords")
def put_plain_words(payload: dict = Body(...)):
    try:
        return {"words": P.save_words(payload.get("words", {}))}
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/plainwords/reset")
def reset_plain_words():
    return {"words": P.reset_words()}


@app.post("/api/readability")
def readability_endpoint(payload: dict = Body(...)):
    return readability(_text(payload))
