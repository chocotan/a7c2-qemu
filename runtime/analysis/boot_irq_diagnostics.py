"""Bounded, non-acknowledging UART/GIC readbacks after a failed boot round trip."""
import json

# SMP GIC MMIO calls gic_get_current_cpu(); monitor-thread physical reads have
# no vCPU context. Do not use pmemsave for that controller.
REGIONS=(('uart-flags',0x09000018,4),('uart-interrupts',0x09000034,16))


def gic_state(qmp):
    children=qmp('qom-list',{'path':'/machine/unattached'})['return']
    paths=['/machine/unattached/'+child['name'] for child in children
           if child['type']=='child<arm_gic>']
    if len(paths)!=1:raise ValueError('No unique TCG GICv2 object')
    raw=qmp('qom-get',{'path':paths[0],'property':'sony-debug-state'})['return']
    state=json.loads(raw)
    if state.get('schema')!='sony-gic-readback-v1' or state.get('observations_only') is not True:
        raise ValueError('Unexpected GIC observation schema')
    return dict(path=paths[0],state=state)


def capture(qmp,run):
    result=dict(observations_only=True,registers={})
    for name,command,args in (('status','query-status',None),('cpus','query-cpus-fast',None),
                            ('cpu_registers','human-monitor-command',{'command-line':'info registers -a'})):
        try:result[name]=qmp(command,args)
        except Exception as error:result[name]=dict(error=str(error))
    try:result['gic']=gic_state(qmp)
    except Exception as error:result['gic']=dict(error=str(error))
    for name,address,size in REGIONS:
        filename=f'boot-{name}.bin'
        record=dict(physical_address=hex(address),bytes=size)
        try:
            qmp('pmemsave',dict(val=address,size=size,filename='/out/'+filename))
            raw=(run/filename).read_bytes()
            if len(raw)!=size:raise ValueError('Short boot register snapshot')
            record['hex']=raw.hex()
        except Exception as error:record['error']=str(error)
        result['registers'][name]=record
    (run/'boot-irq-diagnostics.json').write_text(json.dumps(result,indent=2)+'\n')
    return result
