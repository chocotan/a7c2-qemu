"""Strict read-only record register evidence; no call pairing or store completion."""
import writer_descriptor_upstream_trace as prior

base=prior.base
need,uint=prior.need,prior.uint
SCHEMA='readonly_shutter_writer_v4'
PROFILE='qemu-readonly-shutter-writer-v4'
BEGIN=dict(prior.BEGIN,schema=SCHEMA,record_sites='0x3',record_row='0xa24',record_quota='0x10')
RECORD_SITES=('model_record_update_inputs','model_record_value_store_pre','model_record_flag13_store_pre')
OFFSETS=(0x247088c,0x247089c,0x24708a8)
REGISTERS=('gdb_pc','x0','x1','x19','x20','x21','x30','cpsr')
KEYS=set(('kind site vcpu ordinal record_sequence observation_sequence callback_phase event_pc '
          'gdb_pc_raw candidate_base anchor_length row_u64 x0_raw x1_raw x19_raw x20_raw '
          'x21_raw x30_raw cpsr_raw cpsr_m context_mode api_ok invocation_pairing_verified '
          'store_retirement_verified memory_readback_verified').split())|base.SCOPE.keys()
for name in REGISTERS:KEYS|={name+'_read_length',name+'_api_ok'}
for name in base.OPTIONALS:KEYS|={name+'_available',name+'_raw',name+'_read_length',name+'_api_ok'}
END=set(('record_base record_anchor_seen record_sequence '
         'record0_records record1_records record2_records '
         'record0_skipped record1_skipped record2_skipped '
         'record0_suppressed record1_suppressed record2_suppressed').split())


