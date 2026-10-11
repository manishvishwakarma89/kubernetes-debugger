import json
from pathlib import Path
import pytest
from validator import analyze, InputError, VERSIONS

ROOT = Path(__file__).resolve().parents[1]
CONFIG = 'apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: demo\ndata:\n  key: value\n'


def test_valid_examples():
    report = analyze((ROOT / 'examples/valid.yaml').read_text())
    assert report['outcome'] == 'valid'
    assert report['resource_count'] == 2
    assert report['error_count'] == 0
    assert report['warning_count'] == 0


@pytest.mark.parametrize('version', VERSIONS)
def test_versioned_schema(version):
    assert analyze(CONFIG, version)['outcome'] == 'valid'


def test_selector_mismatch_and_advice():
    report = analyze((ROOT / 'examples/invalid.yaml').read_text())
    codes = {x['code'] for x in report['findings']}
    assert report['outcome'] == 'invalid'
    assert {'SELECTOR_MISMATCH', 'FLOATING_IMAGE', 'RESOURCE_BUDGET', 'NON_ROOT', 'PRIVILEGED_CONTAINER', 'READINESS_PROBE'} <= codes


def test_required_schema_field_and_unknown_field():
    source = (ROOT / 'examples/valid.yaml').read_text().split('---')[0]
    report = analyze(source.replace('replicas: 2', 'replicas: wrong'))
    assert any(x['code'] == 'SCHEMA_ERROR' for x in report['findings'])
    report = analyze(CONFIG + 'madeUp: true\n')
    assert report['error_count'] > 0


@pytest.mark.parametrize('source', [
    'apiVersion: v1\nkind: ConfigMap\nmetadata: [',
    'kind: Pod\nkind: Service',
    'x: &anchor [value]\ny: *anchor',
    '!!python/object/apply:os.system ["touch should-not-exist"]',
    'x: ' + '[' * 50 + '0' + ']' * 50,
    '', '---\n',
])
def test_unsafe_or_invalid_yaml(source):
    with pytest.raises(InputError):
        analyze(source)


def test_large_input_and_resource_limit():
    with pytest.raises(InputError): analyze('x' * (512 * 1024 + 1))
    with pytest.raises(InputError): analyze(('---\n' + CONFIG) * 101)


def test_list_and_duplicate_resource():
    source = 'apiVersion: v1\nkind: List\nitems:\n' + '\n'.join('  ' + row for row in ('- ' + CONFIG.replace('\n', '\n  ').rstrip()).splitlines())
    assert analyze(source)['resource_count'] == 1
    report = analyze(CONFIG + '---\n' + CONFIG)
    assert any(x['code'] == 'DUPLICATE_RESOURCE' for x in report['findings'])


def test_custom_resources_not_claimed_valid():
    result = analyze('apiVersion: example.test/v1\nkind: Widget\nmetadata:\n  name: demo\n')
    assert result['outcome'] == 'incomplete'
    assert result['schema_coverage_complete'] is False


def test_manifest_values_not_echoed_in_schema_or_yaml_errors():
    secret = 'SECRET_CANARY_DO_NOT_ECHO'
    result = analyze(CONFIG.replace('key: value', 'key: [' + secret + ']'))
    assert result['error_count'] > 0
    assert secret not in json.dumps(result)
    with pytest.raises(InputError) as error:
        analyze('key: [' + secret)
    assert secret not in str(error.value)


def test_unsupported_version():
    with pytest.raises(InputError): analyze(CONFIG, '1.99.0')
