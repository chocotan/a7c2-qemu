"""Verify the original display-setup request/consume/run chain, never image output."""
import argparse
import hashlib
import json
from pathlib import Path
import re


def verify(run):
    manifest = json.loads((run / 'runtime-manifest.json').read_text())
    summary = json.loads((run / 'summary.json').read_text())
    console = (run / 'console.log').read_bytes()
    text = console.decode(errors='replace')
    if not isinstance(manifest, dict) or not isinstance(summary, dict):
        raise ValueError('Run metadata must be JSON objects')
    if manifest.get('liveview_trace') is not True or manifest.get('display_setup_request'):
        raise ValueError('Requires trace-only natural boot, without request injection')
    if summary.get('probe_collected') is not True or Path(summary['run']).resolve() != run.resolve():
        raise ValueError('Incomplete capture or mismatched run identity')
    compiled = manifest.get('compiled_observer')
    observer_sha = compiled.get('observer_sha256') if isinstance(compiled, dict) else None
    if (manifest.get('selected_observer_matches_build') is not True or not isinstance(observer_sha, str)
            or not re.fullmatch('[0-9a-f]{64}', observer_sha)):
        raise ValueError('Selected observer did not match the frozen build')
    if any(marker in text for marker in ('Entering exception monitor.', 'ENTRY_PROBE_MISMATCH',
                                         'ENTRY_PROBE_FAILED', 'ENTRY_PROBE_REPROTECT_FAILED',
                                         'LIVEVIEW_TRACE_REFUSED', 'LIVEVIEW_REQUEST_ONCE')):
        raise ValueError('Guest exception, probe failure or injected request')
    for label in ('request 0x2502e24', 'consume 0x2483188', 'run 0x309b82c'):
        if f'OBS ENTRY_PROBE_ARMED liveview {label}' not in text:
            raise ValueError(f'Corrected original probe was not armed: {label}')
    events = []
    for number, line in enumerate(text.splitlines(), 1):
        match = re.match(r'OBS LIVEVIEW_(REQUEST_API|CONSUME|RUN) (.*)', line)
        if match:
            events.append((number, match[1], dict(re.findall(r'(\w+)=([^\s]+)', match[2]))))
    request = next((e for e in events if e[1] == 'REQUEST_API' and e[2].get('n') == '0'), None)
    consume = next((e for e in events if e[1] == 'CONSUME' and e[2].get('n') == '0'), None)
    execution = next((e for e in events if e[1] == 'RUN' and e[2].get('n') == '0'), None)
    if not request or not consume or not execution or not request[0] < consume[0] < execution[0]:
        raise ValueError('First original request, consume and run were not observed in order')
    if consume[2].get('bytes') != '8' or int(consume[2].get('id', '0'), 0) != 0x4dc:
        raise ValueError('Consumed original request identity was not read back')
    if request[2].get('flag') != '1' or consume[2].get('flag') != '1' or request[2].get('callback') != '0':
        raise ValueError('Original request flags or callback differ from the observed boot subset')
    return {'original_display_setup_sequence_observed': True, 'run': run.name,
            'scope': 'first natural request API, dedicated consumption thunk and run entry only',
            'events': [{'line': n, 'stage': stage, **fields} for n, stage, fields in (request, consume, execution)],
            'console_sha256': hashlib.sha256(console).hexdigest(),
            'observer_sha256': observer_sha,
            'display_setup_completion_verified': False, 'liveview_pixels_consumed': False,
            'capture_verified': False, 'movie_verified': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    args = parser.parse_args()
    try:
        result = verify(args.run)
    except (OSError, ValueError, KeyError, TypeError) as error:
        result = {'original_display_setup_sequence_observed': False, 'error': str(error),
                  'display_setup_completion_verified': False, 'liveview_pixels_consumed': False,
                  'capture_verified': False, 'movie_verified': False}
    (args.run / 'display-setup-sequence-proof.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, sort_keys=True))
    return 0 if result['original_display_setup_sequence_observed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
