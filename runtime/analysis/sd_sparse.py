"""Strict kernel-attested extent map for the opt-in 10GiB sparse virtual card."""
import re

TOTAL = 10*1024*1024*1024
DATA_LIMIT = 512*1024*1024
CAP = 4*1024*1024
BEGIN = re.compile(rb'SD_SPARSE_BEGIN total=([0-9]+) dev=([0-9]+) inode=([0-9]+) '
                   rb'mtime=(-?[0-9]+\.[0-9]{9}) ctime=(-?[0-9]+\.[0-9]{9})')
RANGE = re.compile(rb'SD_SPARSE_RANGE offset=([0-9]+) len=([0-9]+)')
END = re.compile(rb'SD_SPARSE_END ranges=([0-9]+) data=([0-9]+) allocated=([0-9]+) rc=0')


def parse_map(raw, total):
    if type(raw) is not bytes or len(raw)>1024*1024 or total!=TOTAL:
        raise ValueError('Sparse map requires bounded bytes and the explicit 10GiB profile')
    lines = [line for line in raw.replace(b'\r\n',b'\n').split(b'\n') if line.startswith(b'SD_SPARSE_')]
    if len(lines)<2 or len(lines)>4098:
        raise ValueError('Missing or excessive sparse records')
    first,last = BEGIN.fullmatch(lines[0]), END.fullmatch(lines[-1])
    if not first or not last or int(first[1])!=total:
        raise ValueError('Invalid sparse BEGIN/END or total')
    ranges=[];previous=0;data=0
    for line in lines[1:-1]:
        match=RANGE.fullmatch(line)
        if not match:
            raise ValueError('Invalid/duplicate/error sparse record')
        offset,length=map(int,match.groups())
        if not 0<length<=CAP or offset<previous or offset+length>total or offset%4096 or length%4096:
            raise ValueError('Unordered, overlapping or out-of-range sparse extent')
        ranges.append((offset,length));previous=offset+length;data+=length
        if data>DATA_LIMIT:
            raise ValueError('Sparse data exceeds bounded guest-memory profile')
    count,reported,allocated=map(int,last.groups())
    if count!=len(ranges) or reported!=data or not data<=allocated<=DATA_LIMIT:
        raise ValueError('Sparse accounting mismatch or allocation limit')
    return dict(identity=[s.decode('ascii') for s in first.groups()], ranges=ranges,
                data_bytes=data, allocated_bytes=allocated)
