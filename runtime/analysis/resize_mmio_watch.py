"""Owned-run kernel resize observation. Never writes MMIO, pixels or completion."""
import hashlib
import json
import os
from pathlib import Path
import struct

KERNEL_SHA = '90343f5f2edc0393ad8809d907cfe648dfd3a82ce0ef39cf06167929d8955096'
KERNEL_BASE = 0xffffffc001000000
ENGINE_BANKS = (0xf30a0000, 0xf30b0000, 0xf30c0000, 0xf31a0000, 0xf31b0000, 0xf31c0000)
HELPER_TABLE = 0x387ac8
POINTS = {'resize_submit': 0x2daf2c,
          'resize_dispatch_result': 0x2db008,
          'resize_helper_dispatch': 0x2c8ef8,
          'resize_builder_result': 0x2d8c3c,
          'resize_queue_gate': 0x2d1ff0,
          'resize_enable_gate': 0x2d8f0c,
          'resize_mmio_enable': 0x2d3a90,
          'resize_cleanup_request': 0x2d3b00,
          'resize_complete_callback': 0x1d3138}
SA_POINTS={'sa_mmu_builder_entry':0x2ff5f4,'sa_mmu_builder_commit':0x2ff8ec}
SA_COMPLETION_POINTS={'sa_reference_group0_irq':0x2fbc08,'sa_nv12_consumer':0x1d565c,
                      'sa_nv12_output_queued':0x1d571c,'sa_nv12_drain_entry':0x1d4964}


def register_u64(value):
    return int(value) & 0xffffffffffffffff


def observation_error(run):
    try:
        path = Path(run)/'resize-watch-result.json'
        if path.is_symlink() or path.stat().st_size > 16384:
            raise ValueError('Invalid resize observation result')
        result = json.loads(path.read_text())
        manifest=Path(run)/'runtime-manifest.json'
        limit=64 if manifest.exists() and json.loads(manifest.read_text()).get('rc_board_profile') is True else 16
        if (result.get('connected') is not True or result.get('detached') is not True or
                result.get('error') or type(result.get('hits')) is not int or not 1 <= result['hits'] <= limit):
            raise ValueError(str(result))
    except (OSError, ValueError, TypeError, AttributeError) as error:
        return str(error)
    return None


def descriptor(raw):
    if len(raw) != 0x120:
        raise ValueError('Resize descriptor length differs')
    return dict(input_address=struct.unpack_from('<Q', raw, 0x10)[0],
                input_bytes=struct.unpack_from('<I', raw, 0x18)[0],
                input_geometry=list(struct.unpack_from('<10H', raw, 0x50)),
                output_address=struct.unpack_from('<Q', raw, 0x98)[0],
                output_bytes=struct.unpack_from('<I', raw, 0xa0)[0],
                output_geometry=list(struct.unpack_from('<10H', raw, 0xd8)))


def banks(context):
    if len(context) != 0x18:
        raise ValueError('Resize context length differs')
    b0, b1 = struct.unpack_from('<2I', context, 0xc)
    return 0xffffffff00000000 | b0, 0xffffffff00000000 | b1


