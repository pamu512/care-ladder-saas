"""ROI #5: session-gate GET /demo/upload/{job_id} + prune finished jobs."""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from care_ladder.api.app import (
    create_app,
    _prune_upload_jobs,
    _UPLOAD_JOBS,
    _UPLOAD_JOB_TTL_SEC,
)
from care_ladder.audit.store import AuditStore


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("CARE_LADDER_AUTH", "on")
    monkeypatch.setenv("SESSION_SECRET", "upload-gate")
    _UPLOAD_JOBS.clear()
    return TestClient(create_app(store=AuditStore()))


def _login(client, email="facility@careladder.local", pw="demo-pass-facility"):
    r = client.post("/auth/login", json={"email": email, "password": pw})
    assert r.status_code == 200


def test_upload_job_get_requires_session(client):
    _UPLOAD_JOBS["abc"] = {
        "status": "processing",
        "filename": "x.mp4",
        "incident_id": None,
        "error": None,
        "created_at": time.time(),
        "tenant_id": "demo-facility",
    }
    assert client.get("/demo/upload/abc").status_code == 401


def test_upload_job_get_ok_when_authed(client):
    _login(client)
    _UPLOAD_JOBS["job1"] = {
        "status": "done",
        "filename": "x.mp4",
        "incident_id": "inc-1",
        "error": None,
        "created_at": time.time(),
        "tenant_id": "demo-facility",
    }
    r = client.get("/demo/upload/job1")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "done"
    assert body["incident_id"] == "inc-1"
    assert "tenant_id" not in body


def test_upload_job_hidden_from_other_tenant(client):
    _login(client, "demo@careladder.local", "demo-pass-home")
    _UPLOAD_JOBS["fac-job"] = {
        "status": "done",
        "filename": "x.mp4",
        "incident_id": "inc-1",
        "error": None,
        "created_at": time.time(),
        "tenant_id": "demo-facility",
    }
    assert client.get("/demo/upload/fac-job").status_code == 404


def test_prune_upload_jobs_drops_stale_finished():
    _UPLOAD_JOBS.clear()
    now = time.time()
    _UPLOAD_JOBS["old"] = {
        "status": "done",
        "filename": "a.mp4",
        "incident_id": "i",
        "error": None,
        "created_at": now - _UPLOAD_JOB_TTL_SEC - 10,
    }
    _UPLOAD_JOBS["fresh"] = {
        "status": "done",
        "filename": "b.mp4",
        "incident_id": "j",
        "error": None,
        "created_at": now,
    }
    _UPLOAD_JOBS["running"] = {
        "status": "processing",
        "filename": "c.mp4",
        "incident_id": None,
        "error": None,
        "created_at": now - _UPLOAD_JOB_TTL_SEC - 10,
    }
    _prune_upload_jobs(now=now)
    assert "old" not in _UPLOAD_JOBS
    assert "fresh" in _UPLOAD_JOBS
    assert "running" in _UPLOAD_JOBS  # in-flight kept even if old
