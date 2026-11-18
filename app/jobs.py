import threading
import time
import uuid

JOBS = {}
_LOCK = threading.Lock()


def submit(fn, *args, **kw):
    jid = uuid.uuid4().hex[:12]
    JOBS[jid] = {"id": jid, "status": "queued", "progress": 0.0, "message": "Queued", "created": time.time()}

    def progress(p, msg, partial=None):
        JOBS[jid].update(progress=round(p, 3), message=msg)
        if partial is not None:
            JOBS[jid]["partial"] = partial

    def run():
        JOBS[jid]["status"] = "running"
        try:
            JOBS[jid]["result"] = fn(*args, progress=progress, **kw)
            JOBS[jid]["status"] = "done"
        except Exception as e:
            JOBS[jid].update(status="error", message=f"{type(e).__name__}: {e}")
    threading.Thread(target=run, daemon=True).start()
    with _LOCK:  # keep memory bounded
        old = sorted(JOBS.values(), key=lambda j: j["created"])[:-50]
        for j in old:
            JOBS.pop(j["id"], None)
    return jid
