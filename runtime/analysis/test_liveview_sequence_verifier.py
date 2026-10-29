import importlib.util
import json
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('sequence_verifier', HERE / 'verify-liveview-sequence.py')
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)


@pytest.fixture
def run(tmp_path):
    (tmp_path / 'runtime-manifest.json').write_text(json.dumps({
        'liveview_trace': True, 'selected_observer_matches_build': True,
        'compiled_observer': {'observer_sha256': 'd' * 64}}))
    (tmp_path / 'summary.json').write_text(json.dumps({'run': str(tmp_path), 'probe_collected': True}))
    lines = [f'OBS ENTRY_PROBE_ARMED liveview {label}' for label in
             ('request 0x2502e24', 'consume 0x2483188', 'run 0x309b82c')]
    lines += ['OBS LIVEVIEW_REQUEST_API n=0 tid=333 data=0 flag=1 callback=0',
              'OBS LIVEVIEW_CONSUME n=0 tid=333 object=0x1234 bytes=8 id=0x4dc flag=1',
              'OBS LIVEVIEW_RUN n=0 tid=387 object=0x5678']
    (tmp_path / 'console.log').write_text('\n'.join(lines) + '\n')
    return tmp_path


def test_sequence_proof_does_not_claim_pixels_or_completion(run):
    result = verifier.verify(run)
    assert result['original_display_setup_sequence_observed']
    assert len(result['events']) == 3
    assert not any(result[key] for key in ('display_setup_completion_verified', 'liveview_pixels_consumed',
                                           'capture_verified', 'movie_verified'))


@pytest.mark.parametrize('before,after', [
    ('LIVEVIEW_CONSUME n=0', 'LIVEVIEW_CONSUME n=1'),
    ('bytes=8', 'bytes=-1'),
    ('id=0x4dc', 'id=0x4dd'),
    ('flag=1', 'flag=0'),
    ('callback=0', 'callback=0x1234'),
    ('liveview request 0x2502e24', 'liveview post 0x36830a8'),
    ('OBS LIVEVIEW_REQUEST_API', 'OBS LIVEVIEW_REQUEST_ONCE'),
    ('OBS LIVEVIEW_RUN', 'Entering exception monitor. OBS LIVEVIEW_RUN'),
])
def test_bad_identity_missing_stage_and_old_probe_are_rejected(run, before, after):
    console = run / 'console.log'
    console.write_text(console.read_text().replace(before, after))
    with pytest.raises(ValueError):
        verifier.verify(run)


def test_out_of_order_and_injected_profiles_are_rejected(run):
    console = run / 'console.log'
    lines = console.read_text().splitlines()
    lines[-1], lines[-2] = lines[-2], lines[-1]
    console.write_text('\n'.join(lines))
    with pytest.raises(ValueError):
        verifier.verify(run)
    (run / 'runtime-manifest.json').write_text(json.dumps({
        'liveview_trace': True, 'display_setup_request': 'once-v1'}))
    with pytest.raises(ValueError, match='without request injection'):
        verifier.verify(run)


def test_unmatched_observer_is_rejected(run):
    manifest = run / 'runtime-manifest.json'
    data = json.loads(manifest.read_text())
    data['selected_observer_matches_build'] = False
    manifest.write_text(json.dumps(data))
    with pytest.raises(ValueError, match='frozen build'):
        verifier.verify(run)
