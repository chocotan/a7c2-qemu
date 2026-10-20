import struct
import pytest

from ee_entry_snapshot import collect, map_base, normalized_frames, stack_candidates, status_fields, syscall_state, thread_list

BASE = 0x7f00000000
MAP = b'7f00000000-7f051a7000 r-xp 00000000 00:01 849 /usr/lib/appFw.so\n'
SP = 0x7e00001000
SYSCALL = f'29 0x3 0x80000006 0x1 0x2 0x3 0x4 {SP:#x} 0x7f90001000\n'.encode()


def stack_dump():
    data = struct.pack('<QQ', SP+0x20, BASE+0x35491c8)
    return (f'READMEM /proc/217/mem address={SP:x} bytes=16\n{SP:016x}: '
            + data.hex(' ')+'\n').encode()


def test_map_identity_and_aslr_frame_normalization():
    assert map_base(MAP) == BASE
    raw = f'FRAME tid=340 fp=123 lr={BASE+0x339fa8c:x}\nFRAME tid=341 lr={BASE+0x339faf4:x}\n'.encode()
    frames = normalized_frames(raw, 340, BASE)
    assert [item['elf_va'] for item in frames] == ['0x339fa8c']
    with pytest.raises(ValueError, match='unique'):
        map_base(MAP + MAP.replace(b'7f00000000', b'7e00000000'))


@pytest.mark.parametrize('raw', [b'', b'EE_THREAD=3:\n',
                                b'EE_THREAD=3:AppFw\nEE_THREAD=3:AppFw\n',
                                b'EE_THREAD=1:init\n'])
def test_incomplete_or_duplicate_thread_identity_is_rejected(raw):
    with pytest.raises(ValueError):
        thread_list(raw)


def test_collection_keeps_raw_reads_and_explicitly_reports_skipped_threads(tmp_path):
    commands = []

    def serial(command):
        commands.append(command)
        if '/status' in command:
            return b'Tgid:\t217\r\nUid:\t0 0 0 0\r\nTracerPid:\t0\r\n'
        if '/wchan' in command:
            return b'futex_wait_queue_me\n'
        if '/syscall' in command:
            return SYSCALL
        if command.startswith('cat /proc/217/maps'):
            return MAP
        if 'EE_THREAD=${t' in command:
            return b'EE_THREAD=340:SeqQueueCommon\r\nEE_THREAD=350:unrelated\r\n'
        if '/menu-regs 340' in command:
            return (f'REGS tid=340 pc={BASE+0x310194c:x}\n'
                    f'FRAME tid=340 fp=10 lr={BASE+0x35491c8:x}\n'
                    'EE_REG_RC_340=0\n').encode()
        if '/menu-readmem ' in command:
            if '4096' in command:
                return stack_dump()
            return b'00000000: 00 00 00 00\n'
        raise AssertionError(command)

    report = collect(serial, b'OBS FRAME_DRAW_ENTER call=1 tid=280 ', tmp_path)
    assert report['ok'] is True
    assert report['listed_threads'] == 2
    assert report['thread_count'] == 1
    assert report['skipped_threads'] == [{'tid': 350, 'name': 'unrelated'}]
    assert report['current_blocker_proven'] is False and report['atomic_snapshot'] is False
    assert report['threads'][0]['raw_stack_collected'] is True
    assert report['threads'][0]['stack_observation']['unwound_stack'] is False
    assert all(len(line.encode('ascii')) <= 120 for cmd in commands for line in cmd.splitlines())
    assert list(tmp_path.glob('ee-snapshot-*/thread-340-stack.txt'))
    assert not any('/menu-regs 340' in command for command in commands)


def test_wrong_register_thread_is_not_accepted(tmp_path):
    def serial(command):
        if '/status' in command:
            return b'Tgid:\t217\nTracerPid:\t0\n'
        if '/wchan' in command:
            return b'futex_wait_queue_me\n'
        if '/syscall' in command:
            return SYSCALL
        if command.startswith('cat /proc/217/maps'):
            return MAP
        if 'EE_THREAD=${t' in command:
            return b'EE_THREAD=340:SeqQueueCommon\nEE_THREAD=336:SeqThreadPool0\n'
        if 'menu-regs' in command:
            return b'REGS tid=341 pc=1\nEE_REG_RC_340=0\n'
        if '4096' in command:
            return stack_dump()
        return b'00000000: 00 00 00 00\n'

    assert collect(serial, b'OBS FRAME_DRAW_ENTER call=1 tid=280 ', tmp_path)['ok'] is False


def test_status_fields_preserve_tracer_and_uninterruptible_state():
    assert status_fields(b'Name:\tSeqQueueCommon\nState:\tD (disk sleep)\nTracerPid:\t0\n') == {
        'Name': 'SeqQueueCommon', 'State': 'D (disk sleep)', 'TracerPid': '0'}


def test_existing_tracer_is_refused_without_attempting_ptrace(tmp_path):
    commands = []

    def serial(command):
        commands.append(command)
        if '/status' in command:
            return b'Tgid:\t217\nTracerPid:\t99\n'
        if command.startswith('cat /proc/217/maps'):
            return MAP
        if 'EE_THREAD=${t' in command:
            return b'EE_THREAD=340:SeqQueueCommon\n'
        if 'menu-readmem' in command:
            return b'00000000: 00 00 00 00\n'
        return b'futex_wait_queue_me\n'

    result = collect(serial, b'OBS FRAME_DRAW_ENTER call=1 tid=280 ', tmp_path)
    assert result['ok'] is False
    assert result['threads'][0]['skipped_reason'].startswith('tracer')
    assert not any('/menu-regs' in command for command in commands)


def test_syscall_and_stack_parser_keeps_candidates_distinct_from_frames():
    assert syscall_state(SYSCALL)['sp'] == SP
    scan = stack_candidates(stack_dump(), SP, BASE)
    assert scan['candidate_ap_code_words'][0]['elf_va'] == '0x35491c8'
    assert scan['unwound_stack'] is False and scan['current_blocker_proven'] is False
    with pytest.raises(ValueError, match='identity'):
        stack_candidates(stack_dump(), SP+16, BASE)
    with pytest.raises(ValueError, match='syscall'):
        syscall_state(b'running\n')


def test_discontinuous_stack_bytes_are_rejected():
    with pytest.raises(ValueError, match='discontinuous'):
        stack_candidates(stack_dump().replace(f'{SP:016x}:'.encode(), f'{SP+16:016x}:'.encode()), SP, BASE)
