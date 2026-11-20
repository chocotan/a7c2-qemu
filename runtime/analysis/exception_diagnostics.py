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
    if not (before==b'Exception> ' or before.endswith(b'\nException> ')):
        result['reason']='No current original exception prompt observed'
    elif getattr(process,'_menu_serial_desynchronized',False):
        result['reason']='Serial transaction boundary is unknown; no diagnostic bytes sent'
    elif getattr(process,'_app_input_transport',None) is not None:
        result['reason']='Active foreground input still owns serial; no diagnostic bytes sent'
    elif process.poll() is not None:
        result['reason']='Original guest owner already exited'
    else:
        queries=[(name,name) for name in COMMANDS]
        for label,command in queries:
            offset=len(console.read_bytes());started=time.monotonic()
            process._menu_serial_desynchronized=True
            # shortcut: accept only v17/v25 CR CR LF echoes; add framing only with original raw evidence.
            echo=command.encode('ascii')+b'\r\r\n';prompt=b'\r\nException> '
            def framed_reply(data):
                return data.startswith(echo) and data.endswith(prompt) and b'Exception> ' not in data[:-len(prompt)]
            data=b'';framed=False
            try:
                for byte in (command+'\r').encode('ascii'):
                    if process.stdin.write(bytes([byte]))!=1:raise OSError('Short exception-monitor write')
                    process.stdin.flush();time.sleep(.01)
                deadline=time.monotonic()+per_command_seconds
                while time.monotonic()<deadline:
                    data=console.read_bytes()[offset:]
                    if framed_reply(data):
                        framed=time.monotonic()<deadline
                        break
                    if process.poll() is not None:break
                    time.sleep(.02)
            finally:
                data=console.read_bytes()[offset:]
                raw_path=run/('exception-'+label+'.raw');raw_path.write_bytes(data)
            framed=framed and framed_reply(data)
            body=data[len(echo):-len(prompt)] if framed else b''
            complete=framed and b'Command not found' not in body and b'Bad data address' not in body
            content=(len(re.findall(rb'\b[xXrR][0-9]{1,2}\s*[:=]\s*(?:0x)?[0-9a-fA-F]{8,16}',body))>=2 if command=='reg' else bool(re.search(rb'(?:0x|\[)[0-9a-fA-F]{8,16}',body)))
            if command.startswith('dq '):content=bool(re.search(rb'[0-9a-fA-F]{8,16}\s*:\s+[0-9a-fA-F]{16}\s+[0-9a-fA-F]{16}',body)) and b'Bad data address' not in body
            if complete and content:process._menu_serial_desynchronized=False
            if command=='reg' and complete and content:queries.extend(memory_queries(body))
            result['commands'].append(dict(command=command,label=label,reply_complete=complete,content_observed=content,
                elapsed_seconds=time.monotonic()-started,raw_bytes=len(data),
                raw_sha256=hashlib.sha256(data).hexdigest()))
            if not (complete and content):break
        result['available']=len(result['commands'])>=2 and all(x['reply_complete'] and x['content_observed'] for x in result['commands'][:2])
        result['memory_samples_complete']=len(result['commands'])==4 and all(x['reply_complete'] and x['content_observed'] for x in result['commands'][2:])
        if not result['available']:result['reason']='Original monitor reply missing; raw bytes preserved'
    result['original_console_after_sha256']=hashlib.sha256(console.read_bytes()).hexdigest()
    output.write_text(json.dumps(result,indent=2)+'\n')
    return result
