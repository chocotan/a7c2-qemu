"""Read-only pointer-store register evidence; destination match does not prove retirement."""
import writer_pointer7_descriptor_trace as previous

base=previous.base
need,uint=previous.need,previous.uint
wire=previous.previous.prior.wire
fields=previous.previous.prior.fields
digest=previous.previous.prior.digest
PROFILE='qemu-readonly-shutter-writer-v7'
SCHEMA='readonly_shutter_writer_v7'
BEGIN=dict(previous.BEGIN,schema=SCHEMA,pointer_sites='0x3',pointer_quota='0x10')
SITES=('saved_descriptor_store_pre','generic_descriptor_mirror_pre','publish_descriptor_mirror_pre')
STARTS=(0x2aa31d8,0x267b6d0,0x2aeffdc)
STORES=(0x2aa31dc,0x267b6d8,0x2aeffe4)
LENGTHS=(12,56,40)
REGNUMS=(1,20,19)
REGISTERS=('gdb_pc','x0','value','x30','cpsr')
KEYS=set(('kind site vcpu ordinal pointer_sequence observation_sequence callback_phase event_pc '
 'gdb_pc_raw candidate_base anchor_length anchor_parts value_register value_u32 value_raw x0_raw x30_raw expected_destination '
 'cpsr_raw cpsr_m context_mode api_ok invocation_pairing_verified store_retirement_verified memory_readback_verified').split())|base.SCOPE.keys()
for name in REGISTERS:KEYS|={name+'_read_length',name+'_api_ok'}
for name in base.OPTIONALS:KEYS|={name+'_available',name+'_raw',name+'_read_length',name+'_api_ok'}
END={'pointer_guard_base','pointer_guard_mask','pointer_base','pointer_anchor_mask','pointer_sequence'}|{f'pointer{site}_{field}' for site in range(3) for field in ('records','suppressed','filtered')}

