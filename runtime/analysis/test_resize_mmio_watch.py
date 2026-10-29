import os
import struct
import subprocess

import pytest

from pathlib import Path
from resize_mmio_watch import ENGINE_BANKS, HELPER_TABLE, KERNEL_BASE, KERNEL_SHA, banks, descriptor, observation_error, register_u64


def test_original_resize_descriptor_offsets_and_bank_sign_extension():
    raw = bytearray(0x120)
    struct.pack_into('<QI', raw, 0x10, 0x4287aa000, 2073600)
    struct.pack_into('<10H', raw, 0x50, 1920,1080,0,0,1920,1080,0,0,1920,1080)
    struct.pack_into('<QI', raw, 0x98, 0x4f8500000, 0x1518000)
    struct.pack_into('<10H', raw, 0xd8, 1280,720,0,0,1280,720,0,0,1280,720)
    result = descriptor(bytes(raw))
    assert result['input_address'] == 0x4287aa000 and result['input_bytes'] == 2073600
    assert result['input_geometry'][:2] == [1920,1080]
    assert result['output_address'] == 0x4f8500000 and result['output_geometry'][:2] == [1280,720]
    context = bytearray(0x18);struct.pack_into('<II',context,0xc,0xf3001000,0xf3002000)
    assert banks(bytes(context)) == (0xfffffffff3001000,0xfffffffff3002000)
    with pytest.raises(ValueError):descriptor(b'')
    with pytest.raises(ValueError):banks(b'')


def test_high_aarch64_register_addresses_and_probe_failure_gate(tmp_path):
    import json
    assert register_u64(-1) == 0xffffffffffffffff
    assert register_u64(-0x3ffed250d4) == 0xffffffc0012daf2c
    assert register_u64(0x4287aa000) == 0x4287aa000
    assert observation_error(tmp_path)
    path=tmp_path/'resize-watch-result.json'
    for result in ({'connected':True,'detached':True,'hits':0},
                   {'connected':True,'detached':True,'hits':1,'error':'read failed'},
                   {'connected':True,'detached':False,'hits':1}):
        path.write_text(json.dumps(result));assert observation_error(tmp_path)
    path.write_text(json.dumps({'connected':True,'detached':True,'hits':1,'pixel_processing_proven':False}))
    assert observation_error(tmp_path) is None  # Observations pass, not pixel conversion.
    path.write_text(json.dumps({'connected':True,'detached':True,'hits':17,'pixel_processing_proven':False}))
    assert observation_error(tmp_path)
    (tmp_path/'runtime-manifest.json').write_text(json.dumps(dict(rc_board_profile=True)))
    assert observation_error(tmp_path) is None


def test_resize_watch_requires_explicit_isolated_live_input():
    script = Path(__file__).with_name('qemu-menu-probe.py')
    for values, error in (({'A7C2_RESIZE_WATCH':'yes'}, 'must be 0/1 or unset'),
                          ({'A7C2_RESIZE_WATCH':'1'}, 'requires an isolated YC injection debug mode')):
        env = {k:v for k,v in os.environ.items() if not k.startswith(('A7C2_', 'MENU_'))}
        process = subprocess.run(['python3',str(script)], env=dict(env,**values),
                                 capture_output=True,text=True,timeout=10)
        assert process.returncode == 2 and error in process.stderr


def test_engine_banks_match_original_static_configuration():
    import hashlib
    image = Path(__file__).parent/'menu-root/system/av-cam.bin'
    if not image.exists():pytest.skip('Original firmware is not distributed')
    raw = image.read_bytes();assert hashlib.sha256(raw).hexdigest() == KERNEL_SHA
    assert tuple(struct.unpack_from('<I', raw, 0x3ef308+i*0x1c+4)[0] for i in range(6)) == ENGINE_BANKS
    assert struct.unpack_from('<I', raw, 0x2d35cc)[0] == 0x2901a808  # stp w8,w10,[x0,#0xc]
    assert HELPER_TABLE == 0x387ac8
    assert struct.unpack_from('<Q', raw, HELPER_TABLE)[0] == KERNEL_BASE + 0x2c8f2c
    assert struct.unpack_from('<I', raw, 0x2c8f1c)[0] == 0x912b2129  # add x9,x9,#0xac8
    assert struct.unpack_from('<5Q', raw, 0x3883c8) == tuple(KERNEL_BASE + offset for offset in
        (0x2d8c60,0x2d8fdc,0x2d9038,0x2d835c,0x2d86fc))
    for offset, word in ((0x2d8f0c,0x54000128), (0x2d8f2c,0x97ffead9),
                         (0x2d3a98,0xb9401009), (0x2d3aa0,0xb9000128),
                         (0x2d8fec,0x97ffeac5)):
        assert struct.unpack_from('<I', raw, offset)[0] == word


