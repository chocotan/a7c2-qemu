import struct
import pytest
from ee_entry_snapshot import collect_passive, collect_group0


@pytest.mark.parametrize('common_only',[False,True])
def test_actual_passive_collection_uses_only_proc_and_readmem(tmp_path,common_only):
    base=0x7f00000000;sp=0x7ffff000;calls=[]
    def serial(command):
        calls.append(command)
        assert not any(token in command for token in ('menu-regs','kill','ptrace','SIGSTOP','echo 1 >'))
        if command.startswith('for p '):return b'EE_AP_MAP=/proc/42\n'
        if command=='cat /proc/42/maps':return b'7f00000000-7f051a7000 r-xp 00000000 00:01 10 /usr/lib/appFw.so\n'
        if command.startswith('for t '):
            return (b'EE_THREAD=44:SeqQueueCommon\nEE_THREAD=45:SeqThreadPool0\n'
                    b'EE_THREAD=43:UDATE_ASYNCSET\nEE_THREAD=42:mwf_monitor_inp\n'
                    b'EE_THREAD=49:IWrapperMwfInh\n'
                    b'EE_THREAD=71:AppBackupDaemon\n'
                    b'EE_THREAD=46:ExternalOSDIF\nEE_THREAD=47:grm_result\nEE_THREAD=48:grm_gpe\n'+
                    b''.join(f'EE_THREAD={tid}:SeqThreadPool{tid}\n'.encode() for tid in range(50,70)))
        if '/status' in command:return b'Name:\tSeqQueueCommon\nState:\tS (sleeping)\nTracerPid:\t0\n'
        if '/syscall' in command:
            return f'98 0x0 0x1 0x2 0x3 0x4 0x5 {sp:#x} {base+0x310194c:#x}\n'.encode()
        if '/wchan' in command:return b'futex_wait_queue_me\n'
        if command.endswith('/stack; true'):return b'[<0>] udate_wait_for_distribution_done+0x70/0x90\n'
        if 'kallsyms' in command:return b'0000000000000000 t udate_wait_for_distribution_done [udate]\n'
        if '4096' in command:
            data=struct.pack('<Q',base+0x339fa8c)+bytes(4088)
            return (f'READMEM /proc/42/mem address={sp:x} bytes=4096\n'+
                ''.join(f'{sp+i:016x}:'+''.join(f' {x:02x}' for x in data[i:i+16])+'\n' for i in range(0,4096,16))).encode()
        if ' 1 appFw.so' in command:return b'0000007f08838af8: 01\n'
        if '4 appFw.so' in command:return b'0000007f07e67700: 00 00 00 00\n'
        raise AssertionError(command)
    proof=collect_passive(serial,tmp_path,common_only=common_only)
    assert proof['threads_not_stopped'] and proof['sampled_threads']==(1 if common_only else 16)
    assert proof['eligible_threads']==29 and len(proof['skipped_eligible_threads'])==(28 if common_only else 13)
    if common_only:
        assert proof['sampling_scope']=='Common only'
        assert {item['name'] for item in proof['threads']}=={'SeqQueueCommon'}
        assert not any('/task/43/' in command or '/task/45/' in command for command in calls)
    else:
        assert {'ExternalOSDIF','grm_result','grm_gpe'} <= {item['name'] for item in proof['threads']}
        assert {'UDATE_ASYNCSET','mwf_monitor_inp','IWrapperMwfInh','AppBackupDaemon'} <= {item['name'] for item in proof['threads']}
        assert 'AppBackupDaemon' not in {item['name'] for item in proof['skipped_eligible_threads']}
    assert proof['threads'][0]['name']=='SeqQueueCommon'
    assert all(item['syscall_boundary_unchanged'] for item in proof['threads'])
    assert proof['threads'][0]['stack']['candidate_ap_code_words'][0]['elf_va']=='0x339fa8c'
    output=next(tmp_path.glob('ee-passive-*'))
    assert b'udate_wait_for_distribution_done' in (output/'thread-44-kernel-stack.txt').read_bytes()
    assert b'[udate]' in (output/'kernel-udate-symbols.txt').read_bytes()
    assert not proof['current_blocker_proven'] and not proof['capture_verified']
    values={cell['name']:cell['value'] for cell in proof['cells']}
    assert values['EE_START_ENABLE']==0 and values['EE_ENTRY_SOURCE']==0 and values['EE_STATUS']==0
    assert values['BACKUP_SYNC_PENDING']==1


