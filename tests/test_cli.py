import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def test_cli_report_and_exit_codes(tmp_path):
    path = tmp_path / 'report.json'
    process = subprocess.run([sys.executable, str(ROOT / 'cli.py'), str(ROOT / 'examples/valid.yaml'), '--report', str(path)], capture_output=True, text=True)
    assert process.returncode == 0, process.stderr
    assert json.loads(path.read_text())['outcome'] == 'valid'
    invalid = subprocess.run([sys.executable, str(ROOT / 'cli.py'), str(ROOT / 'examples/invalid.yaml')], capture_output=True, text=True)
    assert invalid.returncode == 1
    missing = subprocess.run([sys.executable, str(ROOT / 'cli.py'), str(tmp_path / 'missing')], capture_output=True, text=True)
    assert missing.returncode == 2
