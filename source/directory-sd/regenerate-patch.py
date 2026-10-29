"""Regenerate the pinned directory-SD patch without a temporary source checkout."""
import difflib
import hashlib
import json
from pathlib import Path
import tarfile

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent
ARCHIVE = SOURCE/'vendor/qemu-11.1.2.tar.xz'
PATCH = SOURCE/'qemu-directory-sd.patch'
MANIFEST = SOURCE/'qemu-directory-sd.json'
OLD_QAPI = """{ 'struct': 'BlockdevOptionsVVFAT',\n  'data': { 'dir': 'str', '*fat-type': 'int', '*floppy': 'bool',\n            '*label': 'str', '*rw': 'bool' } }"""
NEW_QAPI = """{ 'struct': 'BlockdevOptionsVVFAT',\n  'data': { 'dir': 'str', '*fat-type': 'int', '*floppy': 'bool',\n            '*label': 'str', '*rw': 'bool', '*total-sectors': 'int' } }"""


def main():
    with tarfile.open(ARCHIVE) as archive:
        original_vvfat = archive.extractfile('qemu-11.1.2/block/vvfat.c').read().decode()
        original_qapi = archive.extractfile('qemu-11.1.2/qapi/block-core.json').read().decode()
    work_vvfat = (HERE/'vvfat.c').read_text()
    if original_qapi.count(OLD_QAPI) != 1:
        raise ValueError('QAPI anchor changed')
    work_qapi = original_qapi.replace(OLD_QAPI, NEW_QAPI, 1)
    doc_old = '# @rw: whether to allow write operations (default: false)\n#\n# Since: 2.9'
    doc_new = '# @rw: whether to allow write operations (default: false)\n#\n# @total-sectors: explicit FAT32 disk size in 512-byte sectors\n#\n# Since: 2.9'
    if work_qapi.count(doc_old) != 1:
        raise ValueError('QAPI documentation anchor changed')
    work_qapi = work_qapi.replace(doc_old, doc_new, 1)
    pieces = []
    for name, before, after in (('block/vvfat.c',original_vvfat,work_vvfat),
                                ('qapi/block-core.json',original_qapi,work_qapi)):
        pieces.extend(difflib.unified_diff(before.splitlines(True),after.splitlines(True),
                                           fromfile='a/'+name,tofile='b/'+name))
    PATCH.write_text(''.join(pieces))
    manifest = json.loads(MANIFEST.read_text())
    manifest['patch_sha256'] = hashlib.sha256(PATCH.read_bytes()).hexdigest()
    manifest['source_files']['block/vvfat.c'] = {
        'before':hashlib.sha256(original_vvfat.encode()).hexdigest(),
        'after':hashlib.sha256(work_vvfat.encode()).hexdigest()}
    manifest['source_files']['qapi/block-core.json'] = {
        'before':hashlib.sha256(original_qapi.encode()).hexdigest(),
        'after':hashlib.sha256(work_qapi.encode()).hexdigest()}
    MANIFEST.write_text(json.dumps(manifest,indent=2)+'\n')
    print('DIRECTORY_SD_PATCH_REGENERATED',manifest['patch_sha256'])


if __name__=='__main__':main()
