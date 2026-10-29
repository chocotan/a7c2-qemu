"""Exercise the actual post-run text assignment with corrupted serial bytes."""
import ast
from pathlib import Path


def test_actual_console_summary_assignment_preserves_raw_bytes(tmp_path):
    source=Path(__file__).with_name('qemu-menu-probe.py').read_text()
    tree=ast.parse(source)
    nodes=[node for node in tree.body if isinstance(node,ast.Assign) and
        any(isinstance(target,ast.Name) and target.id=='text' for target in node.targets)]
    assert len(nodes)==1
    raw=b'NATIVE_CPU_ONLINE_BEGIN\r\n0-1\r\nNATIVE_CPU_ONLINE_END\r\n\x92\x00'
    (tmp_path/'console.log').write_bytes(raw)
    scope={'out':tmp_path}
    exec(compile(ast.Module(body=nodes,type_ignores=[]),'actual-finalization','exec'),scope)
    assert 'NATIVE_CPU_ONLINE_BEGIN' in scope['text'] and '\ufffd' in scope['text']
    assert (tmp_path/'console.log').read_bytes()==raw
