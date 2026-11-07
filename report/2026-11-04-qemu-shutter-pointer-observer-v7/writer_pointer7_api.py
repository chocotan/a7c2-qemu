"""Read measured self-owned record API artifacts; this never admits a Sony run."""
from pathlib import Path
import json
import struct

from writer_pointer7_trace import parse_trace
from writer_pointer7_upstream_trace_base import digest, need, read_file

QEMU_SHA256='4e85c70ba38774e9439562a7178a65bdbe6b660fdf8dd6bd4ece686fb707a4d4'
PRIMARY_SHA256='c8ad5719d5620b65451bfe09a0d0a0f6c59ca527f1876ba525c29f873aa9d2a0'
IMPORTS=frozenset('qemu_plugin_'+name for name in ('get_registers','read_register','register_vcpu_init_cb',
    'register_vcpu_tb_trans_cb','register_atexit_cb','tb_n_insns','tb_get_insn','insn_vaddr','insn_size','insn_data',
    'register_vcpu_insn_exec_cb'))
CASES=('original','equivalent-descriptor-mutation','equivalent-record-mutation','wrong-row','foreign-store-entry','short-tb','equivalent-saved-pointer','equivalent-generic-pointer','equivalent-publish-pointer','unmatched-target','duplicate-generic-tail','unqualified-generic-tail')
CONSOLE=b'POINTER_V7_CPU_READBACK_PASS pointer_values=1,0,ffffffff pointer_sites=3 descriptor_values=1,0,ffffffff distinct_current_untouched=1 record_values=1,0,ffffffff record_flags10=1,1,1 record_flags13=1,1,1 upstream_values=1,0,ffffffff selectors=17c\n'
ANCHOR=bytes.fromhex('020380d221ce0290214003916106029b200400b92000805220400039204c0039f0ffff17')
MEASURED=('scope-observer.c','record-taps.inc','descriptor-taps.inc','pointer-taps.inc','writer_pointer7_trace.py','writer_pointer7_descriptor_trace.py','writer_pointer7_record_trace.py','writer_pointer7_upstream_trace.py','writer_pointer7_upstream_trace_base.py','integration/fixture.S','integration/link.ld')


def object_json(raw):
    def unique(pairs):
        value={}
        for key,item in pairs:
            need(key not in value,'duplicate record API JSON field');value[key]=item
        return value
    def invalid(value):raise ValueError('nonfinite record API JSON value: '+value)
    value=json.loads(raw,object_pairs_hook=unique,parse_constant=invalid)
    need(type(value) is dict,'record API JSON object required')
    return value


def elf_body(raw,va,size):
    need(len(raw)>=64,'record fixture ELF header incomplete')
    head=struct.unpack_from('<16sHHIQQQIHHHHHH',raw)
    need(head[0][:6]==b'\x7fELF\x02\x01' and head[2]==183 and head[9]==56 and 1<=head[10]<=32,
         'record fixture must be bounded little-endian AArch64 ELF')
    need(head[5]+head[9]*head[10]<=len(raw),'record fixture program headers incomplete')
    loads=[struct.unpack_from('<IIQQQQQQ',raw,head[5]+i*56) for i in range(head[10])]
    need(all(0x40000000<=q[3] and q[3]+q[6]<=0x48000000 and q[5]<=q[6] and q[2]+q[5]<=len(raw)
             for q in loads if q[0]==1),'record fixture PT_LOAD outside self-owned RAM')
    found=[q for q in loads if q[0]==1 and q[3]<=va and va+size<=q[3]+q[5]]
    need(len(found)==1,'record fixture anchor has no unique file-backed PT_LOAD')
    q=found[0];start=q[2]+va-q[3]
    return raw[start:start+size]