def parse_trace(raw):
    rows=prior.fields(raw)
    need(len(rows)>=2 and rows[0]==BEGIN,'writer-v4 exact begin required')
    end=rows[-1]
    need(set(end)==base.END_KEYS|prior.ORIGIN_END|END and end['kind']=='end','writer-v4 exact terminal required')
    anchor=uint(end,'record_anchor_seen',1);record_base=uint(end,'record_base')
    need((anchor and 0<record_base<=base.LOW48_MAX-0x7e5d577 and not(record_base&0xfff)) or
         (not anchor and record_base==0),'writer-v4 record base/anchor differs')
    records=[];old_rows=[];order=[];counts=[0,0,0];old_sequences={}
    for sequence,row in enumerate(rows[1:-1],1):
        need(row.get('kind') in ('shutter_writer','writer_origin','writer_record') and
             'observation_sequence' in row,'writer-v4 fault or unsupported event')
        need(uint(row,'observation_sequence')==sequence,'writer-v4 global order differs')
        if row['kind']!='writer_record':
            old_sequences[len(old_rows)+1]=sequence
            old_rows.append(dict(row,observation_sequence=hex(len(old_rows)+1)))
            order.append(dict(observation_sequence=sequence,kind=row['kind'],site=row['site']))
            continue
        need(set(row)==KEYS and row['site'] in RECORD_SITES,'writer-v4 exact record fields required')
        site=RECORD_SITES.index(row['site']);counts[site]+=1
        need(anchor and uint(row,'candidate_base')==record_base and uint(row,'anchor_length')==36 and
             uint(row,'event_pc')==record_base+OFFSETS[site] and
             uint(row,'gdb_pc_raw') in (record_base+OFFSETS[0],record_base+OFFSETS[site]) and
             uint(row,'vcpu')==0 and row['callback_phase']=='before_instruction',
             'writer-v4 record anchor/context differs')
        need(counts[site]<=16 and uint(row,'ordinal')==counts[site] and
             uint(row,'record_sequence')==len(records)+1,'writer-v4 record local order differs')
        need(uint(row,'row_u64')==uint(row,'x19_raw')==0xa24,'writer-v4 actual full64 row differs')
        need(not site or uint(row,'x1_raw')==record_base+0x7e43430,'writer-v4 actual store destination differs')
        need(site!=2 or uint(row,'x0_raw')&0xffffffff==1,'writer-v4 actual flag store value differs')
        need(row['api_ok']=='0x1' and all(row[key]=='0x0' for key in
             ('invocation_pairing_verified','store_retirement_verified','memory_readback_verified')),
             'writer-v4 record completion claim differs')
        for name in REGISTERS:
            uint(row,name+'_raw',32 if name=='cpsr' else 64)
            need(row[name+'_read_length']==('0x4' if name=='cpsr' else '0x8') and row[name+'_api_ok']=='0x1',
                 'writer-v4 incomplete record register read')
        mode=uint(row,'cpsr_raw',32)&31
        need(mode in (0,4,5,8,9,12,13) and uint(row,'cpsr_m')==mode and
             row['context_mode']==('EL0t' if mode==0 else 'other_aarch64'),'writer-v4 record CPU mode differs')
        context={}
        for name in base.OPTIONALS:
            available=uint(row,name+'_available',1)
            if available:
                need(row[name+'_api_ok']=='0x1' and row[name+'_read_length']=='0x8','writer-v4 optional read incomplete')
                context[name]=uint(row,name+'_raw')
            else:
                need(row[name+'_raw']==row[name+'_api_ok']=='unknown' and row[name+'_read_length']=='0x0',
                     'writer-v4 missing optional context fabricated')
                context[name]=None
        records.append(dict(site=row['site'],sequence=len(records)+1,observation_sequence=sequence,
            candidate_base=record_base,row=0xa24,event_pc=uint(row,'event_pc'),
            registers={name:uint(row,name+'_raw') for name in ('x0','x1','x19','x20','x21','x30')},
            context=context,record_identity_verified=False,store_retirement_verified=False))
        order.append(dict(observation_sequence=sequence,kind='writer_record',site=row['site']))
    need(uint(end,'record_sequence')==len(records) and uint(end,'observation_sequence')==len(order),
         'writer-v4 terminal event count differs')
    skipped=[];suppressed=[]
    for site in range(3):
        need(uint(end,f'record{site}_records')==counts[site],'writer-v4 terminal record count differs')
        other=uint(end,f'record{site}_skipped');omitted=uint(end,f'record{site}_suppressed')
        need(not omitted or counts[site]==16,'writer-v4 record quota suppressed early')
        need(anchor or counts[site]==other==omitted==0,'writer-v4 counters without record anchor')
        skipped.append(other);suppressed.append(omitted)
    # The prior consumer validates only its original event view; raw v4 bytes retain their own digest/order.
    prior_end={key:value for key,value in end.items() if key not in END}
    prior_end['observation_sequence']=hex(len(old_rows))
    old=prior.parse_trace(prior.wire([prior.BEGIN,*old_rows,prior_end]))
    need(not(anchor and old['candidate_found']) or old['candidate_base']==record_base,'writer-v4 record/setter base conflict')
    need(not(anchor and old['origin_anchor_mask']) or old['origin_base']==record_base,'writer-v4 record/origin base conflict')
    for event in old['origins']:event['observation_sequence']=old_sequences[event['observation_sequence']]
    return dict(old,schema=SCHEMA,trace_sha256=prior.digest(raw),
        status='observed_raw' if records or old['origins'] or old['events'] else 'no_observed_calls',
        record_base=record_base if anchor else None,record_anchor_seen=bool(anchor),records=records,
        record_site_counts=dict(zip(RECORD_SITES,counts)),record_filtered_counts=dict(zip(RECORD_SITES,skipped)),
        record_suppressed_counts=dict(zip(RECORD_SITES,suppressed)),observation_order=order,
        truncated_by_quota=old['truncated_by_quota'] or any(suppressed),record_identity_verified=False,
        store_retirement_verified=False,memory_readback_verified=False,capture_verified=False,
        physical_asic_compatibility_verified=False)
