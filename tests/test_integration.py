from fastapi.testclient import TestClient
from unittest.mock import patch
import main

client = TestClient(main.app)
MANIFEST = 'apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: combined\n'


def test_shared_token_and_independent_backends(monkeypatch):
    token = 'integrated-token-' + 'x' * 32
    monkeypatch.setenv('DEBUGGER_API_TOKEN', token)
    headers = {'Authorization': 'Bearer ' + token}
    with patch('main.DockerDebugger', side_effect=RuntimeError('Docker unavailable')):
        assert client.post('/validate', json={'manifest': MANIFEST}, headers=headers).json()['outcome'] == 'valid'
    with patch.object(main.application.scout_jobs, 'submit', return_value={'job_id':'test','state':'accepted','status_url':'/images/scout/jobs/test'}) as submit:
        response = client.post('/images/scout?image_name=nginx:latest', headers=headers)
        assert response.status_code == 202
        submit.assert_called_once_with('nginx:latest','registry')
    for path, method in [('/versions','get'),('/containers','get'),('/images/scout?image_name=nginx:latest','post'),('/validate','post')]:
        assert getattr(client,method)(path).status_code == 401
        monkeypatch.delenv('DEBUGGER_API_TOKEN')
        assert getattr(client,method)(path).status_code == 503
        monkeypatch.setenv('DEBUGGER_API_TOKEN',token)


def test_dashboard_and_unique_routes():
    text = client.get('/').text
    for feature in ['Docker debugger','Kubernetes Manifest Debugger','Scan image','Container logs']:
        assert feature in text
    paths = list(client.get('/openapi.json').json()['paths'])
    assert sum(getattr(r, 'path', None) == '/' for r in main.app.routes) == 1
    assert len(paths) == len(set(paths))
    assert '/validate' in paths and '/images/scout' in paths


def test_unicode_bad_token_is_rejected(monkeypatch):
    monkeypatch.setenv('DEBUGGER_API_TOKEN','é' * 40)
    assert client.get('/versions',headers={'Authorization':'Bearer wrong'}).status_code == 401
