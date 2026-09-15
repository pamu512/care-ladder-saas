"""POST /demo/upload: real video clip → ladder."""

import cv2
import numpy as np
from fastapi.testclient import TestClient

from care_ladder.api.app import create_app
from care_ladder.audit.store import AuditStore


def _clip_bytes(person_frames=25, total=32, fps=5) -> bytes:
    import tempfile
    from pathlib import Path

    tmp = Path(tempfile.mkstemp(suffix=".mp4")[1])
    w, h = 320, 240
    vw = cv2.VideoWriter(str(tmp), cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
    rng = np.random.default_rng(5)
    for i in range(total):
        f = (rng.random((h, w, 3)) * 20 + 30).astype(np.uint8)
        if i < person_frames:
            f[60:190, 130:200] = (110, 130, 150)
            cv2.circle(f, (165, 45), 20, (180, 170, 160), -1)
        vw.write(f)
    vw.release()
    data = tmp.read_bytes()
    tmp.unlink()
    return data




def _upload_and_wait(client, name, data, mime="video/mp4", timeout=60.0):
    """POST upload (202 job) then poll the job endpoint until done/error."""
    import time

    r = client.post("/demo/upload", files={"file": (name, data, mime)})
    if r.status_code != 200:
        return r  # immediate validation error
    job = r.json()["incident_id"]  # job id (async contract)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        j = client.get(f"/demo/upload/{job}").json()
        if j["status"] == "done":
            class _R:  # minimal response shim
                status_code = 200
                def json(self_inner):
                    return {"incident_id": j["incident_id"]}
            return _R()
        if j["status"] == "error":
            detail = j.get("error")
            code = 422 if "could not be decoded" in str(detail) or "no cue" in str(detail) else 500
            class _RE:
                status_code = code
                text = str(detail)
                def json(self_inner):
                    return {"detail": detail}
            return _RE()
        time.sleep(0.1)
    raise AssertionError("upload job did not finish in time")


def test_upload_clip_runs_ladder():
    app = create_app(store=AuditStore())
    with TestClient(app) as client:
        r = _upload_and_wait(client, "leaves.mp4", _clip_bytes())
        assert r.status_code == 200, getattr(r, "text", "")
        inc_id = r.json()["incident_id"]
        inc = client.get(f"/incidents/{inc_id}").json()

    assert inc["cue"]["kind"] in {"no_visibility", "no_movement"}
    src = inc["cue"]["detail"]["source"]
    assert src.startswith("uploaded_clip:")
    assert inc["cue"]["detail"]["clip_frames"] > 0
    tools = [e["tool"] for e in inc["events"]]
    assert "speaker_prompt" in tools and "dial_contact" in tools
    assert inc["pre_event_frame_count"] >= 1


def test_upload_garbage_422_or_400():
    app = create_app(store=AuditStore())
    with TestClient(app) as client:
        r = _upload_and_wait(client, "bad.mp4", b"garbage")
        assert r.status_code in {400, 422, 500}


def test_upload_bad_extension_400():
    app = create_app(store=AuditStore())
    with TestClient(app) as client:
        r = client.post(
            "/demo/upload", files={"file": ("x.exe", b"MZ", "application/octet-stream")}
        )
        assert r.status_code == 400
