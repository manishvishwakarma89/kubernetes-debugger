from fastapi.testclient import TestClient
import main

client = TestClient(main.app)
TOKEN = 'x' * 40
HEADERS = {'Authorization': 'Bearer ' + TOKEN}
MANIFEST = 'apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: test\n'


def test_public_health_and_ui():
    assert client.get('/healthz').json() == {'status': 'ok'}
    assert 'Kubernetes Manifest Debugger' in client.get('/').text
    assert client.get('/docs').status_code == 200


def test_missing_configuration_fails_closed(monkeypatch):
    monkeypatch.delenv('DEBUGGER_API_TOKEN', raising=False)
    assert client.post('/validate', json={'manifest': MANIFEST}).status_code == 503


def test_auth_and_success(monkeypatch):
    monkeypatch.setenv('DEBUGGER_API_TOKEN', TOKEN)
    assert client.post('/validate', json={'manifest': MANIFEST}).status_code == 401
    assert client.post('/validate', json={'manifest': MANIFEST}, headers={'Authorization': 'Bearer wrong'}).status_code == 401
    result = client.post('/validate', json={'manifest': MANIFEST}, headers=HEADERS)
    assert result.status_code == 200
    assert result.json()['outcome'] == 'valid'
    assert client.get('/versions', headers=HEADERS).status_code == 200


def test_input_errors_and_body_limit(monkeypatch):
    monkeypatch.setenv('DEBUGGER_API_TOKEN', TOKEN)
    for payload in [{}, {'manifest': []}, {'manifest': MANIFEST, 'extra': True}, {'manifest': MANIFEST, 'kubernetes_version': 'bad'}]:
        assert client.post('/validate', json=payload, headers=HEADERS).status_code == 400
    assert client.post('/validate', content=b'not-json', headers=HEADERS).status_code == 400
    assert client.post('/validate', content=b'x' * (1024 * 1024 + 1), headers=HEADERS).status_code == 413
    assert client.post('/validate', json={'manifest': MANIFEST}, headers=HEADERS).status_code == 200


def test_concurrency_capacity_and_release(monkeypatch):
    monkeypatch.setenv('DEBUGGER_API_TOKEN', TOKEN)
    for _ in range(4): main.slots.acquire()
    try:
        assert client.post('/validate', json={'manifest': MANIFEST}, headers=HEADERS).status_code == 429
    finally:
        for _ in range(4): main.slots.release()
    assert client.post('/validate', json={'manifest': MANIFEST}, headers=HEADERS).status_code == 200


def test_swagger_body_schema():
    operation = client.get('/openapi.json').json()['paths']['/validate']['post']
    assert 'requestBody' in operation
    assert 'manifest' in operation['requestBody']['content']['application/json']['schema']['properties']
