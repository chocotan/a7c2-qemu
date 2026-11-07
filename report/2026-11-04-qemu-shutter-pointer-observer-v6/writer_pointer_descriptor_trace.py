"""Descriptor d578 register observations; current d570, memory and call pairing stay separate."""
import writer_pointer_record_trace as previous

base=previous.base
need,uint=previous.need,previous.uint
PROFILE='qemu-readonly-shutter-writer-v5'
SCHEMA='readonly_shutter_writer_v5'
BEGIN=dict(previous.BEGIN,schema=SCHEMA,descriptor_sites='0x3',descriptor_quota='0x10')
SITES=('descriptor_setter_entry','descriptor_store_pre','descriptor_ret_pre')
OFFSETS=(0x2767990,0x2767994,0x2767998)
REGISTERS=('gdb_pc','x0','x1','x30','cpsr')
KEYS=set(('kind site vcpu ordinal descriptor_sequence observation_sequence callback_phase event_pc '
    'gdb_pc_raw candidate_base anchor_length input_w0 x0_raw x1_raw x30_raw expected_destination '
    'cpsr_raw cpsr_m context_mode api_ok invocation_pairing_verified store_retirement_verified '
    'memory_readback_verified').split())|base.SCOPE.keys()
for name in REGISTERS:KEYS|={name+'_read_length',name+'_api_ok'}
for name in base.OPTIONALS:KEYS|={name+'_available',name+'_raw',name+'_read_length',name+'_api_ok'}
END=set(('descriptor_base descriptor_anchor_seen descriptor_sequence descriptor0_records descriptor1_records '
    'descriptor2_records descriptor0_suppressed descriptor1_suppressed descriptor2_suppressed').split())


