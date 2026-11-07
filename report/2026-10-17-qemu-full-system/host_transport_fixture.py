"""Explicit synthetic host evidence, never original guest state reconstruction."""
import base64
import hashlib
from pathlib import Path

def proof_bytes(api, spec, body):
    begin, end = api['state_file_markers'](spec)
    done = 'RETAINED_DONE_' + spec['phase'] + '=' + spec['token']
    if done not in body.splitlines():
        body += done + '\n'
    return (begin+'\nSHA256(/usr/lib/appFw.so)= '+spec['sourceap_sha256']+'\n'+body+end+'\n').encode('ascii')

def wire_bytes(api, spec, proof, attempt=0):
    meta = api['state_identity'](spec)+' bytes='+str(len(proof))+' sha256='+hashlib.sha256(proof).hexdigest()
    lines = ['RETAINED_LIVE_META '+meta]
    lines += ['RETAINED_LIVE_CHUNK nonce='+spec['nonce']+' offset='+str(n)+' data='+base64.b64encode(proof[n:n+192]).decode('ascii') for n in range(0,len(proof),192)]
    lines += ['RETAINED_LIVE_END '+meta, api['state_done'](spec, attempt)]
    return ('\n'.join(lines)+'\n').encode('ascii')

def fixture_transport(api, output, phase, token, body, full, owner_pid, input_text=''):
    spec = api['state_spec'](phase, token, hashlib.sha256(('host-fixture-'+phase).encode()).hexdigest()[:32], phase=='ready')
    proof = proof_bytes(api,spec,body)
    first = input_text.encode()+wire_bytes(api,spec,proof)
    _, clean = api['state_cleanup_script'](spec,hashlib.sha256(proof).hexdigest())
    cleanup = (clean+'\n'+api['state_done'](spec,2)+'\n').encode()
    begin, middle = len(full), len(full)+len(first)
    trace = first+cleanup
    full.extend(trace)
    stem = phase+'-state-transport'
    api['R']['save_bytes'](output/(stem+'.raw'),trace)
    api['R']['save_bytes'](output/(stem+'.proof'),proof)
    receipt = dict(schema=api['STATE_DOMAIN'],spec=spec,owner_pid=owner_pid,
        log='transaction/source-console.log' if phase in ('ready','source') else 'transaction/target/console.log',begin=begin,end=len(full),
        attempts=[dict(begin=begin,end=middle,command_sha256=hashlib.sha256(api['state_command'](api['state_sample_script'](spec),spec,0).encode()).hexdigest())],cleanup_begin=middle,
        trace=api['binding'](output/(stem+'.raw')),sample=api['binding'](output/(stem+'.proof')))
    api['R']['save'](output/(stem+'.json'),receipt)
    return api['binding'](output/(stem+'.json'))

def upgrade_fixture(api, output, result, rfix):
    token = result['source_run'].removeprefix('retained-source-')
    oldsource = (output/'transaction/source-console.log').read_text()
    oldtarget = (output/'transaction/target/console.log').read_text()
    source = bytearray((output/'source-cold-trace.log').read_bytes())
    target = bytearray()
    captured = api['DEV']['read_json'](output/'capture-result.json')
    restored = api['DEV']['read_json'](output/'restore-paused-result.json')
    bindings = {}
    for phase in ('ready','source','restored','menu','shooting'):
        original_phase = 'source' if phase=='ready' else phase
        old = oldsource if original_phase=='source' else oldtarget
        body = ('RETAINED_STATE_BEGIN='+original_phase+'\n'+api['R']['section'](old,'RETAINED_STATE_BEGIN='+original_phase,'RETAINED_STATE_END='+original_phase)+
                'RETAINED_STATE_END='+original_phase+'\n').replace('=source\n','=ready\n') if phase=='ready' else (
                'RETAINED_STATE_BEGIN='+phase+'\n'+api['R']['section'](old,'RETAINED_STATE_BEGIN='+phase,'RETAINED_STATE_END='+phase)+'RETAINED_STATE_END='+phase+'\n')
        owner = (captured['source_identity'] if phase in ('ready','source') else restored['target_identity'])['owner']['pid']
        bindings[phase] = fixture_transport(api,output,phase,token,body,source if phase in ('ready','source') else target,owner,
                                          rfix['input_text'](phase) if phase in ('menu','shooting') else '')
        if phase=='ready':
            api['R']['save'](output/'ready-state.json',api['R']['parse_state'](body,'ready'))
    marker='A7C2_RETAINED_GUEST_SYNC nonce='+captured['guest_sync']['nonce']+' sync_rc=0\n'
    source.extend(marker.encode())
    for name,value in (('transaction/source-console.log',source),('transaction/guest-sync.console',source),('transaction/target/console.log',target)):
        (output/name).write_bytes(value)
    result['state_transports']=bindings


def legacy_orchestration_fixture(api, obj, owner, qmp, log, phase, create=False):
    # Existing orchestration tests keep their old shell seam; codec tests use the real new helper.
    prefix=api['R']['MENU'] if phase in ('menu','shooting') else 'busybox sleep 1\n' if phase in ('source','restored') else ''
    observed=api['R']['shell'](owner,log,prefix+api['R']['state_script'](phase,obj.token,create),phase,obj.token)
    return api['R']['parse_state'](observed,phase),observed
