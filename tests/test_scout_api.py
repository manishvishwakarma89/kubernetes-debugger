"""API tests mock Scout execution; they do not contact Docker or a registry."""
from unittest.mock import patch
from fastapi.testclient import TestClient
import main


TOKEN = "x" * 40
HEADERS = {"Authorization": "Bearer " + TOKEN}
client = TestClient(main.app)


def test_registry_default_and_failure_status(monkeypatch):
    monkeypatch.setenv("DEBUGGER_API_TOKEN", TOKEN)
    result = {"image": "nginx:latest", "source": "registry", "status": "execution_failed", "exit_code": 255}
    with patch("main.DockerDebugger.scout_scan", return_value=result) as scan:
        response = client.post("/images/scout/sync?image_name=nginx:latest", headers=HEADERS)
        scan.assert_called_once_with("nginx:latest", source="registry")
        assert response.status_code == 502
        assert response.json()["detail"]["exit_code"] == 255


def test_completed_and_vulnerability_reports(monkeypatch):
    monkeypatch.setenv("DEBUGGER_API_TOKEN", TOKEN)
    for status in ["completed", "vulnerabilities_found"]:
        with patch("main.DockerDebugger.scout_scan", return_value={"status": status}):
            response = client.post("/images/scout/sync?image_name=nginx:latest", headers=HEADERS)
            assert response.status_code == 200
            assert response.json()["status"] == status


def test_local_id_in_default_registry_mode(monkeypatch):
    monkeypatch.setenv("DEBUGGER_API_TOKEN", TOKEN)
    response = client.post("/images/scout/sync?image_name=5e2309035332", headers=HEADERS)
    assert response.status_code == 400
    assert "published image" in response.json()["detail"]


def test_source_validation_and_auth(monkeypatch):
    monkeypatch.setenv("DEBUGGER_API_TOKEN", TOKEN)
    assert client.post("/images/scout/sync?image_name=nginx:latest").status_code == 401
    assert client.post("/images/scout/sync?image_name=nginx:latest&source=archive", headers=HEADERS).status_code == 422
    with patch("main.DockerDebugger.scout_scan", return_value={"status": "completed"}) as scan:
        response = client.post("/images/scout/sync?image_name=5e2309035332&source=local", headers=HEADERS)
        assert response.status_code == 200
        scan.assert_called_once_with("5e2309035332", source="local")
