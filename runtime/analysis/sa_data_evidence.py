"""Independent full-byte readback for the optional data-only reference layout."""
import hashlib
import json
import re

PATTERN=re.compile(r'^SONY_SA_REFERENCE_DATA_ONLY src=(0x[0-9a-f]+) dst=(0x[0-9a-f]+) '
    r'input_bytes=4147200 output_bytes=3110400 input_sha256=([0-9a-f]{64}) output_sha256=([0-9a-f]{64}) '
    r'layout=YUYV-vmean-half-up silicon=unverified completion_published=0$',re.M)


def expected_nv12(source):
    if len(source)!=4147200:raise ValueError('Wrong reference input size')
    chroma=b''.join(bytes((a+b+1)//2 for a,b in zip(source[row*3840+1:(row+1)*3840:2],
        source[(row+1)*3840+1:(row+2)*3840:2])) for row in range(0,1080,2))
    return source[::2]+chroma


def capture(qmp,run):
    trace=run/'boot-trace.log'
    if not trace.exists():return None
    matches=PATTERN.findall(trace.read_text(errors='replace'))
    if not matches:return None
    if len(matches)!=1:raise ValueError('Data-only job capture requires one pinned launch')
    source,destination,input_hash,output_hash=matches[0]
    receipt=dict(source=int(source,16),destination=int(destination,16),input_sha256=input_hash,
        output_sha256=output_hash,layout='YUYV-vmean-half-up',completion_published=False)
    target=run/'sa-nv12-data-readback.json'
    if target.exists():
        if json.loads(target.read_text())!=receipt:raise ValueError('SA data-only job changed')
        return receipt
    for role,address,size in (('input',int(source,16),4147200),('output',int(destination,16),3110400)):
        if not 0x400000000<=address<=0x500000000-size:raise ValueError('SA data-only readback exceeds RAM window')
        name=f'sa-nv12-{role}.bin'
        qmp('pmemsave',dict(val=address,size=size,filename='/out/'+name))
        if (run/name).stat().st_size!=size:raise ValueError('Short SA data-only readback')
    target.write_text(json.dumps(receipt,indent=2)+'\n')
    return receipt


def verify(run):
    from sa_program_evidence import verify as verify_program
    from sa_mmu import verify_committed
    manifest=json.loads((run/'runtime-manifest.json').read_text())
    receipt=json.loads((run/'sa-nv12-data-readback.json').read_text())
    source=(run/'sa-nv12-input.bin').read_bytes();output=(run/'sa-nv12-output.bin').read_bytes()
    mmu=verify_committed(run);program=verify_program(run)
    hashes=(hashlib.sha256(source).hexdigest()==receipt['input_sha256'] and
            hashlib.sha256(output).hexdigest()==receipt['output_sha256'])
    bindings=(receipt['source']==mmu['entries'][1]['backing_physical_address'] and
              receipt['destination']==mmu['entries'][2]['backing_physical_address'])
    return dict(data_only_reference_readback_verified=bool(manifest.get('sa_reference_data_only') is True and
        hashes and bindings and program['loaded_nv12_program_identity_verified'] and output==expected_nv12(source)),
        input_sha256=receipt['input_sha256'],output_sha256=receipt['output_sha256'],
        output_bytes=len(output),layout=receipt['layout'],program_identity_verified=program['loaded_nv12_program_identity_verified'],
        original_mmu_binding_verified=bindings,completion_published=False,
        native_sa_isa_execution_verified=False,silicon_packing_verified=False,
        downstream_consumption_verified=False,capture_verified=False)
