#!/usr/bin/env python3
"""Read-only validation of complete official-derived Sony BK4 configuration files."""
import hashlib
import struct

RECORD_OFFSETS=(0,0xed000)
FILE_BYTES=2390264
OFFICIAL_PP_SHA256='3dab4f0d6b7790f4a7798034b57f43bfe3255c39dc6da2897fc288b3a218fe47'


def parse_record(data,offset,limit,verify_checksum=True):
    if not 0<=offset<=limit<=len(data) or limit-offset<256:
        raise ValueError('Truncated BK4 header')
    record=memoryview(data)[offset:limit]
    magic,cookie,generation,revision,subsystems,slots,data_offset,data_size,checksum=struct.unpack_from('<9I',record)
    if magic!=0x04000000 or cookie!=0xaaaaaaaa or revision!=0x00344b42:
        raise ValueError('Unsupported BK4 identity')
    size=data_offset+data_size
    if data_offset<256 or size>len(record) or 256+subsystems*6+slots*6>data_offset:
        raise ValueError('Invalid BK4 table/data bounds')
    if verify_checksum and (sum(record[:32])+sum(record[36:size]))&0xffffffff!=checksum:
        raise ValueError('BK4 checksum differs')
    properties={}
    table_offset=256+subsystems*6
    for subsystem in range(subsystems):
        count,first=struct.unpack_from('<HI',record,256+subsystem*6)
        if first>slots or count>slots-first:
            raise ValueError('BK4 subsystem exceeds property slots')
        for local in range(count):
            attr,pointer=struct.unpack_from('<HI',record,table_offset+(first+local)*6)
            if pointer==0xffffffff:continue
            length=maximum=pointer>>24
            start=pointer&0xffffff
            if start<data_offset or start>size:
                raise ValueError('BK4 property offset outside data')
            if length in (0,255):
                prefix=4 if not length else 2
                if prefix>size-start:raise ValueError('Truncated BK4 property length')
                length=struct.unpack_from('<H',record,start)[0]
                maximum=struct.unpack_from('<H',record,start+2)[0] if prefix==4 else length
                start+=prefix
            if length>maximum or maximum>size-start:
                raise ValueError('BK4 property exceeds data')
            if attr&0x74 and maximum>size-start-maximum:
                raise ValueError('BK4 reset data exceeds record')
            key=(subsystem<<16)|local
            properties[key]={'attr':attr,'size':length,'max_size':maximum,
                             'data':bytes(record[start:start+length])}
    return {'offset':offset,'bytes':size,'generation':generation,
            'id1':struct.unpack_from('<I',record,40)[0],
            'region':bytes(record[192:224]).rstrip(b'\0').decode('ascii'),
            'version':bytes(record[64:96]).rstrip(b'\0').decode('ascii'),
            'subsystems':subsystems,'property_slots':slots,'properties':properties}


def parse_file(data,verify_checksum=True):
    if len(data)!=FILE_BYTES:raise ValueError('Unexpected full Backup file length')
    return [parse_record(data,start,end,verify_checksum) for start,end in
            zip(RECORD_OFFSETS,(*RECORD_OFFSETS[1:],len(data)))]


def validate(data,official):
    if hashlib.sha256(official).hexdigest()!=OFFICIAL_PP_SHA256:
        raise ValueError('Reference must be the verified official ALLLANG PP')
    reference=parse_file(official);actual=parse_file(data);records=[]
    for source,current in zip(reference,actual):
        for key in ('region','version','subsystems','property_slots','bytes'):
            if source[key]!=current[key]:raise ValueError('Backup source/schema differs: '+key)
        def schema(record):
            return {key:(value['attr'],value['max_size']) for key,value in record['properties'].items()}
        if schema(source)!=schema(current):raise ValueError('Backup property schema differs from official PP')
        records.append({key:value for key,value in current.items() if key!='properties'})
    return {'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data),
            'official_pp_sha256':OFFICIAL_PP_SHA256,'records':records}