def parse_trace(raw):
    rows=previous.prior.fields(raw)
    need(len(rows)>=2 and rows[0]==BEGIN,'descriptor-v5 exact begin required');end=rows[-1]
    need(set(end)==base.END_KEYS|previous.prior.ORIGIN_END|previous.END|END and end['kind']=='end',
         'descriptor-v5 exact terminal required')
    seen=uint(end,'descriptor_anchor_seen',1);anchor=uint(end,'descriptor_base')
    need((seen and 0<anchor<=base.LOW48_MAX-0x7e5d58b and not(anchor&0xfff)) or
         (not seen and anchor==0),'descriptor-v5 base/anchor differs')
    old=[];descriptors=[];order=[];counts=[0,0,0];old_sequences={}
    for sequence,row in enumerate(rows[1:-1],1):
        need(row.get('kind') in ('shutter_writer','writer_origin','writer_record','writer_descriptor') and
             'observation_sequence' in row,'descriptor-v5 fault or unsupported event')
        need(uint(row,'observation_sequence')==sequence,'descriptor-v5 global order differs')
        if row['kind']!='writer_descriptor':
            old_sequences[len(old)+1]=sequence;old.append(dict(row,observation_sequence=hex(len(old)+1)))
            order.append(dict(observation_sequence=sequence,kind=row['kind'],site=row['site']));continue
        need(set(row)==KEYS and row['site'] in SITES,'descriptor-v5 fields/site differ')
        site=SITES.index(row['site']);counts[site]+=1
        need(seen and uint(row,'candidate_base')==anchor and uint(row,'anchor_length')==12 and
             uint(row,'event_pc')==anchor+OFFSETS[site] and uint(row,'vcpu')==0 and
             row['callback_phase']=='before_instruction' and
             uint(row,'gdb_pc_raw') in (anchor+OFFSETS[0],anchor+OFFSETS[site]),
             'descriptor-v5 anchor/current or TB-PC contract differs')
        need(uint(row,'expected_destination')==anchor+0x7e5d578 and
             (not site or uint(row,'x1_raw')==anchor+0x7e5d000),'descriptor-v5 target page differs')
        need(counts[site]<=16 and uint(row,'ordinal')==counts[site] and
             uint(row,'descriptor_sequence')==len(descriptors)+1,'descriptor-v5 local sequence differs')
        need(uint(row,'input_w0',32)==uint(row,'x0_raw')&0xffffffff,'descriptor-v5 raw input width differs')
        need(row['api_ok']=='0x1' and all(row[key]=='0x0' for key in
             ('invocation_pairing_verified','store_retirement_verified','memory_readback_verified')),
             'descriptor-v5 completion claim differs')
        for name in REGISTERS:
            uint(row,name+'_raw',32 if name=='cpsr' else 64)
            need(row[name+'_read_length']==('0x4' if name=='cpsr' else '0x8') and row[name+'_api_ok']=='0x1',
                 'descriptor-v5 required register read incomplete')
        mode=uint(row,'cpsr_raw',32)&31
        need(mode in (0,4,5,8,9,12,13) and uint(row,'cpsr_m')==mode and
             row['context_mode']==('EL0t' if mode==0 else 'other_aarch64'),'descriptor-v5 CPU mode differs')
        context={}
        for name in base.OPTIONALS:
            available=uint(row,name+'_available',1)
            if available:
                need(row[name+'_api_ok']=='0x1' and row[name+'_read_length']=='0x8','descriptor-v5 optional read incomplete')
                context[name]=uint(row,name+'_raw')
            else:
                need(row[name+'_raw']==row[name+'_api_ok']=='unknown' and row[name+'_read_length']=='0x0',
                     'descriptor-v5 missing context fabricated');context[name]=None
        descriptors.append(dict(site=row['site'],sequence=len(descriptors)+1,observation_sequence=sequence,
            candidate_base=anchor,event_pc=uint(row,'event_pc'),gdb_pc_raw=uint(row,'gdb_pc_raw'),
            input_w0=uint(row,'input_w0',32),destination=anchor+0x7e5d578,
            registers={name:uint(row,name+'_raw') for name in ('x0','x1','x30')},context=context,
            invocation_pairing_verified=False,store_retirement_verified=False,memory_readback_verified=False))
        order.append(dict(observation_sequence=sequence,kind='writer_descriptor',site=row['site']))
    need(uint(end,'descriptor_sequence')==len(descriptors) and uint(end,'observation_sequence')==len(order),
         'descriptor-v5 terminal event count differs')
    suppressed=[]
    for site in range(3):
        need(uint(end,f'descriptor{site}_records')==counts[site],'descriptor-v5 terminal count differs')
        omitted=uint(end,f'descriptor{site}_suppressed')
        need(not omitted or counts[site]==16,'descriptor-v5 quota suppressed early')
        need(seen or counts[site]==omitted==0,'descriptor-v5 counters without anchor');suppressed.append(omitted)
    old_end={key:value for key,value in end.items() if key not in END};old_end['observation_sequence']=hex(len(old))
    prior=previous.parse_trace(previous.prior.wire([previous.BEGIN,*old,old_end]))
    for present,value in ((prior['candidate_found'],prior['candidate_base']),
                          (prior['origin_anchor_mask'],prior['origin_base']),
                          (prior['record_anchor_seen'],prior['record_base'])):
        need(not(seen and present) or value==anchor,'descriptor-v5 old/new base conflict')
    for event in (*prior['records'],*prior['origins']):event['observation_sequence']=old_sequences[event['observation_sequence']]
    return dict(prior,schema=SCHEMA,trace_sha256=previous.prior.digest(raw),
        status='observed_raw' if descriptors or prior['records'] or prior['origins'] or prior['events'] else 'no_observed_calls',
        descriptor_anchor_seen=bool(seen),descriptor_base=anchor if seen else None,descriptors=descriptors,
        descriptor_site_counts=dict(zip(SITES,counts)),descriptor_suppressed_counts=dict(zip(SITES,suppressed)),
        observation_order=order,truncated_by_quota=prior['truncated_by_quota'] or any(suppressed),
        descriptor_identity_verified=False,descriptor_current_sync_verified=False,capture_verified=False,
        physical_asic_compatibility_verified=False)