def gdb_main(config):
    import gdb
    from request_queue_watch import revalidate_gdb_config
    fd, actual = revalidate_gdb_config(config)
    root = Path(actual['run'])
    original = (Path(__file__).parent / 'menu-root/system/av-cam.bin').read_bytes()
    if hashlib.sha256(original).hexdigest() != KERNEL_SHA:
        os.close(fd)
        raise ValueError('Original resize kernel identity differs')
    points={**POINTS,**(SA_POINTS if actual.get('observe_sa_mmu') is True else {}),
            **(SA_COMPLETION_POINTS if actual.get('observe_sa_completion') is True else {})}
    result = dict(connected=False, observations_only=True, hits=0, stops=0, pixel_processing_proven=False,
                  capture_limit=actual['limit'],events_per_kind={kind:0 for kind in points})
    events = (root / 'resize-watch-events.jsonl').open('x')
    breakpoints, stops = {}, []

    def stopped(event):
        stops.append(dict(numbers=[bp.number for bp in (getattr(event, 'breakpoints', None) or ())],
                          signal=getattr(event, 'stop_signal', None)))

    def emit(kind, **data):
        events.write(json.dumps(dict(kind=kind, **data)) + '\n');events.flush()

    try:
        gdb.execute('target remote ' + actual['socket'], to_string=True)
        result['connected'] = True
        gdb.events.stop.connect(stopped)
        for kind, offset in points.items():
            bp = gdb.Breakpoint('*' + hex(KERNEL_BASE + offset),
                                type=gdb.BP_HARDWARE_BREAKPOINT, internal=True)
            if bp.type != gdb.BP_HARDWARE_BREAKPOINT:
                raise RuntimeError('Software breakpoint fallback refused')
            breakpoints[bp.number] = (bp, kind, offset)
        (root / 'queue-watch-ready.json').write_text(json.dumps(
            dict(connected=True, observation='kernel RC submit/start/callback; original bytes checked on hit')))
        for _ in range(actual['limit']):
            stops.clear();gdb.execute('continue', to_string=True)
            if any(event['signal'] == 'SIGINT' for event in stops):raise KeyboardInterrupt()
            numbers = {number for event in stops for number in event['numbers']}
            matched = numbers & breakpoints.keys()
            if len(matched) != 1:
                raise RuntimeError('Unexpected resize debug stop: ' + str(stops))
            _, kind, offset = breakpoints[next(iter(matched))]
            regs = {name: register_u64(gdb.parse_and_eval('$' + name)) for name in
                    ('pc', 'sp', 'x0', 'x1', 'x2', 'x3', 'x8', 'x19', 'x20', 'x21', 'x22', 'x30')}
            result['stops'] += 1
            result['last_stop'] = dict(kind=kind, registers=regs)
            inferior = gdb.selected_inferior()
            if regs['pc'] != KERNEL_BASE + offset or bytes(inferior.read_memory(regs['pc'], 16)) != original[offset:offset+16]:
                raise ValueError('Resize kernel entry bytes/PC differ')
            data = dict(registers=regs, original_entry_verified=True)
            if kind=='sa_nv12_drain_entry':
                data.update(stream_enabled=bool(bytes(inferior.read_memory(regs['x0']+0x14c0,1))[0]),
                    uvc_format=bytes(inferior.read_memory(regs['x0']+0x14b5,1))[0],
                    notify_queue_depth=int.from_bytes(bytes(inferior.read_memory(regs['x0']+0x13e8,4)),'little'),
                    frame_time_queue_depth=int.from_bytes(bytes(inferior.read_memory(regs['x0']+0x1458,4)),'little'))
            elif kind=='sa_nv12_consumer':
                job=bytes(inferior.read_memory(regs['x1'],0xc0))
                handle=struct.unpack_from('<I',job,0x7c)[0]
                address=struct.unpack_from('<Q',job,0x80)[0]
                width,height=struct.unpack_from('<2I',job,0xb4)
                sequence=result['events_per_kind'][kind]
                if (not handle or (width,height)!=(1920,1080) or sequence>=3 or
                        not 0x400000000<=address<=0x500000000-3110400):
                    raise ValueError('NV12 original-consumer output exceeds the bounded experiment')
                output=bytes(inferior.read_memory(address+0xffffffbc00000000,3110400))
                name=f'sa-consumer-nv12-{sequence:02d}.bin'
                with (root/name).open('xb') as target:target.write(output)
                data.update(job_hex=job.hex(),output_handle=handle,output_physical_address=address,
                    width=width,height=height,output_bytes=len(output),output_file=name,
                    output_sha256=hashlib.sha256(output).hexdigest(),
                    stream_enabled=bool(bytes(inferior.read_memory(regs['x0']+0x14c0,1))[0]),
                    uvc_format=bytes(inferior.read_memory(regs['x0']+0x14b5,1))[0],
                    notify_queue_depth=int.from_bytes(bytes(inferior.read_memory(regs['x0']+0x13e8,4)),'little'),
                    frame_time_queue_depth=int.from_bytes(bytes(inferior.read_memory(regs['x0']+0x1458,4)),'little'),
                    notify_destination=int.from_bytes(bytes(inferior.read_memory(regs['x0']+0x14ac,4)),'little'),
                    reference_protocol='virtual group0 bit0; hardware factor unverified')
            elif kind=='sa_nv12_output_queued':
                pointer=register_u64(gdb.parse_and_eval('$x12'))
                if not regs['x19']+0x13e8<=pointer<=regs['x19']+0x13e8+4*16:
                    raise ValueError('Original NV12 notify entry pointer exceeds the five-slot ring')
                entry=bytes(inferior.read_memory(pointer+0x10,16))
                handle,size,address=struct.unpack('<IIQ',entry)
                if not handle or size!=3110400 or not 0x400000000<=address<=0x500000000-size:
                    raise ValueError('Original NV12 notify metadata differs from bounded FHD output')
                data.update(output_handle=handle,output_bytes=size,output_physical_address=address,
                    notify_queue_depth=int.from_bytes(bytes(inferior.read_memory(regs['x19']+0x13e8,4)),'little'),
                    frame_time_queue_depth=int.from_bytes(bytes(inferior.read_memory(regs['x19']+0x1458,4)),'little'))
            elif kind=='sa_reference_group0_irq':
                data.update(engine=2,group=0,hardware_factor_verified=False)
            elif kind=='sa_mmu_builder_entry':
                data.update(logical_input_count=regs['x0']&0xffff,
                    logical_window_mode=regs['x2']&0xff,backing_unit_mode=regs['x3']&0xff,
                    backing_unit='byte' if regs['x3']&0xff else 'word',
                    handle_array_pointer=hex(regs['x1']))
            elif kind=='sa_mmu_builder_commit':
                count=register_u64(gdb.parse_and_eval('$x29'))&0xffffffff
                pointer=struct.unpack('<Q',bytes(inferior.read_memory(regs['sp']+0x30,8)))[0]
                if count>22 or not 0xffffffc000000000<=pointer<=0xffffffc200000000-22*16:
                    raise ValueError('SA builder output exceeds original table/direct-RAM bounds')
                data.update(builder_record_count=count,table_virtual_address=hex(pointer),
                    table_hex=bytes(inferior.read_memory(pointer,22*16)).hex())
            elif kind == 'resize_submit':
                raw = bytes(inferior.read_memory(regs['x1'], 0x120))
                data.update(descriptor(raw), descriptor_hex=raw.hex())
                for name in ('input', 'output'):
                    address, length = data[name+'_address'], data[name+'_bytes']
                    if 0x400000000 <= address < 0x500000000 and length >= 64:
                        # Sampling is explicitly not full-pixel verification; QMP input proof is separate.
                        virtual = address + 0xffffffbc00000000
                        try:data[name+'_sample64_hex'] = bytes(inferior.read_memory(virtual, 64)).hex()
                        except gdb.MemoryError as error:data[name+'_sample_error'] = str(error)
            elif kind in ('resize_mmio_enable', 'resize_cleanup_request'):
                context = bytes(inferior.read_memory(regs['x0'], 0x18))
                b0, b1 = banks(context)
                data.update(context_hex=context.hex(), bank0_virtual=b0, bank1_virtual=b1)
                pa = b0 & 0xffffffff
                if pa not in ENGINE_BANKS or b1 != b0 + 0x2000:
                    raise ValueError('Resize bank pair differs from the original configuration table')
                engine = ENGINE_BANKS.index(pa)
                data.update(engine_index=engine, bank0_physical=pa, bank1_physical=pa+0x2000,
                            expected_context=KERNEL_BASE+0xb1ff50+engine*0x60)
                if regs['x0'] != data['expected_context']:
                    raise ValueError('Resize context differs from the original engine binding')
                # These are the same registers the original start helper reads before writing.
                register = b1 if kind == 'resize_mmio_enable' else b1+8
                data['bank1_register_before'] = int.from_bytes(bytes(inferior.read_memory(register, 4)), 'little')
                if kind == 'resize_mmio_enable':
                    data['register_blocks'] = {}
                    for name, offset, size in (('rc',0x2000,0x80), ('dma',0x1000,0x10),
                            ('input_dma',0x1200,0x80), ('output_dma',0x1280,0x80),
                            ('input_pack',0xd100,0x10), ('output_pack',0xc100,0x10)):
                        data['register_blocks'][name] = bytes(inferior.read_memory(b0+offset,size)).hex()
                    # Debugger memory dispatch lacks current_cpu, which SMP GIC reads require.
                    data['gic_targets_observation'] = 'omitted: GIC MMIO requires a vCPU context'
            elif kind in ('resize_start_call', 'resize_engine_exec'):
                engine = regs['x0']
                try:
                    engine_bytes = bytes(inferior.read_memory(engine, 0x210))
                    data.update(engine_object=hex(engine), engine_e0=hex(struct.unpack_from('<Q', engine_bytes, 0xe0)[0]),
                                engine_1f0=hex(struct.unpack_from('<Q', engine_bytes, 0x1f0)[0]),
                                engine_1f8=hex(struct.unpack_from('<Q', engine_bytes, 0x1f8)[0]))
                    if kind == 'resize_engine_exec':
                        executor = struct.unpack_from('<Q', engine_bytes, 0x1f0)[0]
                        executor_bytes = bytes(inferior.read_memory(executor, 0x8))
                        vtable = struct.unpack_from('<Q', executor_bytes, 0)[0]
                        vtable_bytes = bytes(inferior.read_memory(vtable, 0x40))
                        data.update(descriptor_executor=hex(executor), descriptor_vtable=hex(vtable),
                                    descriptor_vtable_20=hex(struct.unpack_from('<Q', vtable_bytes, 0x20)[0]))
                except gdb.MemoryError as error:
                    data['engine_read_error'] = str(error)
            elif kind == 'resize_helper_dispatch':
                descriptor_ptr = regs['x2']
                try:
                    raw = bytes(inferior.read_memory(descriptor_ptr, 0x174))
                    index = struct.unpack_from('<I', raw, 0x16c)[0]
                    if index > 10:
                        raise ValueError('Resize size helper index exceeds the original table')
                    table = KERNEL_BASE + HELPER_TABLE
                    target = struct.unpack('<Q', bytes(inferior.read_memory(table + index * 8, 8)))[0]
                    expected = struct.unpack_from('<Q', original, HELPER_TABLE + index * 8)[0]
                    if target != expected:
                        raise ValueError('Resize size helper table differs from the original')
                    data.update(descriptor=hex(descriptor_ptr), helper_index=index,
                                helper_table=hex(table), helper_target=hex(target),
                                descriptor_hex=raw.hex())
                except gdb.MemoryError as error:
                    raise ValueError('Resize size helper unreadable') from error
            elif kind == 'resize_builder_result':
                raw = bytes(inferior.read_memory(regs['x19'], 0x1a0))
                data.update(builder_status=regs['x22'] & 0xffffffff,
                            descriptor_pointer=hex(regs['x19']), descriptor_hex=raw.hex(),
                            chunk_width=struct.unpack_from('<I', raw, 0x16c)[0],
                            pending_chunks=struct.unpack_from('<I', raw, 0x174)[0],
                            built_chunks=struct.unpack_from('<I', raw, 0x178)[0])
            elif kind == 'resize_queue_gate':
                manager = bytes(inferior.read_memory(regs['x20'], 0xe8))
                data.update(next_state=regs['x0'] & 0xffffffff,
                            manager_pointer=hex(regs['x20']), manager_hex=manager.hex(),
                            current_slot=struct.unpack_from('<I', manager, 0xc0)[0])
                for name, pointer in (('next_record', regs['x19']), ('previous_record', regs['x21'])):
                    raw = bytes(inferior.read_memory(pointer, 0x210))
                    data[name] = dict(pointer=hex(pointer), state=struct.unpack_from('<I', raw, 0x208)[0],
                                      record_hex=raw.hex())
            elif kind == 'resize_enable_gate':
                raw = bytes(inferior.read_memory(regs['x20'], 0x1b4))
                data.update(parameter_pointer=hex(regs['x20']), parameter_hex=raw.hex(),
                            context_pointer=hex(regs['x19']), setup_status=regs['x21'] & 0xffffffff,
                            enable_mode=struct.unpack_from('<I', raw, 0x1b0)[0],
                            branch_value=regs['x8'] & 0xffffffff)
            else:
                data.update(result0=regs['x0'] & 0xffffffff, result1=regs['x1'] & 0xffffffff)
            emit(kind, **data);result['hits'] += 1;result['events_per_kind'][kind] += 1
        result['capture_limit_reached'] = True
    except KeyboardInterrupt:
        emit('cleanup_interrupt')
    except BaseException as error:
        result['error'] = f'{type(error).__name__}: {error}'
    finally:
        try:gdb.events.stop.disconnect(stopped)
        except Exception:pass
        for bp, _, _ in breakpoints.values():
            try:bp.delete()
            except Exception:pass
        try:gdb.execute('detach', to_string=True);result['detached'] = True
        except Exception as error:result['detach_error'] = str(error)
        events.close();os.close(fd)
        (root / 'resize-watch-result.json').write_text(json.dumps(result, indent=2) + '\n')
