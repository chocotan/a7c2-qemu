"""Host-only checks for the isolated observer build recipe."""
import hashlib
from pathlib import Path
import re
import subprocess

HERE = Path(__file__).resolve().parent
ANALYSIS = HERE.parents[1]/'runtime/analysis'
RECIPE = HERE/'build-observer-diagnostic.sh'


def test_isolated_recipe_matches_reviewed_observer_object_lists(tmp_path):
    upstream = (ANALYSIS/'build-observers.sh').read_text()
    isolated = RECIPE.read_text()
    assert hashlib.sha256(upstream.encode()).hexdigest() in isolated
    assert 'observer_private_inputs.py' in isolated
    assert 'lib="$out/lib"' in isolated
    assert "schema='a7c2-isolated-observer-build-v2'" in isolated
    for name in ('device', 'owner', 'parser', 'capture'):
        pattern = rf'for {name} in (.*?); do'
        left = [value.replace('\\\n', ' ').split() for value in re.findall(pattern, upstream, re.S)]
        right = [value.replace('\\\n', ' ').split() for value in re.findall(pattern, isolated, re.S)]
        assert left and left == right
    syntax = subprocess.run(['bash', '-n', str(RECIPE)], capture_output=True, text=True)
    assert syntax.returncode == 0, syntax.stderr
    rejected = subprocess.run(['bash', str(RECIPE), str(tmp_path/'invalid')], capture_output=True, text=True)
    assert rejected.returncode != 0
    assert not (tmp_path/'invalid').exists()
