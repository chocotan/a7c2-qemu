#!/usr/bin/env python3
"""Run selected synthetic host tests of the complete-image/P1/USB sources; no VM or USB access."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / 'runtime/analysis'))
sys.path.insert(0, str(ROOT / 'report/2026-10-17-qemu-full-system'))
spec = importlib.util.spec_from_file_location('public_model_guard', ROOT / 'tools/test-public-models.py')
models = importlib.util.module_from_spec(spec)
spec.loader.exec_module(models)


def main():
    names = json.loads((ROOT / 'tools/system-runtime-tests.json').read_text())
    if (not isinstance(names, list) or not names or any(type(name) is not str for name in names)
            or len(names) != len(set(names))):
        raise ValueError('Expected a nonempty unique system host test manifest')
    paths = []
    for name in names:
        path = Path(name)
        if (path.is_absolute() or '..' in path.parts or path.as_posix() != name or
                not path.name.startswith(('test-', 'test_')) or path.suffix != '.py'):
            raise ValueError('Invalid relative system host test path: ' + name)
        resolved = (ROOT / path).resolve()
        if not resolved.is_relative_to(ROOT) or not resolved.is_file():
            raise ValueError('Missing or escaping system host test: ' + name)
        paths.append(str(resolved))
    output = ROOT / 'validation/tmp/system-runtime'
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='a7s-', dir=os.environ.get('TMPDIR') or '/var/tmp') as temporary:
        os.environ.update(TMPDIR=temporary, PYTHONDONTWRITEBYTECODE='1', DISPLAY='',
                          PYTEST_DISABLE_PLUGIN_AUTOLOAD='1')
        sys.addaudithook(models.guard)
        import pytest
        import public_asset_tests
        print('HOST_SYSTEM_RUNTIME_ONLY; no guest, host USB, physical disk, installation or capture acceptance', flush=True)
        return pytest.main(['-q', '--color=no', '--import-mode=importlib', '-p', 'no:cacheprovider',
                            '--basetemp', str(Path(temporary) / 'p'), '--junitxml', str(output / 'result.xml'),
                            *paths, *sys.argv[1:]], plugins=[public_asset_tests])


if __name__ == '__main__':
    raise SystemExit(main())
