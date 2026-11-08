"""Real product/libfdt prepare-only integration; requires imported assets, no guest."""
import subprocess
import pytest
import original_cold_boot as cold


@pytest.mark.parametrize('profile,storage_profile,suffix,valid',[
    ('original-init-v1','product-single-disk-v1','.ext2',True),
    ('original-init-v2','product-single-disk-v1','.ext2',False),
    ('original-init-v1','','.ext2',False),
    ('original-init-v1','product-single-disk-v1','.cpio',False),
])
def test_explicit_cold_launcher_requires_bound_raw_ram0(tmp_path,profile,storage_profile,suffix,valid):
    import os,ctypes
    image=tmp_path/('input'+suffix);image.write_bytes(b'host-only fixture')
    env={k:v for k,v in os.environ.items() if not k.startswith(('QEMU_','MENU_','A7C2_','SONY_'))}
    env.update(A7C2_ORIGINAL_COLD=profile,A7C2_STORAGE_PROFILE=storage_profile,QEMU_PREPARE_ONLY='1',QEMU_OUTPUT_DIR=str(tmp_path/'out'),MENU_NATIVE_WINDOW='1',QEMU_SYSTEM_SOUND_OWNER='1')
    result=subprocess.run(['bash',str(cold.ANALYSIS/'qemu-kernel-probe.sh'),'4096',str(cold.ANALYSIS/'qemu-virt-board/virt-packed.dtb'),'1','1',str(image)],env=env,capture_output=True,timeout=20)
    if not valid:assert result.returncode==2 and b'exact profile' in result.stderr;return
    assert result.returncode==0,result.stderr.decode(errors='replace')
    lib=ctypes.CDLL(str(cold.ANALYSIS.parent/'sources/qemu-tools/usr/lib/libfdt.so.1'));data=ctypes.create_string_buffer((tmp_path/'out/virt.dtb').read_bytes());lib.fdt_getprop.restype=ctypes.c_void_p
    node=lib.fdt_path_offset(data,b'/chosen');size=ctypes.c_int();pointer=lib.fdt_getprop(data,node,b'bootargs',ctypes.byref(size));args=ctypes.string_at(pointer,size.value)
    assert b'init=/sbin/product-cold-bootstrap' in args and b'rootfstype=ext2' in args
    assert b'product.cold=original-init-v1' in args and b'rdinit=' not in args and b'init=/bin/sh' not in args
    assert b'memrsv=0xCFC00000@0x430400000:uc' in args and b'memrsv=0x00020000@0x41d000000:uc' in args
