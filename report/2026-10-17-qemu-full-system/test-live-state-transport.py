"""Transport/semantic/offline host tests. No guest commands or VM are executed."""
import base64
import copy
import hashlib
import json
import os
from pathlib import Path
import runpy
import shlex
import subprocess
import time
from types import SimpleNamespace
import pytest
from host_transport_fixture import proof_bytes, wire_bytes, fixture_transport
HERE=Path(__file__).resolve().parent
A=runpy.run_path(str(HERE/'retained-camera-live.py'))
G=A['sample_live_state'].__globals__
F=runpy.run_path(str(HERE/'test-retained-camera-test.py'))
LIVE=runpy.run_path(str(HERE/'test-retained-camera-live.py'))
content_fixture=LIVE['content_fixture']
TOKEN='a'*32
NONCE='b'*32
PRIVATE_FAILURE_RAW = os.environ.get('A7C2_STATE_FAILURE_RAW')
if PRIVATE_FAILURE_RAW:
    RAW = Path(PRIVATE_FAILURE_RAW).read_bytes()
else:
    # Synthetic state with the exact observed printk splice; no private console is shipped.
    RAW = F['state_text']('menu', TOKEN).encode().replace(
        b'RETAINED_VIEWER_STATUS_END',
        b'[   45.069485] [K]**UIPC ERROR** osal_snd_msg: No snd_msg regisRETAINED_VIEWER_STATUS_ENDte\n'
        b'red. Skip snd to 0x8fc\n'
        b'[   45.070046] [K]**UIPC ERROR** osal_snd_msg: No snd_msg registered. Skip snd to 0x83f')

def spec(phase='menu'):
    return A['state_spec'](phase,TOKEN,NONCE,phase=='ready')

def sample(s=None):
    s=spec() if s is None else s
    phase='source' if s['phase']=='ready' else s['phase']
    body=F['state_text'](phase,s['token']).replace('=source\n','=ready\n') if s['phase']=='ready' else F['state_text'](phase,s['token'])
    return proof_bytes(A,s,body)

def test_interleaved_state_is_rejected_and_intact_wire_survives_it():
    assert b'No snd_msg regisRETAINED_VIEWER_STATUS_ENDte' in RAW
    assert b'0x8fc' in RAW and b'0x83f' in RAW
    with pytest.raises(ValueError,match='exact guest section'):
        A['R']['parse_state'](RAW.decode('utf-8',errors='replace').replace('\r',''),'menu')
    proof=sample()
    full=RAW+wire_bytes(A,spec(),proof)
    assert full.startswith(RAW)
    assert A['decode_state_transfer'](full,spec(),0)==proof
    assert A['review_state_file'](proof,spec())['ap_pids']==['31']
    # The decoder never guesses clean bytes from the interrupted original state.
    with pytest.raises(ValueError): A['decode_state_transfer'](RAW,spec(),0)

@pytest.mark.parametrize('damage',['missing','duplicate','offset','hash','nonce','meta-nonce','end-nonce','base64','code','sourceapsha','actualapsha','uid','gid','frame','canary','missingmarker','repeatedmarker','done','double-done','domain'])
def test_decoder_or_semantic_rejects_even_rehashed_damage(damage):
    s=spec(); proof=sample(s)
    if damage in ('code','sourceapsha','actualapsha','domain'):
        key={'code':b'code_sha256=', 'sourceapsha':b'sourceap_sha256=', 'actualapsha':b'SHA256(/usr/lib/appFw.so)= ', 'domain':b'domain='}[damage]
        index=proof.index(key)+len(key)
        proof=proof[:index]+b'X'+proof[index+1:]
    elif damage in ('uid','gid'):
        proof=proof.replace((damage.capitalize()+': 0 0 0 0').encode(),(damage.capitalize()+': 1 0 0 0').encode())
    elif damage=='canary': proof=proof.replace(b'RETAINED_CANARY='+TOKEN.encode(),b'RETAINED_CANARY='+b'c'*32)
    elif damage=='frame': proof=proof.replace(b'RETAINED_FRAME_HEADER=',b'RETAINED_FRAME_BROKEN=')
    elif damage=='missingmarker': proof=proof.replace(b'\nRETAINED_VIEWER_STATUS_END\n',b'\n')
    elif damage=='repeatedmarker': proof=proof.replace(b'\nRETAINED_VIEWER_STATUS_END\n',b'\nRETAINED_VIEWER_STATUS_END\nRETAINED_VIEWER_STATUS_END\n')
    wire=wire_bytes(A,s,proof); lines=wire.splitlines(keepends=True)
    if damage=='missing': del lines[2]; wire=b''.join(lines)
    elif damage=='duplicate': wire=b''.join(lines[:2]+[lines[1]]+lines[2:])
    elif damage=='offset': wire=wire.replace(b'offset=0 ',b'offset=1 ',1)
    elif damage=='hash': wire=wire.replace(hashlib.sha256(proof).hexdigest().encode(),b'0'*64)
    elif damage in ('nonce','meta-nonce','end-nonce'):
        index={'nonce':1,'meta-nonce':0,'end-nonce':-2}[damage]
        lines[index]=lines[index].replace(NONCE.encode(),b'c'*32); wire=b''.join(lines)
    elif damage=='base64': wire=wire.replace(b'data=',b'data=!',1)
    elif damage=='done': wire=wire.replace(b'attempt=0 rc=0',b'attempt=0 rc=1')
    elif damage=='double-done': wire+=lines[-1]
    with pytest.raises(ValueError):
        A['review_state_file'](A['decode_state_transfer'](RAW+wire,s,0),s)

