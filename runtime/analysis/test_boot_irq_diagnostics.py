import json
from boot_irq_diagnostics import capture,REGIONS


def test_diagnostics_never_ack_irq_consume_uart_or_change_cpu_state(tmp_path):
    calls=[]
    def qmp(command,args=None):
        calls.append((command,args))
        assert command in ('query-status','query-cpus-fast','human-monitor-command','pmemsave','qom-list','qom-get')
        if command=='qom-list':return {'return':[{'name':'device[2]','type':'child<arm_gic>'}]}
        if command=='qom-get':
            assert args=={'path':'/machine/unattached/device[2]','property':'sony-debug-state'}
            return {'return':json.dumps(dict(schema='sony-gic-readback-v1',observations_only=True))}
        if command=='human-monitor-command':assert args=={'command-line':'info registers -a'}
        if command=='pmemsave':
            for destructive in (0x09000000,0x0801000c,0x08010010):
                assert not args['val']<=destructive<args['val']+args['size']
            (tmp_path/args['filename'].removeprefix('/out/')).write_bytes(bytes(args['size']))
        return {'return':{}}
    result=capture(qmp,tmp_path)
    assert result['observations_only'] and len(calls)==len(REGIONS)+5
    assert result['gic']['state']['observations_only']
    assert all('hex' in record for record in result['registers'].values())


def test_capture_failure_is_evidence_and_does_not_stop_other_reads(tmp_path):
    def qmp(command,args=None):
        if command!='pmemsave' or args['val']==0x09000018:raise RuntimeError('test failure')
        (tmp_path/args['filename'].removeprefix('/out/')).write_bytes(bytes(args['size']))
        return {'return':{}}
    result=capture(qmp,tmp_path)
    assert 'error' in result['status'] and 'error' in result['registers']['uart-flags']
    assert 'hex' in result['registers']['uart-interrupts']
