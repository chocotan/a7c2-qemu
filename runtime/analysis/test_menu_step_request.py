import pytest
from menu_step_request import validate,await_checkpoint


def test_only_ordered_menu_keys():
    for key in ('UP','DOWN','LEFT','RIGHT','ENTER','MENU','FINISH'):
        assert validate({'step':1,'key':key},1)==key


@pytest.mark.parametrize('payload',[
    {'step':1,'key':'SHUTTER'}, {'step':1,'key':'FORMAT_API'},
    {'step':1,'key':'ENTER','command':'rm'}, {'step':2,'key':'ENTER'},
    {'step':True,'key':'ENTER'}, {'key':'ENTER'}, [], None,
])
def test_reject_injection_and_unordered_requests(payload):
    with pytest.raises(ValueError):validate(payload,1)


def test_actual_file_event_checkpoint_and_timeout(tmp_path):
    import threading
    target=tmp_path/'page'
    timer=threading.Timer(.02,lambda:target.write_text('actual page checkpoint'))
    timer.start()
    try:assert await_checkpoint(tmp_path,lambda:target.read_text() if target.exists() else None,1)=='actual page checkpoint'
    finally:timer.join(timeout=1)
    with pytest.raises(TimeoutError):await_checkpoint(tmp_path,lambda:None,0)


def test_ready_cli_requires_host_profile_and_each_page_artifact(tmp_path):
    import json,subprocess,sys
    from pathlib import Path
    helper=Path(__file__).with_name('menu_step_request.py')
    run=tmp_path/'run';run.mkdir();log=tmp_path/'workflow.log'
    log.write_text(f'FORMAT_WORKFLOW_READY {run}\n')
    manifest=run/'runtime-manifest.json'
    manifest.write_text(json.dumps({'host_sd_profile':'host-file-usb-256gb-v1'}))
    for name in ('gtk-simplified-chinese-selected.png','gtk-shooting-after-setup.png','gtk-menu-stable.png'):
        (run/name).write_bytes(b'presence fixture; actual images verified by GTK harness')
    result=subprocess.run([sys.executable,str(helper),'ready',str(log)],capture_output=True,text=True,timeout=3)
    assert result.returncode==0,result.stderr
    assert json.loads(result.stdout)=={'ready':True,'run':str(run),'formatted_by_camera':False}
    manifest.write_text('{}')
    result=subprocess.run([sys.executable,str(helper),'ready',str(log)],capture_output=True,text=True,timeout=3)
    assert result.returncode!=0 and 'Not the requested' in result.stderr