def verify_actual_api(path,expected_sha256,library_sha256,fixture_sha256):
    path=Path(path);raw=read_file(path,4*1024*1024,expected_sha256);manifest=object_json(raw)
    need(set(manifest)==set(('status returncode started_at_ns finished_at_ns source_sha256 library_sha256 '
         'exact_readonly_imports commands foreign_pointer_guard_host_only Sony_profile_admitted '
         'active1365_modified capture_verified physical_asic_compatibility_verified').split()) and
         manifest['status']=='PASS_SELF_OWNED_POINTER_V7_TWELVE_API_CASES_NOT_SONY_OR_PROFILE_ADMISSION' and
         type(manifest['returncode']) is int and manifest['returncode']==0 and
         manifest['foreign_pointer_guard_host_only'] is True and
         all(manifest[k] is False for k in ('Sony_profile_admitted','active1365_modified','capture_verified','physical_asic_compatibility_verified')) and
         manifest['library_sha256']==library_sha256 and manifest['exact_readonly_imports']==sorted(IMPORTS),
         'record API scope, import set or outcome differs')
    need(type(manifest['started_at_ns']) is int and type(manifest['finished_at_ns']) is int and
         0<manifest['started_at_ns']<manifest['finished_at_ns'],'record API time bounds invalid')
    pins=manifest['source_sha256'];need(type(pins) is dict and all(type(k) is str and type(v) is str for k,v in pins.items()),
         'record API source pins missing')
    measured={}
    for name in MEASURED:
        matches=[key for key in pins if key.endswith('/'+name) or
                 name.startswith('integration/') and key.endswith('/integration-v2/'+Path(name).name)]
        need(len(matches)==1,'record API source identity ambiguous: '+name);measured[name]=pins[matches[0]]
    commands=manifest['commands']
    need(type(commands) is list and len(commands)==12 and [q.get('case') for q in commands]==list(CASES),
         'record API cases differ')
    evidence={}
    for call in commands:
        case=call['case'];folder=path.parent/case
        need(call.get('qemu_sha256')==QEMU_SHA256 and call.get('plugin_sha256')==library_sha256 and
             call.get('primary_sha256')==PRIMARY_SHA256 and type(call.get('returncode')) is int and call['returncode']==0 and
             call.get('outer_timeout') is False and call.get('CPU_readback_verified') is True and
             all(type(call.get(k)) is int and call[k]==0 for k in ('QMP_calls','signals_sent')),
             'record API failed, timed out or used unapproved assets')
        result_raw=read_file(folder/'content-result.json',256*1024);result=object_json(result_raw)
        need(set(result)=={'CPU_self_owned_readback_verified','console_sha256','trace_sha256','observed',
             'foreign_pointer_guard_exercised_by_this_API','foreign_entry_coverage_refused','capture_verified'} and
             result['CPU_self_owned_readback_verified'] is True and result['foreign_pointer_guard_exercised_by_this_API'] is False and
             result['foreign_entry_coverage_refused'] is (case=='foreign-store-entry') and result['capture_verified'] is False,
             'record API CPU or foreign-entry evidence claim differs')
        trace=read_file(folder/'record.log',expected_sha256=result['trace_sha256'])
        console=read_file(folder/'console.bin',4096,result['console_sha256']);need(console==CONSOLE,'record CPU self-readback differs')
        primary=read_file(folder/'primary.log')
        elf=read_file(folder/'fixture.elf',1024*1024,call.get('elf_sha256'))
        observed=parse_trace(trace)
        need(json.dumps(observed,sort_keys=True)==json.dumps(result['observed'],sort_keys=True),'record API parsed content differs from raw')
        descriptors=0 if case in ('equivalent-descriptor-mutation','short-tb') else 9
        records=0 if case in ('equivalent-record-mutation','wrong-row','foreign-store-entry','short-tb') else 9;old=0 if case=='short-tb' else 9
        need(type(call.get('descriptor_callbacks')) is int and call['descriptor_callbacks']==descriptors and
             len(observed['descriptors'])==descriptors and
             type(call.get('record_callbacks')) is int and call['record_callbacks']==records and
             type(call.get('writer_callbacks')) is int and call['writer_callbacks']==old and
             type(call.get('origin_callbacks')) is int and call['origin_callbacks']==old and
             len(observed['records'])==records and len(observed['events'])==len(observed['origins'])==old and
             observed['truncated_by_quota'] is False,'record API measured callback count differs')
        need(observed['candidate_found'] is bool(old) and observed['origin_anchor_mask']==(7 if old else 0),
             'record API old writer/origin coverage differs')
        need(observed['record_anchor_seen'] is (case not in ('equivalent-record-mutation','foreign-store-entry','short-tb')),'record API unexpected complete anchor coverage')
        expected_block=bytes.fromhex('02038052')+ANCHOR[4:] if case=='equivalent-record-mutation' else ANCHOR
        need(elf_body(elf,0x4247088c,36)==expected_block and
             elf_body(elf,0x42767978,12).hex()=='a1b702d0207005b9c0035fd6','record API original or mutated anchor differs')
        need(observed['descriptor_anchor_seen'] is (case not in ('equivalent-descriptor-mutation','short-tb')),
             'descriptor complete anchor coverage differs')
        expected_descriptor=(bytes.fromhex('a2b702d0407805b9c0035fd6') if case=='equivalent-descriptor-mutation'
                             else bytes.fromhex('a1b702d0207805b9c0035fd6'))
        need(elf_body(elf,0x42767990,12)==expected_descriptor,'descriptor exact original/mutated anchor differs')
        if descriptors:
            need([q['input_w0'] for q in observed['descriptors']]==[1]*3+[0]*3+[0xffffffff]*3,
                 'actual descriptor raw input values differ')
        need(all(value==0 for value in observed['descriptor_suppressed_counts'].values()),'descriptor API unexpectedly truncated')
        pointer_count=0 if case in ('short-tb','unmatched-target') else 6 if (case.startswith('equivalent-') and case.endswith('-pointer')) or case=='unqualified-generic-tail' else 9
        need(type(call.get('pointer_callbacks')) is int and call['pointer_callbacks']==pointer_count and len(observed['pointers'])==pointer_count,
             'pointer actual API callback count differs')
        pointer_specs=(('saved_descriptor_store_pre', 1118450136, '61a240b9010000b9f2eff697', '61024ab8010000b9f2eff697', 'equivalent-saved-pointer'), ('generic_descriptor_mirror_pre', 1114093264, '600640f9000440f9140000b92000805260560039600240f9140000b92000805260520039e00313aaf35341a9fd7bc3a8c0035fd6', '608240f8000440f9140000b92000805260560039600240f9140000b92000805260520039e00313aaf35341a9fd7bc3a8c0035fd6', 'equivalent-generic-pointer'), ('publish_descriptor_mirror_pre', 1118765020, 'a02f40f9000440f9130000b920008052a0970139a02b40f9130000b920008052a0930139', 'a08345f8000440f9130000b920008052a0970139a02b40f9130000b920008052a0930139', 'equivalent-publish-pointer'))
        expected_counts={}
        for site,va,original,mutated,mutation in pointer_specs:
            count=0 if case in ('short-tb','unmatched-target',mutation) or (site=='generic_descriptor_mirror_pre' and case=='unqualified-generic-tail') else 3;expected_counts[site]=count
            expected=bytes.fromhex(mutated if case==mutation else original)
            need(elf_body(elf,va,len(expected))==expected,'pointer original/equivalent fixture anchor differs')
            if count:need([row['value_u32'] for row in observed['pointers'] if row['site']==site]==[1,0,0xffffffff],
                          'pointer CPU register values differ')
        need(observed['pointer_site_counts']==expected_counts and
             list(observed['pointer_filtered_counts'].values())==([3,3,3] if case=='unmatched-target' else [0,0,0]),
             'pointer measured target filter differs')
        need(elf_body(elf,0x4267b6cc,4).hex()=='771e4094' and elf_body(elf,0x42aeffd8,4).hex()=='344c2e94',
             'pointer7 exact original call-prefix parts differ')
        need(observed['pointer_guard_mask']==(4 if case=='unqualified-generic-tail' else 6),
             'pointer7 actually translated complete-prefix set differs')
        if case in ('duplicate-generic-tail','unqualified-generic-tail'):
            need(elf_body(elf,0x430fa6d0,52)==bytes.fromhex(pointer_specs[1][2]),
                 'pointer7 independent duplicate tail fixture bytes differ')
        need(all(value==0 for value in observed['pointer_suppressed_counts'].values()),'pointer API unexpectedly truncated')
        if case=='original':
            need(digest(elf)==fixture_sha256,'record original fixture identity differs')
            need([q['registers']['x0']&0xffffffff for q in observed['records'] if q['site']=='model_record_value_store_pre']==[1,0,0xffffffff] and
                 [q['registers']['x21'] for q in observed['records'] if q['site']=='model_record_update_inputs']==[0x89ab,0x89ac,0x89ad],
                 'record API actual input/value register content differs')
        need(list(observed['record_filtered_counts'].values())==([3,3,3] if case=='wrong-row' else [0,0,0]),
             'record API wrong-row filter counts differ')
        need(all(value==0 for value in observed['record_suppressed_counts'].values()),'record API unexpectedly truncated')
        if old:
            need([q['input_w0'] for q in observed['events']]==[1]*3+[0]*3+[0xffffffff]*3,'record API old setter values differ')
            for site in ('dispatch_entry','table_setter_entry','upstream_entry'):
                need([q['value_u32'] for q in observed['origins'] if q['site']==site]==[1,0,0xffffffff],
                     'record API old origin values differ')
        evidence[case]=dict(result_sha256=digest(result_raw),trace_sha256=digest(trace),console_sha256=digest(console),
            primary_trace_sha256=digest(primary),elf_sha256=digest(elf),pointer_callbacks=pointer_count,descriptor_callbacks=descriptors,record_callbacks=records,writer_callbacks=old,origin_callbacks=old)
    need(read_file(path,4*1024*1024)==raw,'record API manifest changed during verification')
    return dict(path=str(path),sha256=digest(raw),cases=evidence,measured_source_sha256=measured,
                foreign_pointer_guard_host_only=True,Sony_runtime_verified=False)

