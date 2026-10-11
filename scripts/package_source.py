#!/usr/bin/env python3
"""Create a source bundle with Dockerfile at root, omitting common local secrets."""
import argparse
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

SKIP_DIRS = {'.git', '.venv', 'venv', '__pycache__', '.pytest_cache', 'node_modules', 'logs', 'certs', 'certificates'}
SKIP_SUFFIXES = {'.pyc', '.pem', '.key', '.p12', '.pfx', '.log', '.zip'}

def package(source: Path, output: Path):
    source = source.resolve()
    output = output.resolve()
    if not source.is_dir() or not (source / 'Dockerfile').is_file():
        raise ValueError('Source directory must contain a root Dockerfile.')
    files = []
    for item in sorted(source.rglob('*')):
        relative = item.relative_to(source)
        if item.is_symlink():
            raise ValueError(f'Symlinks are not accepted: {relative}')
        if not item.is_file() or item.resolve() == output:
            continue
        if any(part in SKIP_DIRS for part in relative.parts):
            continue
        if item.name == '.env' or item.name.startswith('.env.') or item.suffix.lower() in SKIP_SUFFIXES:
            continue
        files.append((item, relative.as_posix()))
    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output, 'w', ZIP_DEFLATED) as archive:
        for item, name in files:
            archive.write(item, name)
    with ZipFile(output) as archive:
        if 'Dockerfile' not in archive.namelist() or archive.testzip() is not None:
            raise ValueError('Bundle verification failed.')
    return [name for _, name in files]

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    try:
        names = package(args.source, args.output)
    except (OSError, ValueError) as exc:
        parser.exit(1, f'{exc}\n')
    print(f'Created {args.output} with {len(names)} files. Review these for secrets:')
    print('\n'.join(names))

if __name__ == '__main__':
    main()
