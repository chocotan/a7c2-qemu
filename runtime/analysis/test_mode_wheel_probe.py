"""Run the real probe closures with host callbacks; never boot a camera."""
import ast
import json
from pathlib import Path
from types import SimpleNamespace
import pytest

SOURCE=Path(__file__).with_name('check-natural-gtk-input.py')


def block():
    return next(node for node in ast.walk(ast.parse(SOURCE.read_text()))
                if isinstance(node,ast.If) and isinstance(node.test,ast.Compare)
                and isinstance(node.test.left,ast.Constant)
                and node.test.left.value=='--mode-wheel-probe' and len(node.body)>2)


def test_actual_plan_returns_to_shooting_then_requests_positions_and_wheels():
    actions=[];captures=[];proof={'ok':False}
    def wait(check,timeout):
        assert timeout==5
        assert check({'mode_positions':{label:[1,2] for label in ('MR1','MR2','MR3','P')}})
    namespace=dict(sys=SimpleNamespace(argv=['--mode-wheel-probe']),
        time=SimpleNamespace(monotonic=lambda:0),proof=proof,wait=wait,
        action=lambda *a,**kw:actions.append((a,kw)),capture=lambda *a:captures.append(a))
    exec(compile(ast.Module(body=[block()],type_ignores=[]),str(SOURCE),'exec'),namespace)
    assert actions[0]==(('MENU',True),{})
    assert captures[0][0]=='mode-wheel-shooting-before'
    assert len(actions)==15 and len(captures)==11
    assert proof['mode_wheel_probe_symbols']==['MR1','MR2','MR3','P',
        'FRONT_LEFT','FRONT_RIGHT','REAR_LEFT','REAR_RIGHT','CONTROL_LEFT','CONTROL_RIGHT']
    assert not proof['ok'] and proof['main_review_required']


def test_budget_prevents_any_further_position_or_wheel_input():
    actions=[];ticks=iter([0,45])
    namespace=dict(sys=SimpleNamespace(argv=['--mode-wheel-probe']),
        time=SimpleNamespace(monotonic=lambda:next(ticks)),proof={},
        action=lambda *a,**kw:actions.append((a,kw)),capture=lambda *a:None)
    with pytest.raises(TimeoutError,match='budget'):
        exec(compile(ast.Module(body=[block()],type_ignores=[]),str(SOURCE),'exec'),namespace)
    assert actions==[(('MENU',True),{})]


def test_position_click_and_event_match_use_exact_selected_label():
    tree=ast.parse(SOURCE.read_text())
    action=next(node for node in ast.walk(tree)
                if isinstance(node,ast.FunctionDef) and node.name=='action')
    matcher=next(node for node in tree.body
                 if isinstance(node,ast.FunctionDef) and node.name=='input_submission')
    state={'events':[{'id':5}],'mode_positions':{'MR2':[123,456]}};calls=[]
    def wait(check):
        assert not check({'events':[{'id':6,'kind':'input','message':'MODE MR1：位置输入已提交'}]})
        assert check({'events':[{'id':6,'kind':'input','message':'MODE MR2：位置输入已提交'}]})
    namespace=dict(idle=lambda:state,native='owned-window',new_ui=True,wait=wait,
                   xdo=lambda *a:calls.append(a))
    exec(compile(ast.Module(body=[matcher,action],type_ignores=[]),str(SOURCE),'exec'),namespace)
    namespace['action']('MODE',True,position='MR2')
    assert ('mousemove','--window','owned-window',123,456) in calls
    assert calls.count(('click',1))==1
    state['mode_positions']={}
    with pytest.raises(RuntimeError,match='geometry'):
        namespace['action']('MODE',True,position='MR2')


def test_unmapped_popover_never_publishes_stale_coordinates(tmp_path):
    import os
    import threading
    tree=ast.parse(SOURCE.read_text())
    driver=next(node for node in tree.body if isinstance(node,ast.Assign)
                and any(isinstance(t,ast.Name) and t.id=='DRIVER' for t in node.targets))
    status=next(node for node in ast.parse(ast.literal_eval(driver.value)).body
                if isinstance(node,ast.FunctionDef) and node.name=='observed_status')
    def choice(label,mapped):
        return SimpleNamespace(translate_coordinates=lambda *a:(20,30),get_label=lambda:label,
            get_mapped=lambda:mapped,get_allocated_width=lambda:80,get_allocated_height=lambda:40)
    popup=SimpleNamespace(get_mapped=lambda:True,get_child=lambda:SimpleNamespace(
        get_children=lambda:[choice('MR1',True),choice('MR2',False)]))
    ui=SimpleNamespace(window=object(),buttons={},mode_popover=popup)
    state=dict(state='running',error=None,run=str(tmp_path),busy='',pending=0,snapshot=None,events=[])
    geometry=tmp_path/'geometry.json'
    namespace=dict(original_status=lambda self:state,ui_instance=ui,threading=threading,
                   main_thread=threading.get_ident(),os=os,json=json,geometry=geometry)
    exec(compile(ast.Module(body=[status],type_ignores=[]),str(SOURCE),'exec'),namespace)
    vm=SimpleNamespace(lock=threading.RLock(),png=None)
    namespace['observed_status'](vm)
    assert json.loads(geometry.read_text())['mode_positions']=={'MR1':[60,50]}
    popup.get_mapped=lambda:False
    namespace['observed_status'](vm)
    assert json.loads(geometry.read_text())['mode_positions']=={}