def test_bounded_kernel_debug_does_not_weaken_normal_queue_guard():
    script = Path(__file__).with_name('qemu-kernel-probe.sh')
    env = {k:v for k,v in os.environ.items() if not k.startswith(('A7C2_', 'MENU_', 'QEMU_'))}
    for extra, error in (({}, 'Queue debug requires an owned live native VM'),
                         ({'QEMU_RESIZE_OBSERVE':'1','QEMU_SONY_PCIDMA':'0'},
                          'Resize observation requires the isolated PCI DMA model')):
        process = subprocess.run(['bash',str(script)],
            env=dict(env,QEMU_REQUEST_QUEUE_GDB='1',**extra),capture_output=True,text=True,timeout=10)
        assert process.returncode == 2 and error in process.stderr


@pytest.mark.parametrize('fault', [None, 'index', 'table', 'code', 'memory'])
@pytest.mark.parametrize('observe_sa',[False,True])
def test_executed_gdb_observer_decodes_and_detaches(tmp_path, monkeypatch, fault,observe_sa):
    import hashlib
    import json
    import sys
    from types import SimpleNamespace
    import request_queue_watch as queue
    import resize_mmio_watch as watch

    # A small synthetic original exercises the actual GDB loop without a VM.
    original = bytearray(HELPER_TABLE + 88)
    struct.pack_into('<Q', original, HELPER_TABLE, KERNEL_BASE + 0x2c8f2c)
    image = tmp_path/'menu-root/system/av-cam.bin'
    image.parent.mkdir(parents=True)
    image.write_bytes(original)
    monkeypatch.setattr(watch, '__file__', str(tmp_path/'resize_mmio_watch.py'))
    monkeypatch.setattr(watch, 'KERNEL_SHA', hashlib.sha256(original).hexdigest())
    config = dict(run=str(tmp_path), socket='owned-test', limit=16,
        observe_sa_mmu=observe_sa,observe_sa_completion=observe_sa)
    monkeypatch.setattr(queue, 'revalidate_gdb_config',
                        lambda _: (os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY), config))
    points, commands, reads, handlers = [], [], [], []
    sequence = iter(['resize_submit', 'resize_helper_dispatch',
                     'resize_builder_result', 'resize_queue_gate',
                     'resize_enable_gate', 'resize_mmio_enable']+(['sa_mmu_builder_entry','sa_mmu_builder_commit',
                         'sa_reference_group0_irq','sa_nv12_consumer','sa_nv12_output_queued','sa_nv12_drain_entry'] if observe_sa else []))
    regs = dict.fromkeys(('pc','sp','x0','x1','x2','x3','x8','x19','x20','x21','x22','x30'), 0)
    regs.update(x1=0x1000, x2=0x2000, x19=0x2000, x20=0x3000)

    class Breakpoint:
        def __init__(self, spec, type, internal):
            assert type == 7 and internal
            self.address, self.type, self.number = int(spec[1:],16), type, len(points)+1
            self.deleted = False
            points.append(self)

        def delete(self):
            self.deleted = True

    def read(address, size):
        reads.append((address, size))
        if size == 0x210:
            assert address in (0x2000, 0)
            raw = bytearray(size)
            struct.pack_into('<I',raw,0x208,1 if address else 0)
            return raw
        if address == 0x2000 and size == 0x1b4:
            raw = bytearray(size)
            struct.pack_into('<I',raw,0x1b0,1)
            return raw
        if address == KERNEL_BASE+0xb1ffb0:
            assert size == 0x18
            raw = bytearray(size)
            struct.pack_into('<2I',raw,0xc,ENGINE_BANKS[1],ENGINE_BANKS[1]+0x2000)
            return raw
        if address==0x5030:
            assert size==8
            return struct.pack('<Q',0xffffffc07e5bd400)
        if address==0xffffffc07e5bd400:
            assert size==352
            return bytes(size)
        if address==0x6000:
            assert size==0xc0
            raw=bytearray(size)
            struct.pack_into('<I',raw,0x7c,0x421)
            struct.pack_into('<Q',raw,0x80,0x4af654000)
            struct.pack_into('<2I',raw,0xb4,1920,1080)
            return raw
        if address==0xffffffc0af654000:
            assert size==3110400
            return bytes([128])*size
        if address in (0x84c0,0x84b5):
            assert size==1
            return bytes([1 if address==0x84c0 else 0x10])
        if address==0x83e8:
            assert size==4
            return (1 if regs['pc']==KERNEL_BASE+watch.SA_COMPLETION_POINTS['sa_nv12_output_queued'] else 0).to_bytes(4,'little')
        if address in (0x8458,0x84ac):
            assert size==4
            return (0 if address==0x8458 else 0x82d908f2).to_bytes(4,'little')
        if address==0x83f8:
            assert size==16
            return struct.pack('<IIQ',0x421,3110400,0x4af654000)
        if address == 0xfffffffff30b2000:
            assert size in (4,0x80)
            return bytes(size)
        if address in (0xfffffffff30b1000,0xfffffffff30b1200,0xfffffffff30b1280,
                       0xfffffffff30bd100,0xfffffffff30bc100):
            assert size in (0x10,0x80)
            return bytes(size)
        if size == 16:
            assert address == regs['pc']
            return b'X'*16 if fault == 'code' else bytes(original[address-KERNEL_BASE:address-KERNEL_BASE+16])
        if address == 0x1000:
            assert size == 0x120
            return bytes(size)  # Calls descriptor(), catching local-name shadowing.
        if fault == 'memory':
            raise MemoryError('unreadable')
        if address == 0x2000:
            raw = bytearray(size)
            if size == 0x174:
                struct.pack_into('<I', raw, 0x16c, 11 if fault == 'index' else 0)
            else:
                assert size == 0x1a0
                struct.pack_into('<III', raw, 0x16c, 1280, 0, 0)
                struct.pack_into('<I', raw, 0x178, 1)
            return raw
        if address == KERNEL_BASE+HELPER_TABLE:
            assert size == 8
            return struct.pack('<Q', 0 if fault == 'table' else KERNEL_BASE+0x2c8f2c)
        assert address == 0x3000 and size == 0xe8
        return bytes(size)

    def execute(command, to_string):
        commands.append(command)
        if command != 'continue':
            return
        try:
            kind = next(sequence)
        except StopIteration:
            raise KeyboardInterrupt
        regs['pc'] = KERNEL_BASE + {**watch.POINTS,**watch.SA_POINTS,**watch.SA_COMPLETION_POINTS}[kind]
        if kind == 'resize_queue_gate':
            regs['x0'] = 1
        elif kind == 'resize_enable_gate':
            regs.update(x19=KERNEL_BASE+0xb1ffb0,x20=0x2000,x21=0,x8=0)
        elif kind == 'resize_mmio_enable':
            regs['x0'] = KERNEL_BASE+0xb1ffb0
        elif kind=='sa_mmu_builder_entry':
            regs.update(x0=3,x1=0x4000,x2=1,x3=0)
        elif kind=='sa_mmu_builder_commit':
            regs.update(sp=0x5000,x29=3,x19=0x123)
        elif kind=='sa_nv12_consumer':
            regs.update(x0=0x7000,x1=0x6000)
        elif kind=='sa_nv12_output_queued':
            regs.update(x19=0x7000,x12=0x83e8)
        elif kind=='sa_nv12_drain_entry':
            regs['x0']=0x7000
        bp = next(p for p in points if p.address == regs['pc'])
        for callback in handlers:
            callback(SimpleNamespace(breakpoints=[bp]))

    monkeypatch.setitem(sys.modules, 'gdb', SimpleNamespace(
        Breakpoint=Breakpoint, BP_HARDWARE_BREAKPOINT=7, MemoryError=MemoryError,
        events=SimpleNamespace(stop=SimpleNamespace(connect=handlers.append, disconnect=handlers.remove)),
        execute=execute, parse_and_eval=lambda name: regs[name[1:]],
        selected_inferior=lambda: SimpleNamespace(read_memory=read)))
    watch.gdb_main(config)
    result = json.loads((tmp_path/'resize-watch-result.json').read_text())
    events = [json.loads(line) for line in (tmp_path/'resize-watch-events.jsonl').read_text().splitlines()]
    assert result['detached'] and commands[-1] == 'detach'
    assert all(p.deleted for p in points) and not handlers
    assert not any(command.startswith(('set ', 'call ')) for command in commands)
    if fault:
        assert result['error'] and watch.observation_error(tmp_path)
        if fault == 'index':
            assert (KERNEL_BASE+HELPER_TABLE+11*8,8) not in reads
    else:
        assert result['hits'] == (12 if observe_sa else 6) and watch.observation_error(tmp_path) is None
        assert events[1]['helper_target'] == hex(KERNEL_BASE+0x2c8f2c)
        assert events[2]['built_chunks'] == 1 and events[2]['chunk_width'] == 1280
        assert events[3]['next_state'] == 1
        assert events[3]['next_record']['state'] == 1
        assert events[4]['enable_mode'] == 1 and events[4]['setup_status'] == 0
        assert events[5]['bank1_physical'] == 0xf30b2000
        assert len(bytes.fromhex(events[5]['register_blocks']['input_dma'])) == 0x80
        assert events[5]['gic_targets_observation'].startswith('omitted:')
        assert not any(0xfffffffff13a1000<=address<0xfffffffff13a3000 for address,size in reads)
        if observe_sa:
            mmu=next(event for event in events if event['kind']=='sa_mmu_builder_entry')
            assert mmu['backing_unit']=='word' and mmu['logical_input_count']==3
            assert mmu['original_entry_verified']
            committed=next(event for event in events if event['kind']=='sa_mmu_builder_commit')
            assert committed['builder_record_count']==3 and committed['table_virtual_address']=='0xffffffc07e5bd400'
            consumed=next(event for event in events if event['kind']=='sa_nv12_consumer')
            assert consumed['output_physical_address']==0x4af654000 and consumed['output_handle']==0x421
            assert (tmp_path/consumed['output_file']).read_bytes()==bytes([128])*3110400
            assert consumed['stream_enabled'] and consumed['uvc_format']==0x10
            assert consumed['frame_time_queue_depth']==0 and consumed['notify_destination']==0x82d908f2
            queued=next(event for event in events if event['kind']=='sa_nv12_output_queued')
            assert queued['notify_queue_depth']==1 and queued['output_handle']==0x421
