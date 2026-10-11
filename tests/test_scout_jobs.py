"""Exercise background progress and failures with simulated scanner backends."""
import threading
import time
from unittest.mock import patch

from fastapi.testclient import TestClient
from main import DockerDebuggerApp


TOKEN = "x" * 40
HEADERS = {"Authorization": "Bearer " + TOKEN}


def terminal(client, job_id):
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        response = client.get("/images/scout/jobs/" + job_id, headers=HEADERS)
        assert response.status_code == 200
        if response.json()["state"] in ("succeeded", "failed", "timed_out"):
            return response.json()
        time.sleep(0.001)
    raise AssertionError("Fake scan did not finish")


def test_returns_before_scan_finishes_and_bounds_concurrency(monkeypatch):
    monkeypatch.setenv("DEBUGGER_API_TOKEN", TOKEN)
    client = TestClient(DockerDebuggerApp().app)
    release = threading.Event()
    started = threading.Event()

    def scan(image, source):
        started.set()
        assert release.wait(2)
        return {"status": "completed", "stdout": "report"}

    with patch("scout_jobs.DockerDebugger.scout_scan", side_effect=scan):
        try:
            response = client.post("/images/scout?image_name=nginx:latest", headers=HEADERS)
            assert response.status_code == 202
            job_id = response.json()["job_id"]
            assert started.wait(1)
            state = client.get(response.json()["status_url"], headers=HEADERS).json()
            assert state["state"] == "running"
            assert state["source"] == "registry"
            assert client.post("/images/scout?image_name=nginx:latest", headers=HEADERS).status_code == 429
        finally:
            release.set()
        result = terminal(client, job_id)
        assert result["state"] == "succeeded"
        assert result["result"]["stdout"] == "report"


def test_failure_and_timeout_are_recorded(monkeypatch):
    monkeypatch.setenv("DEBUGGER_API_TOKEN", TOKEN)
    for fake, state in [(lambda *a, **kw: {"status": "execution_failed", "exit_code": 255}, "failed"),
                        (TimeoutError("Scan stopped after 300 seconds"), "timed_out")]:
        client = TestClient(DockerDebuggerApp().app)
        with patch("scout_jobs.DockerDebugger.scout_scan", side_effect=fake):
            response = client.post("/images/scout?image_name=nginx:latest", headers=HEADERS)
            assert response.status_code == 202
            assert terminal(client, response.json()["job_id"])["state"] == state


def test_auth_input_and_missing_job(monkeypatch):
    monkeypatch.setenv("DEBUGGER_API_TOKEN", TOKEN)
    client = TestClient(DockerDebuggerApp().app)
    assert client.post("/images/scout?image_name=nginx:latest").status_code == 401
    assert client.get("/images/scout/jobs/unknown").status_code == 401
    assert client.get("/images/scout/jobs/unknown", headers=HEADERS).status_code == 404
    assert client.post("/images/scout?image_name=5e2309035332", headers=HEADERS).status_code == 400
    assert client.post("/images/scout?image_name=nginx:latest&source=archive", headers=HEADERS).status_code == 422


def test_vulnerabilities_are_a_completed_scan(monkeypatch):
    monkeypatch.setenv("DEBUGGER_API_TOKEN", TOKEN)
    client = TestClient(DockerDebuggerApp().app)
    with patch("scout_jobs.DockerDebugger.scout_scan", return_value={"status": "vulnerabilities_found", "exit_code": 2}):
        response = client.post("/images/scout?image_name=nginx:latest", headers=HEADERS)
        result = terminal(client, response.json()["job_id"])
        assert result["state"] == "succeeded"
        assert result["result"]["status"] == "vulnerabilities_found"
