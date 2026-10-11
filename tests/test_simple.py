from unittest.mock import patch
from fastapi.testclient import TestClient
import main

client = TestClient(main.app)
TOKEN = 'x' * 40
HEADERS = {'Authorization': 'Bearer ' + TOKEN}


def test_auth(monkeypatch):
    monkeypatch.setenv('DEBUGGER_API_TOKEN', TOKEN)
    assert client.get('/containers').status_code == 401
    assert client.get('/healthz').status_code == 200
    assert client.get('/docs').status_code == 200


def test_routes_and_cleanup(monkeypatch):
    monkeypatch.setenv('DEBUGGER_API_TOKEN', TOKEN)
    with patch('main.DockerDebugger') as constructor:
        debugger = constructor.return_value
        debugger.list_containers.return_value = [{'name': 'example'}]
        debugger.get_logs.return_value = {'logs': 'hello', 'truncated': False}
        assert client.get('/containers', headers=HEADERS).json() == [{'name': 'example'}]
        assert client.get('/containers/example/logs', headers=HEADERS).json()['logs'] == 'hello'
        debugger.get_logs.assert_called_once_with('example', 200)
        assert debugger.close.call_count == 2
        assert client.get('/containers/example/logs?tail=2000', headers=HEADERS).status_code == 422


def test_sanitized_inspect_and_log_capture():
    from docker_debugger import DockerDebugger
    with patch('docker_debugger.docker.from_env') as factory:
        service = DockerDebugger()
        item = factory.return_value.containers.get.return_value
        item.attrs = {'Config': {'Image': 'test', 'Env': ['PASSWORD=secret']}, 'State': {'Status': 'running'}}
        item.logs.return_value = b'stdout\nstderr\n'
        assert 'secret' not in str(service.inspect_container('example'))
        assert service.get_logs('example')['logs'] == 'stdout\nstderr\n'
        try:
            service.get_logs('--invalid')
        except ValueError:
            pass
        else:
            raise AssertionError('Invalid ID accepted')
        service.close()
        factory.return_value.close.assert_called_once()
