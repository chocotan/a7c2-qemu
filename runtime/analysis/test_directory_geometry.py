import struct
import pytest
from directory_geometry import layout,check_boot


def synthetic():
    m=layout();mbr=bytearray(512);boot=bytearray(512);info=bytearray(512)
    mbr[510:512]=b'\x55\xaa';boot[510:512]=b'\x55\xaa'
    mbr[446+4]=0x0c;struct.pack_into('<I',mbr,446+8,63);struct.pack_into('<I',mbr,446+12,m['partition_sectors'])
    struct.pack_into('<H',boot,11,512);boot[13]=64;struct.pack_into('<H',boot,14,32);boot[16]=2
    struct.pack_into('<I',boot,32,m['partition_sectors']);struct.pack_into('<I',boot,36,m['sectors_per_fat'])
    struct.pack_into('<I',boot,44,2);struct.pack_into('<H',boot,48,1);struct.pack_into('<H',boot,50,6);boot[82:90]=b'FAT32   '
    struct.pack_into('<I',info,0,0x41615252);struct.pack_into('<I',info,484,0x61417272)
    struct.pack_into('<I',info,488,0xffffffff);struct.pack_into('<I',info,492,2);struct.pack_into('<I',info,508,0xaa550000)
    return mbr,boot,info


def test_exact_256gb_geometry_and_bpb_contract():
    mbr,boot,info=synthetic();m=check_boot(mbr,boot,info)
    assert m['total_sectors']==500000000 and m['root_cluster']==2
    assert m['sectors_per_cluster']==64 and m['bpb_sectors']<=m['partition_sectors']
    assert m['sectors_per_fat']*128>=m['cluster_one_past']


def test_bad_backup_signature_or_fat16_residue_rejected():
    mbr,boot,info=synthetic();boot[510]=0
    with pytest.raises(ValueError):check_boot(mbr,boot,info)
    mbr,boot,info=synthetic();boot[40]=1
    with pytest.raises(ValueError):check_boot(mbr,boot,info)
