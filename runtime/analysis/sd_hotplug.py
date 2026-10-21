"""Typed SD hotplug control over the existing serialized guest channel."""
import json
from pathlib import Path
import re
import time

STATES = ('unavailable', 'present', 'ejecting', 'absent', 'inserting', 'uncertain')
PATTERN = (rb'^SD_HOTPLUG v=1 pid=([1-9][0-9]*) sequence=([0-9]+) generation=([0-9]+) '
           rb'state=([a-z]+) drive=([0-9]+) result=([0-9]+) port=([0-9]+) lost=([01])\r?$')


def parse(raw):
    matches = re.findall(PATTERN, raw, re.M)
    if len(matches) != 1:
        raise ValueError('Missing or ambiguous SD worker status')
    pid, sequence, generation, state, drive, result, port, lost = matches[0]
    state = state.decode('ascii')
    values = dict(pid=int(pid), sequence=int(sequence), generation=int(generation), state=state,
                  drive=int(drive), result=int(result), port=int(port), lost=bool(int(lost)))
    if (values['pid'] <= 1 or state not in STATES or values['sequence'] >= 2**63
            or values['generation'] >= 2**64 or values['drive'] > 255 or values['port'] > 255
            or values['result'] > 15):
        raise ValueError('Invalid SD worker status fields')
    return values


class SDHotplug:
    def __init__(self, serial, run, timeout=45):
        self.serial = serial
        self.run = Path(run)
        self.timeout = timeout
        self.sequence = 0
        self.owner = None
        self.pending_request = None
        self.observed_state = None

    def input_blocked(self):
        return self.pending_request is not None or self.observed_state in ('ejecting','inserting','uncertain')

    def status(self):
        raw = self.serial('cat /tmp/sd-hotplug.state; true')
        if not re.search(rb'^SD_HOTPLUG ', raw, re.M):
            return {'type': 'sd_card', 'ok': False, 'state': 'unavailable',
                    'error': 'Original mount has not bound the SD worker'}
        state = parse(raw)
        if self.owner is None:
            self.owner = state['pid']
        if state['pid'] != self.owner:
            raise RuntimeError('SD worker owner changed during the session')
        observed = {'type': 'sd_card', 'ok': state['state'] in ('present', 'absent') and not state['lost'], **state}
        self.observed_state = state['state']
        pending = self.pending_request
        if pending is None:
            return observed
        matches = state['sequence'] == pending['sequence']
        if matches and observed['ok']:
            if ((state['state'] == pending['wanted'] and state['result'] == 0)
                    or state['result'] in (6,7,8,9,10,11,13,15)):
                self.pending_request = None
                return observed
        if matches and state['state'] in ('ejecting','inserting','uncertain'):
            return observed
        return {**observed, 'ok': False, 'state': 'uncertain', 'worker_state': state['state'],
                'pending_sequence': pending['sequence'],
                'error': 'Pending SD request has no matching terminal observation'}

    def set_present(self, present):
        if type(present) is not bool:
            raise ValueError('SD present must be a boolean')
        before = self.status()
        if not before.get('ok'):
            return before
        wanted = 'present' if present else 'absent'
        if before['state'] == wanted:
            return {**before, 'requested_present': present, 'already': True}
        sequence = max(self.sequence + 1, before['sequence'] + 1, time.monotonic_ns())
        self.sequence = sequence
        operation = 1 if present else 0
        self.pending_request = {'sequence': sequence, 'wanted': wanted}
        self.serial(f'echo "1 {sequence} {operation}" > /tmp/sd-hotplug.request.new')
        self.serial('mv /tmp/sd-hotplug.request.new /tmp/sd-hotplug.request')
        deadline = time.monotonic() + self.timeout
        history = []
        while True:
            state = self.status()
            marker = (state.get('sequence'), state['state'], state.get('result'))
            if not history or history[-1]['marker'] != list(marker):
                history.append({'marker': list(marker), 'status': state})
            if state.get('sequence') == sequence:
                if state['state'] == wanted and state['ok'] and state['result'] == 0:
                    return self._finish({**state, 'requested_present': present,
                                         'history': history, 'ok': True})
                if state['state'] == 'uncertain' or state.get('result') not in (0, 3):
                    return self._finish({**state, 'requested_present': present, 'history': history,
                                         'ok': False, 'error': 'SD transition did not complete'})
            if time.monotonic() >= deadline:
                return self._finish({**state, 'requested_present': present, 'history': history,
                                     'ok': False, 'state': 'uncertain',
                                     'error': 'SD observation deadline exceeded; do not retry or reverse automatically'})
            time.sleep(.1)

    def _finish(self, result):
        result['capture_verified'] = False
        (self.run/'sd-hotplug-latest.json').write_text(json.dumps(result, indent=2)+'\n')
        with (self.run/'sd-hotplug-events.jsonl').open('a') as events:
            events.write(json.dumps(result)+'\n')
        return result