@pytest.mark.parametrize('size',[1,191,192,193,4097,65536])
def test_real_host_sh_openssl_exact_transport_bytes(tmp_path,size):
    payload=bytes(i%256 for i in range(size))
    path=tmp_path/'host-proof'; path.write_bytes(payload)
    s=spec(); host_spec=dict(s,guest_file=str(path))
    script='busybox() { "$@"; }\n'+A['state_command'](A['state_transfer_script'](host_spec,0),host_spec,0)
    result=subprocess.run(['/bin/sh','-x'],input=script.encode(),capture_output=True,timeout=10)
    assert result.returncode==0 and b'rc=0\n' in result.stdout,result.stderr
    assert result.stdout==wire_bytes(A,host_spec,payload)
    assert A['decode_state_transfer'](result.stdout,host_spec,0)==payload
    assert result.stderr.count(b'/usr/bin/openssl enc -base64 -in ')==1
    assert result.stderr.count(b'/usr/bin/openssl dgst -sha256 ')==2
    assert path.read_bytes()==payload

@pytest.fixture
def sampler(tmp_path,monkeypatch):
    log=tmp_path/'console'; log.write_bytes(b'original raw prefix\n'); log.chmod(0o600)
    owner=F['Owner'](123)
    calls=[]; session=SimpleNamespace(output=tmp_path,token=TOKEN,tx=object(),state_transports={},state_deadline=time.monotonic()+60)
    session.unchanged=lambda: calls.append('anchor')
    monkeypatch.setattr(A['secrets'],'token_hex',lambda n:NONCE)
    monkeypatch.setitem(A['R'],'authenticate_owner',lambda *a:calls.append('owner'))
    monkeypatch.setitem(A['R'],'wait_for',lambda owner,path,condition,seconds: condition(A['R']['console'](path)) or (_ for _ in ()).throw(TimeoutError('host incomplete')))
    return SimpleNamespace(log=log,owner=owner,session=session,calls=calls)

@pytest.mark.parametrize('failure',['syntax','uid','foreignPID','hash','nonce','code','sourceapsha','frame','canary','owner','lease','deadline','changed-file','nonzero'])
def test_only_file_transport_retry_never_replays_input(sampler,monkeypatch,failure):
    f=sampler; s=spec(); proof=sample(s); commands=[]
    if failure=='uid': proof=proof.replace(b'Uid: 0 0 0 0',b'Uid: 7 0 0 0')
    if failure=='foreignPID': proof=proof.replace(b'RETAINED_APP_PID=31',b'RETAINED_APP_PID=999')
    if failure=='deadline': f.session.state_deadline=time.monotonic()-1
    if failure=='code': proof=proof.replace(b'code_sha256=',b'bad_code_sha256=')
    if failure=='sourceapsha': proof=proof.replace(b'SHA256(/usr/lib/appFw.so)= ',b'SHA256(/wrong)= ')
    if failure=='frame': proof=proof.replace(b'RETAINED_FRAME_HEADER=',b'RETAINED_FRAME_INVALID=')
    if failure=='canary': proof=proof.replace(b'RETAINED_CANARY='+TOKEN.encode(),b'RETAINED_CANARY='+b'c'*32)
    if failure=='lease': f.session.unchanged=lambda: (_ for _ in ()).throw(ValueError('lease changed'))
    if failure=='owner': monkeypatch.setitem(A['R'],'authenticate_owner',lambda *a: (_ for _ in ()).throw(ValueError('owner changed')))
    def write(stream,envelope):
        commands.append(envelope)
        n=len(commands)-1
        if b'busybox rm -f' in envelope:
            _,clean=A['state_cleanup_script'](s,hashlib.sha256(proof).hexdigest())
            raw=(clean+'\n'+A['state_done'](s,2)+'\n').encode()
        else:
            data=proof+(b'X' if failure=='changed-file' and n else b'')
            raw=wire_bytes(A,s,data,n)
            if n==0 and failure in ('syntax','changed-file'):
                lines=raw.splitlines(keepends=True); del lines[2]; raw=b''.join(lines)
            if failure=='hash': raw=raw.replace(hashlib.sha256(proof).hexdigest().encode(),b'0'*64)
            if failure=='nonce': raw=raw.replace(b'nonce='+NONCE.encode()+b' offset=0',b'nonce='+b'c'*32+b' offset=0')
            if failure=='nonzero': raw=raw.replace(b'rc=0\n',b'rc=1\n')
            if n==0: raw=F['input_text']('menu').encode()+raw
        with f.log.open('ab') as out: out.write(raw)
    monkeypatch.setitem(A['E'],'write_console',write)
    if failure=='syntax':
        state,observed=A['sample_live_state'](f.session,f.owner,None,f.log,'menu')
        assert state['ap_pids']==['31'] and A['R']['review_input'](observed,'menu')['received_edges']==2
        assert len(commands)==3
        manifest=json.loads((f.session.output/'menu-state-transport.json').read_bytes())
        assert len(manifest['attempts'])==2
        def raw(name): return (f.session.output/name).read_bytes()
        value,_=A['replay_live_state'](f.session.output,'menu',TOKEN,f.log.read_bytes(),123,f.session.state_transports['menu'],raw)
        assert value==state and raw('menu-state-transport.proof')==proof
    else:
        with pytest.raises(ValueError): A['sample_live_state'](f.session,f.owner,None,f.log,'menu')
        assert len(commands)==(0 if failure in ('lease','owner','deadline') else 2 if failure=='changed-file' else 1)
        assert not f.session.state_transports
    if commands:
        assert commands[0].count(b'/simulation/inject-key ')==2
        for command in commands[1:]:
            assert b'/simulation/inject-key ' not in command and b'RETAINED_STATE_BEGIN=' not in command
            assert b'/proc/' not in command and b'echo RETAINED_CANARY=' not in command
        assert sum(command.count(b'/simulation/inject-key ') for command in commands)==2
    assert f.owner.poll() is None