def parse_trace(raw):
 rows=fields(raw)
 need(len(rows)>=2 and rows[0]==BEGIN,'pointer-v6 exact begin required')
 end=rows[-1];old_end={key:value for key,value in end.items() if key not in END}
 need(set(end)==set(old_end)|END and len(set(end)&END)==len(END),'pointer-v6 exact terminal fields required')
 guard_seen=uint(end,'pointer_guard_mask',3);guard_base=uint(end,'pointer_guard_base')
 need(not(guard_seen&1),'pointer-v7 unsupported guard bit')
 need((guard_seen and 0<guard_base<=base.LOW48_MAX-0x7e5d58b and not(guard_base&0xfff)) or (not guard_seen and guard_base==0),'pointer-v7 guard base differs')
 mask=uint(end,'pointer_anchor_mask',3);anchor=uint(end,'pointer_base')
 need(not(mask&6) or ((guard_seen&mask&6)==(mask&6) and guard_base==anchor),'pointer-v7 split full anchor not qualified')
 need((mask and 0<anchor<=base.LOW48_MAX-0x7e5d58b and not(anchor&0xfff)) or (not mask and anchor==0),'pointer-v6 anchor base differs')
 old=[];pointers=[];order=[];counts=[0,0,0];old_sequences={}
 for sequence,row in enumerate(rows[1:-1],1):
  need(row.get('kind') in ('shutter_writer','writer_origin','writer_record','writer_descriptor','writer_pointer') and 'observation_sequence' in row,'pointer-v6 fault or unsupported event')
  need(uint(row,'observation_sequence')==sequence,'pointer-v6 global order differs')
  if row['kind']!='writer_pointer':
   old_sequences[len(old)+1]=sequence;old.append(dict(row,observation_sequence=hex(len(old)+1)))
   order.append(dict(observation_sequence=sequence,kind=row['kind'],site=row['site']));continue
  need(set(row)==KEYS and row['site'] in SITES,'pointer-v6 exact event fields/site differ')
  site=SITES.index(row['site']);counts[site]+=1
  need(mask&(1<<site) and uint(row,'candidate_base')==anchor and uint(row,'anchor_length')==LENGTHS[site] and uint(row,'anchor_parts')==(2 if site>0 else 1) and
       uint(row,'event_pc')==anchor+STORES[site] and uint(row,'vcpu')==0 and row['callback_phase']=='before_instruction' and
       uint(row,'gdb_pc_raw') in (anchor+STARTS[site],anchor+STORES[site]),'pointer-v6 anchor or PC differs')
  need(uint(row,'value_register')==REGNUMS[site] and uint(row,'x0_raw')==uint(row,'expected_destination')==anchor+0x7e5d578,'pointer-v6 actual destination/register differs')
  need(counts[site]<=16 and uint(row,'ordinal')==counts[site] and uint(row,'pointer_sequence')==len(pointers)+1,'pointer-v6 local sequence differs')
  need(uint(row,'value_u32',32)==uint(row,'value_raw')&0xffffffff,'pointer-v6 raw value width differs')
  need(row['api_ok']=='0x1' and all(row[key]=='0x0' for key in ('invocation_pairing_verified','store_retirement_verified','memory_readback_verified')),'pointer-v6 completion claim differs')
  for name in REGISTERS:
   uint(row,name+'_raw',32 if name=='cpsr' else 64)
   need(row[name+'_read_length']==('0x4' if name=='cpsr' else '0x8') and row[name+'_api_ok']=='0x1','pointer-v6 required register incomplete')
  mode=uint(row,'cpsr_raw',32)&31
  need(mode in (0,4,5,8,9,12,13) and uint(row,'cpsr_m')==mode and row['context_mode']==('EL0t' if mode==0 else 'other_aarch64'),'pointer-v6 mode differs')
  context={}
  for name in base.OPTIONALS:
   available=uint(row,name+'_available',1)
   if available:
    need(row[name+'_api_ok']=='0x1' and row[name+'_read_length']=='0x8','pointer-v6 optional read incomplete');context[name]=uint(row,name+'_raw')
   else:
    need(row[name+'_raw']==row[name+'_api_ok']=='unknown' and row[name+'_read_length']=='0x0','pointer-v6 context fabricated');context[name]=None
  pointers.append(dict(site=row['site'],sequence=len(pointers)+1,observation_sequence=sequence,candidate_base=anchor,
   event_pc=uint(row,'event_pc'),gdb_pc_raw=uint(row,'gdb_pc_raw'),value_u32=uint(row,'value_u32',32),
   value_register='x'+str(REGNUMS[site]),value_raw=uint(row,'value_raw'),destination=uint(row,'x0_raw'),link_register_raw=uint(row,'x30_raw'),context=context,
   invocation_pairing_verified=False,store_retirement_verified=False,memory_readback_verified=False))
  order.append(dict(observation_sequence=sequence,kind='writer_pointer',site=row['site']))
 need(uint(end,'pointer_sequence')==len(pointers) and uint(end,'observation_sequence')==len(order),'pointer-v6 terminal sequence differs')
 suppressed=[];filtered=[]
 for site in range(3):
  need(uint(end,f'pointer{site}_records')==counts[site],'pointer-v6 terminal count differs')
  omitted=uint(end,f'pointer{site}_suppressed');skipped=uint(end,f'pointer{site}_filtered')
  need(not omitted or counts[site]==16,'pointer-v6 premature quota suppression')
  need(mask&(1<<site) or counts[site]==omitted==skipped==0,'pointer-v6 counters without complete anchor')
  suppressed.append(omitted);filtered.append(skipped)
 old_end['observation_sequence']=hex(len(old))
 prior=previous.parse_trace(wire([previous.BEGIN,*old,old_end]))
 for present,value in ((prior['candidate_found'],prior['candidate_base']),(prior['origin_anchor_mask'],prior['origin_base']),
                       (prior['record_anchor_seen'],prior['record_base']),(prior['descriptor_anchor_seen'],prior['descriptor_base'])):
  need(not(mask and present) or value==anchor,'pointer-v6 old/new base conflict')
  need(not(guard_seen and present) or value==guard_base,'pointer-v7 guard/old base conflict')
 for event in (*prior['descriptors'],*prior['records'],*prior['origins']):event['observation_sequence']=old_sequences[event['observation_sequence']]
 return dict(prior,schema=SCHEMA,trace_sha256=digest(raw),status='observed_raw' if pointers or old else 'no_observed_calls',
  pointer_guard_mask=guard_seen,pointer_guard_base=guard_base if guard_seen else None,
  pointer_anchor_mask=mask,pointer_base=anchor if mask else None,pointers=pointers,pointer_site_counts=dict(zip(SITES,counts)),
  pointer_filtered_counts=dict(zip(SITES,filtered)),pointer_suppressed_counts=dict(zip(SITES,suppressed)),observation_order=order,
  truncated_by_quota=prior['truncated_by_quota'] or any(suppressed),pointer_identity_verified=False,
  descriptor_current_sync_verified=False,capture_verified=False,physical_asic_compatibility_verified=False)
