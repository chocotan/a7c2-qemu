"""Exercise actual focused acceptance flow without launching a camera."""
import ast
from pathlib import Path
from types import SimpleNamespace

SOURCE=Path(__file__).with_name('check-natural-gtk-input.py')


def test_mr1_settles_and_half_af_on_start_after_p_request():
    block=next(node for node in ast.walk(ast.parse(SOURCE.read_text()))
        if isinstance(node,ast.If) and isinstance(node.test,ast.Compare)
        and isinstance(node.test.left,ast.Constant)
        and node.test.left.value=='--focus-controls-probe' and len(node.body)>2)
    ticks=iter(range(100));actions=[];captures=[];proof={'ok':False}
    def wait(check,timeout):
        assert timeout==5 and check({'mode_positions':{'MR1':[1,2],'P':[3,4]}})
    namespace=dict(sys=SimpleNamespace(argv=['--focus-controls-probe']),
        time=SimpleNamespace(monotonic=lambda:next(ticks),sleep=lambda delay:None),
        idle=lambda:None,wait=wait,proof=proof,
        action=lambda *args,**kwargs:actions.append((args,kwargs)),
        capture=lambda *args:captures.append(args))
    exec(compile(ast.Module(body=[block],type_ignores=[]),str(SOURCE),'exec'),namespace)
    assert actions==[(('MENU',True),{}),(('MODE',True),{}),
        (('MODE',True),{'position':'MR1'}),(('MODE',True),{}),
        (('MODE',True),{'position':'P'}),(('SHUTTER_HALF',True),{}),(('AF_ON',True),{})]
    assert [item[0] for item in captures]==['focus-controls-shooting-before',
        'focus-controls-mr1-settled','focus-controls-p','focus-controls-shutter_half','focus-controls-af_on']
    assert proof['focus_controls_symbols']==['MR1','P','SHUTTER_HALF','AF_ON']
    assert not proof['ok'] and proof['main_review_required']
