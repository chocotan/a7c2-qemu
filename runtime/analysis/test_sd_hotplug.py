import pytest
from sd_hotplug import SDHotplug,parse


def line(state='present',seq=0,gen=1,drive=65,result=0,pid=217,lost=0):
    port=2 if state=='present' else 0x10
    return f'SD_HOTPLUG v=1 pid={pid} sequence={seq} generation={gen} state={state} drive={drive} result={result} port={port} lost={lost}\n'.encode()


def test_state_parser_requires_one_actual_status_line():
    assert parse(b'cat /tmp/sd-hotplug.state\n'+line())['state']=='present'
    for raw in (b'echo SD_HOTPLUG v=1\n',line()+line(),line(pid=1),line(state='madeup'),line(result=99)):
        with pytest.raises(ValueError):parse(raw)


def test_default_profile_enables_only_verified_rm2_and_retains_optout():
    from menu_control import launcher
    assert launcher.profile_environment({},natural_boot=True)['A7C2_SD_HOTPLUG']=='1'
    assert launcher.profile_environment({'A7C2_SD_HOTPLUG':'0'},natural_boot=True)['A7C2_SD_HOTPLUG']=='0'
    assert 'A7C2_SD_HOTPLUG' not in launcher.profile_environment({},natural_boot=False)
    assert 'A7C2_SD_HOTPLUG' not in launcher.profile_environment({'MENU_RM_SLOT1':'1'},natural_boot=True)


def test_cycle_waits_for_filesystem_and_free_terminal_status(tmp_path,monkeypatch):
    monkeypatch.setattr('sd_hotplug.time.sleep',lambda _:None)
    commands=[];sequence=0;reads=0
    def serial(command):
        nonlocal sequence,reads
        commands.append(command)
        if command.startswith('echo '):sequence=int(command.split()[2]);return b''
        if command.startswith('mv '):return b''
        if not sequence:return line()
        reads+=1
        return line('ejecting',sequence,2,result=3) if reads==1 else line('absent',sequence,2,drive=0)
    result=SDHotplug(serial,tmp_path).set_present(False)
    assert result['ok'] is True and result['state']=='absent' and len(result['history'])==2
    assert result['capture_verified'] is False
    assert all(len(command)<121 for command in commands)
    assert (tmp_path/'sd-hotplug-events.jsonl').is_file()


def test_uncertain_result_is_not_reversed_or_resent(tmp_path):
    sequence=0;writes=[]
    def serial(command):
        nonlocal sequence
        if command.startswith('echo '):sequence=int(command.split()[2]);writes.append(command);return b''
        if command.startswith('mv '):return b''
        return line('uncertain',sequence,2,result=15) if sequence else line()
    result=SDHotplug(serial,tmp_path).set_present(False)
    assert result['ok'] is False and len(writes)==1


def test_owner_change_is_rejected(tmp_path):
    responses=iter((line(),line(pid=218)));controller=SDHotplug(lambda _:next(responses),tmp_path)
    controller.status()
    with pytest.raises(RuntimeError,match='owner changed'):controller.status()


def test_link_boundary_rejects_non_boolean(tmp_path):
    controller=SDHotplug(lambda _:line(),tmp_path)
    for value in (1,0,'true',None):
        with pytest.raises(ValueError):controller.set_present(value)


def test_queued_sd_request_blocks_new_and_already_queued_input():
    from menu_control import VM
    vm=VM(natural_boot=True);vm.state='running';vm.sd_card={'state':'present','ok':True}
    vm.enqueue({'action':'sd_card','present':False})
    with pytest.raises(ValueError,match='SD'):vm.enqueue({'action':'key','key':'SHUTTER'})
    assert not vm._admit_queued({'action':'key','key':'SHUTTER'})
    vm.sd_pending=0;vm.sd_card={'state':'uncertain','ok':False}
    assert not vm._admit_queued({'action':'key','key':'SHUTTER'})
    assert vm._admit_queued({'action':'snapshot'}) and vm._admit_queued({'action':'export_sd'})
    vm.sd_card={'state':'present','ok':True};assert vm._admit_queued({'action':'key','key':'SHUTTER'})


def test_unconsumed_command_after_timeout_cannot_be_reissued(tmp_path):
    writes=[]
    def serial(command):
        if command.startswith(('echo ','mv ')):writes.append(command);return b''
        return line()
    controller=SDHotplug(serial,tmp_path,timeout=0)
    assert controller.set_present(False)['state']=='uncertain'
    assert controller.status()['state']=='uncertain'
    controller.set_present(False)
    assert len(writes)==2


def test_late_terminal_resolves_only_the_same_pending_request(tmp_path):
    current=line();submitted=0
    def serial(command):
        nonlocal submitted
        if command.startswith('echo '):submitted=int(command.split()[2]);return b''
        if command.startswith('mv '):return b''
        return current
    controller=SDHotplug(serial,tmp_path,timeout=0)
    assert controller.set_present(False)['state']=='uncertain'
    current=line('absent',submitted,2,drive=0)
    assert controller.status()['ok'] is True


def test_uncertain_publication_cannot_recover_from_old_status(tmp_path):
    writes=[]
    def serial(command):
        if command.startswith('echo '):writes.append(command);return b''
        if command.startswith('mv '):raise OSError('serial outcome unknown')
        return line()
    controller=SDHotplug(serial,tmp_path)
    with pytest.raises(OSError):controller.set_present(False)
    assert controller.status()['ok'] is False and controller.set_present(False)['ok'] is False
    assert len(writes)==1