@pytest.mark.parametrize('damage',['repeat-done','offset','proof','binding','legacy-done','owner','sourceapsha','code','duplicate-attempt','retry-after-success','unbound-input'])
def test_offline_closed_full_verifier_reparses_bound_transport(content_fixture,damage):
    f=content_fixture
    assert A['verify_result'](A['binding'](f.output/'result.json'),f.instance,f.controller)['owners_closed']
    name=f.output/'menu-state-transport.json'; receipt=json.loads(name.read_bytes())
    if damage=='unbound-input':
        target=f.output/'transaction/target/console.log'
        at=receipt['begin']; extra=F['input_text']('menu').encode()
        target.write_bytes(target.read_bytes()[:at]+extra+target.read_bytes()[at:])
        result=A['DEV']['read_json'](f.output/'result.json')
        for phase in ('menu','shooting'):
            path=f.output/(phase+'-state-transport.json'); row=A['DEV']['read_json'](path)
            for key in ('begin','end','cleanup_begin'): row[key]+=len(extra)
            for attempt in row['attempts']:
                attempt['begin']+=len(extra); attempt['end']+=len(extra)
            A['DEV']['write_json'](path,row); result['state_transports'][phase]=A['binding'](path)
        A['DEV']['write_json'](f.output/'result.json',result)
    elif damage in ('repeat-done','legacy-done'):
        path=f.output/'transaction/target/console.log'
        suffix=A['state_done'](receipt['spec'],0) if damage=='repeat-done' else 'RETAINED_DONE_menu='+receipt['spec']['token']
        with path.open('ab') as out: out.write((suffix+'\n').encode())
    elif damage=='proof':
        path=f.output/'menu-state-transport.proof'; path.write_bytes(path.read_bytes()+b'X')
    elif damage=='binding': receipt['sample']['sha256']='0'*64
    elif damage=='offset': receipt['begin']+=1
    elif damage=='owner': receipt['owner_pid']+=1
    elif damage in ('code','sourceapsha'): receipt['spec'][{'code':'code_sha256','sourceapsha':'sourceap_sha256'}[damage]]='0'*64
    elif damage in ('duplicate-attempt','retry-after-success'): receipt['attempts']*=2
    if damage not in ('repeat-done','legacy-done','proof','unbound-input'):
        A['DEV']['write_json'](name,receipt)
        result=A['DEV']['read_json'](f.output/'result.json'); result['state_transports']['menu']=A['binding'](name)
        A['DEV']['write_json'](f.output/'result.json',result)
    with pytest.raises(ValueError): A['verify_result'](A['binding'](f.output/'result.json'),f.instance,f.controller)

def test_protected_sources_and_bindings_and_shared_budget():
    assert len(A['SOURCE_BINDINGS'])==14
    bindings = {Path(row['path']).name: row for row in A['SOURCE_BINDINGS']}
    for name in ('retained-camera-test.py','newretained-camera-execution.py','retained-disk-state.py','retained-camera-launch.py','boot-execution.py','low-latency-input.py','retained-camera-frontend.py'):
        assert bindings[name]['sha256'] == hashlib.sha256((HERE/name).read_bytes()).hexdigest()
    for phase in ('ready','source','restored','menu','shooting'):
        s=spec(phase)
        for script in (A['state_sample_script'](s),A['state_transfer_script'](s,1)):
            assert script.encode('ascii') and max(map(len,script.splitlines()))<=512
            result=subprocess.run(['/bin/sh','-n'],input=A['state_command'](script,s,0).encode(),capture_output=True)
            assert result.returncode==0,result.stderr
    source=(HERE/'retained-camera-live.py').read_text()
    assert 'self.state_deadline = time.monotonic() + 60' in source
    assert 'busybox sleep 0.05\n' in A['R']['MENU']