def test_missing_ap_is_evidence_not_run_failure_and_ambiguity_is_rejected(tmp_path):
    import pytest
    calls=[]
    def serial(command):calls.append(command);return b''
    result=collect_passive(serial,tmp_path)
    assert not result['available'] and result['threads_not_stopped']
    assert not result['current_blocker_proven'] and len(calls)==1
    def ambiguous(command):return b'EE_AP_MAP=/proc/42\nEE_AP_MAP=/proc/43\n'
    with pytest.raises(ValueError,match='Ambiguous'):collect_passive(ambiguous,tmp_path)


def test_common_only_rejects_missing_thread_before_stack_commands(tmp_path):
    calls=[]
    def serial(command):
        calls.append(command)
        if command.startswith('for p '):return b'EE_AP_MAP=/proc/42\n'
        if command=='cat /proc/42/maps':return b'7f00000000-7f051a7000 r-xp 00000000 00:01 10 /usr/lib/appFw.so\n'
        if command.startswith('for t '):return b'EE_THREAD=43:UDATE_ASYNCSET\n'
        raise AssertionError(command)
    with pytest.raises(ValueError,match='No unique Common'):
        collect_passive(serial,tmp_path,common_only=True)
    assert len(calls)==3


@pytest.mark.parametrize('prefix,reads',[('', '4/8/4/8/8/4'),('/ # ', '4/8/4/8/-1/-1')])
def test_group0_readback_is_bounded_and_reports_nonatomic_changes(tmp_path,prefix,reads):
    base=0x7f00000000;manager=base+0x910a108;group=manager+0x310
    current=0x7f70001000;control=0x7f70002000;calls=[]
    snapshot={'available':True,'app_pid':42,'app_base':hex(base),'snapshot_dir':str(tmp_path)}
    (tmp_path/'console.log').write_bytes(
        f'{prefix}OBS MODE_SCHEDULE sequence_id=0x2f group=0 manager={manager:#x} object=0x7f11111111 group_base={group:#x} reads={reads} observation_only=1\r\n'.encode())
    block=bytearray(0x90);struct.pack_into('<Q',block,0x88,current);struct.pack_into('<Q',block,0x20,6)
    def serial(command):
        calls.append(command)
        assert command.startswith('/simulation/menu-readmem /proc/42/mem ')
        address=int(command.split()[-2],16);size=int(command.split()[-1])
        if address==group:
            data=bytearray(block)
            if len(calls)>1:struct.pack_into('<Q',data,0x20,7)
        elif address==current+8:data=struct.pack('<Q',control)
        elif address==control+8:data=struct.pack('<I',0x1b2)
        else:raise AssertionError(command)
        assert len(data)==size
        return (f'READMEM /proc/42/mem address={address:x} bytes={size}\r\n'+
            ''.join(f'{address+i:016x}:'+''.join(f' {b:02x}' for b in data[i:i+16])+'\r\n'
                    for i in range(0,size,16))).encode()
    result=collect_group0(serial,tmp_path,snapshot)
    assert result['available'] and result['current_id']=='0x1b2' and result['queued']==6
    assert not result['group_bytes_unchanged'] and not result['atomic_snapshot']
    assert not result['current_blocker_proven'] and len(calls)==4
    assert not collect_group0(lambda _:b'',tmp_path,snapshot)['available']
    (tmp_path/'console.log').write_bytes((tmp_path/'console.log').read_bytes().replace(reads.encode(),b'4/8/4/7/-1/-1'))
    assert not collect_group0(lambda _: (_ for _ in ()).throw(AssertionError()),tmp_path,snapshot)['available']
    (tmp_path/'console.log').write_bytes(b'')
    assert not collect_group0(lambda _: (_ for _ in ()).throw(AssertionError()),tmp_path,snapshot)['available']
