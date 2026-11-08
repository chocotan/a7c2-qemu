"""Read original Sony exception-monitor state without resuming the firmware."""
import hashlib
import json
import math
from pathlib import Path
import re
import time

COMMANDS=('reg','call')


def memory_queries(registers):
    queries=[]
    for name,label in (('pc','code'),('sp','stack')):
        match=re.search(rb'\b'+name.encode()+rb':\s*(0x[0-9a-fA-F]+)',registers)
        if not match:continue
        address=int(match[1],16)
        if not 0x10000<=address<0x1000000000000:continue
        page=address&~4095
        start=max(page,(address&~15)-(32 if name=='pc' else 0))
        size=min(128,page+4096-start)
        # The captured 2.01 monitor counts four-byte units even for dq.
        queries.append((label,'dq '+hex(start)+' '+hex(size//4)))
    return queries


def collect_exception(process,run,*,per_command_seconds=2):
    if type(per_command_seconds) not in (int,float) or not math.isfinite(per_command_seconds) or not 0<per_command_seconds<=5:
        raise ValueError('Bounded exception diagnostic deadline required')
    run=Path(run);console=run/'console.log';output=run/'exception-diagnostics.json'
    if output.exists():return json.loads(output.read_bytes())
    before=console.read_bytes()
    result=dict(schema='a7c2-original-exception-readonly-diagnostics-v1',available=False,
                firmware_resumed=False,memory_or_registers_written=False,commands=[],
                original_console_before_sha256=hashlib.sha256(before).hexdigest())
    if b'Exception> ' not in before:
        result['reason']='No original exception prompt observed'
    elif getattr(process,'_app_input_transport',None) is not None:
        result['reason']='Active foreground input still owns serial; no diagnostic bytes sent'
    elif process.poll() is not None:
        result['reason']='Original guest owner already exited'
    else:
        queries=[(name,name) for name in COMMANDS]
        for label,command in queries:
            offset=len(console.read_bytes());started=time.monotonic()
            for byte in (command+'\r').encode('ascii'):
                process.stdin.write(bytes([byte]));process.stdin.flush();time.sleep(.01)
            deadline=time.monotonic()+per_command_seconds;data=b''
            while time.monotonic()<deadline:
                data=console.read_bytes()[offset:]
                if b'Exception> ' in data or process.poll() is not None:break
                time.sleep(.02)
            raw_path=run/('exception-'+label+'.raw');raw_path.write_bytes(data)
            complete=b'Exception> ' in data and b'Command not found' not in data
            content=(len(re.findall(rb'\b[xXrR][0-9]{1,2}\s*[:=]\s*(?:0x)?[0-9a-fA-F]{8,16}',data))>=2 if command=='reg' else bool(re.search(rb'(?:0x|\[)[0-9a-fA-F]{8,16}',data)))
            if command.startswith('dq '):content=bool(re.search(rb'[0-9a-fA-F]{8,16}\s*:\s+[0-9a-fA-F]{16}\s+[0-9a-fA-F]{16}',data)) and b'Bad data address' not in data
            if command=='reg' and complete and content:queries.extend(memory_queries(data))
            result['commands'].append(dict(command=command,label=label,reply_complete=complete,content_observed=content,
                elapsed_seconds=time.monotonic()-started,raw_bytes=len(data),
                raw_sha256=hashlib.sha256(data).hexdigest()))
            if not complete:break
        result['available']=len(result['commands'])>=2 and all(x['reply_complete'] and x['content_observed'] for x in result['commands'][:2])
        result['memory_samples_complete']=len(result['commands'])==4 and all(x['reply_complete'] and x['content_observed'] for x in result['commands'][2:])
        if not result['available']:result['reason']='Original monitor reply missing; raw bytes preserved'
    result['original_console_after_sha256']=hashlib.sha256(console.read_bytes()).hexdigest()
    output.write_text(json.dumps(result,indent=2)+'\n')
    return result
