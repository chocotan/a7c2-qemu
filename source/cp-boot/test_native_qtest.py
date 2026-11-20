"""Host contract tests only; written here without execution. Use a project-local --basetemp."""
import importlib.util
import io
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location('native_qtest', Path(__file__).with_name('native-qtest.py'))
nq = importlib.util.module_from_spec(spec)
spec.loader.exec_module(nq)


@pytest.fixture
def local(tmp_path):
    assert not str(tmp_path).startswith('/tmp/'), 'Use --basetemp in the project, per AGENTS.md'
    return tmp_path


def ram_arguments(pair, side):
    return [item for name, filename, size, offset in nq.EXPECTED[side] for item in (
        '-object', json.dumps(dict(**{'qom-type': 'memory-backend-file', 'id': name,
                                      'mem-path': str(pair / filename), 'size': size,
                                      'offset': offset, 'share': True, 'discard-data': False}),
                             separators=(',', ':')))]


@pytest.mark.parametrize('side,machine,memory,cpu,smp,notify', [
    ('ap', 'virt,gic-version=2,memory-backend=native-local-ram', '24G', 'cortex-a53', '1',
     'socket,id=notify-peer,path=notify.sock,server=on,wait=off'),
    ('cp', 'none,memory-backend=native-local-ram', '128M', 'cortex-a53', '4',
     'socket,id=notify-peer,path=notify.sock,server=off')])
def test_role_geometry_and_relative_sockets(local, side, machine, memory, cpu, smp, notify):
    pair, out = local / 'pair', local / 'a,b'
    command = nq.build_command(local / 'qemu', pair, out, side, ram_arguments(pair, side))
    assert command[1:3] == ['-M', machine]
    assert command.count('-object') == 3
    assert [command[index+1] for index,item in enumerate(command) if item=='-object'] == ram_arguments(pair,side)[1::2]
    assert command[command.index('-accel') + 1] == 'qtest'
    assert command[command.index('-m') + 1] == memory
    assert command[command.index('-cpu') + 1] == cpu
    assert command[command.index('-smp') + 1] == smp
    assert command[command.index('-qmp') + 1] == 'unix:' + side + '-qmp.sock,server=on,wait=off'
    assert command[command.index('-qtest') + 1] == 'unix:' + side + '-qt.sock,server=on,wait=off'
    assert command[command.index('-chardev') + 1] == notify
    for option in ('-S', '-nodefaults', '-display', '-nic', '-audio', '-monitor', '-serial',
                   '-sandbox'):
        assert option in command
    assert command[command.index('-sandbox') + 1] == 'on'
    uarts = [item for item in command if item.startswith('file,id=cp-uart')]
    gdb = [command[index + 1] for index, item in enumerate(command) if item == '-gdb']
    if side == 'cp':
        assert gdb == []
        assert len(uarts) == 5
        assert uarts[0] == 'file,id=cp-uart0,path=' + str(out / 'uart0.log').replace(',', ',,')
        assert ',,' in uarts[3]
    else:
        assert gdb == []
        assert uarts == []


def test_ram_geometry_is_not_bypassed(local):
    pair = local / 'pair'
    ram = ram_arguments(pair, 'ap')
    ram[1] = ram[1].replace('"size":25769803776', '"size":25769803777')
    with pytest.raises(ValueError, match='RAM geometry differs'):
        nq.build_command(local / 'qemu', pair, local / 'out', 'ap', ram)
    with pytest.raises(ValueError, match='three -object'):
        nq.build_command(local / 'qemu', pair, local / 'out', 'ap', ram[:4])


def test_invalid_side_is_rejected_before_any_output(local):
    out = local / 'out'
    with pytest.raises(ValueError, match='Side must be ap or cp'):
        nq.NativeEndpoint(local / 'qemu', local / 'pair', out, 'AP')
    assert not out.exists()


def test_environment_strips_every_role_prefix(local):
    inherited = {'HOME': '/h', 'PATH': '/bin', 'MENU_X': '1', 'QEMU_CP_GIC': '1',
                 'SONY_TIMERS': '1', 'A7C2_HOST_SD': '/sd'}
    assert nq.strip_environment(inherited) == {'HOME': '/h', 'PATH': '/bin'}


@pytest.mark.parametrize('side', ['ap', 'cp'])
def test_secure_group_window_is_component_cp_only(local,monkeypatch,side):
    monkeypatch.setitem(nq.LINK, 'environment', lambda role,pair:{'QEMU_AP_CP_GPIO_SIDE':role})
    env=nq.child_environment(side,local,{'QEMU_NATIVE_COMPONENT_GIC_GROUPS':'inherited-forbidden','MENU_FAKE':'1'})
    assert 'MENU_FAKE' not in env
    if side=='cp':
        assert env['QEMU_NATIVE_COMPONENT_GIC_GROUPS']=='virtual-native-component-gic-groups-v1'
    else:
        assert 'QEMU_NATIVE_COMPONENT_GIC_GROUPS' not in env


def test_p1_spi_component_is_explicit_ap_only(local, monkeypatch):
    monkeypatch.setitem(nq.LINK, 'environment', lambda role, pair: {'QEMU_AP_CP_GPIO_SIDE': role})
    assert 'QEMU_NATIVE_P1_SPI_COMPONENT' not in nq.child_environment('ap', local, {})
    enabled = nq.child_environment('ap', local, {}, p1_spi_component=True)
    assert enabled['QEMU_NATIVE_P1_SPI_COMPONENT'] == 'virtual-p1-pl022-component-v1'
    with pytest.raises(ValueError, match='AP-only'):
        nq.child_environment('cp', local, {}, p1_spi_component=True)
    with pytest.raises(ValueError, match='AP-only'):
        nq.child_environment('ap', local, {}, p1_spi_component=1)


def test_qmp_id_mismatch_and_qtest_fail_are_transport_errors():
    endpoint=nq.NativeEndpoint.__new__(nq.NativeEndpoint)
    endpoint.side='cp';endpoint.counter=0;endpoint.records=[];endpoint.qmp=io.BytesIO()
    endpoint.receive=lambda:{'id':999,'return':{}}
    with pytest.raises(nq.QtestTransportError):
        endpoint.command('cont')
    class BrokenQtest:
        def write(self, _data): pass
        def readline(self, _limit): return b'FAIL invalid transaction\n'
    endpoint.qt=BrokenQtest()
    with pytest.raises(nq.QtestTransportError):
        endpoint.qtest('readl 0x0')
    endpoint.qtest=lambda _command:['garbage']
    with pytest.raises(nq.QtestTransportError, match='Malformed'):
        endpoint.read(0)
    endpoint.qtest=lambda _command:['0x00000000ffffffff']
    assert endpoint.read(0)==0xffffffff
    endpoint.qtest=lambda _command:['0x100000000']
    with pytest.raises(nq.QtestTransportError, match='Malformed'):
        endpoint.read(0)


@pytest.mark.parametrize('number',range(1,14))
@pytest.mark.parametrize('down',[True,False])
def test_virtual_key_qmp_serializes_only_exact_owned_cp_events(number,down):
    endpoint=nq.NativeEndpoint.__new__(nq.NativeEndpoint)
    endpoint.side='cp';endpoint.counter=0;endpoint.records=[];endpoint.qmp=io.BytesIO()
    endpoint.receive=lambda:{'id':endpoint.counter,'return':{}}
    args={'events':[{'type':'key','data':{'down':down,'key':{'type':'qcode','data':'f'+str(number)}}}]}
    assert endpoint.command('input-send-event',args)=={}
    assert json.loads(endpoint.qmp.getvalue())=={'execute':'input-send-event','id':1,'arguments':args}
    assert endpoint.records[0]['qmp_execute']['arguments']==args


@pytest.mark.parametrize('side,arguments',[
    ('ap',{'events':[]}),('cp',None),('cp',{'events':[]}),('cp',{'events':[{}]}),
    ('cp',{'events':[{'type':'key','data':{'down':1,'key':{'type':'qcode','data':'f1'}}}]}),
    ('cp',{'events':[{'type':'key','data':{'down':True,'key':{'type':'qcode','data':'delete'}}}]}),
    ('cp',{'events':[{'type':'key','data':{'down':True,'key':{'type':'qcode','data':[]}}}]}),
])
def test_virtual_key_qmp_rejects_before_socket_write(side,arguments):
    endpoint=nq.NativeEndpoint.__new__(nq.NativeEndpoint)
    endpoint.side=side
    with pytest.raises(ValueError):endpoint.command('input-send-event',arguments)


class FakeProcess:
    pid = 4321

    def __init__(self):
        self.returncode = None
        self.dead = False

    def poll(self):
        return self.returncode if self.dead else None

    def wait(self, timeout=None):
        assert timeout == 10
        self.dead, self.returncode = True, 0
        return 0


class FakeQmp:
    def __init__(self, fail=False):
        self.fail, self.reply, self.closed = fail, None, False

    def write(self, raw):
        if self.fail:
            raise BrokenPipeError('mock QMP quit failed')
        self.reply = (json.dumps({'id': json.loads(raw)['id'], 'return': {}}) + '\n').encode()

    def readline(self, limit):
        return self.reply

    def close(self):
        self.closed = True


def fake_endpoint(out, side='cp', fail=False):
    endpoint = object.__new__(nq.NativeEndpoint)
    endpoint.side, endpoint.out = side, out
    endpoint.log = open(out / (side + '.stderr'), 'xb')
    endpoint.process, endpoint.counter, endpoint.records = FakeProcess(), 0, []
    endpoint.qmp, endpoint.qt = FakeQmp(fail), None
    endpoint.qmp_socket = endpoint.qt_socket = None
    endpoint._startup_error = endpoint._shutdown = None
    endpoint._owner = dict(side=side, qmp=side + '-qmp.sock', qt=side + '-qt.sock',
                           signals_sent=[])
    return endpoint


def test_base_gpio_endpoint_keeps_live_owner_and_preserves_failed_receipt(local):
    endpoint = object.__new__(nq.Endpoint)
    endpoint.side, endpoint.out = 'cp', local
    endpoint.log = open(local/'cp.stderr', 'xb')
    endpoint.process, endpoint.counter, endpoint.records = FakeProcess(), 0, []
    endpoint.qmp, endpoint.qt = FakeQmp(True), None
    endpoint.qmp_socket = endpoint.qt_socket = None
    endpoint._shutdown = None
    process, qmp = endpoint.process, endpoint.qmp
    with pytest.raises(RuntimeError, match='retained'):
        endpoint.close()
    first = json.loads((local/'cp-owner.json').read_text())
    assert first['shutdown']['alive'] and first['shutdown']['retained']
    assert endpoint.process is process and not qmp.closed and not endpoint.log.closed
    qmp.fail = False
    result = endpoint.close()
    assert result['qmp_quit_confirmed'] and not result['alive']
    assert json.loads((local/'cp-owner.json').read_text()) == first
    assert len(list(local.glob('cp-owner-retry-*.json'))) == 1


def test_close_retains_live_owner_when_quit_fails(local):
    endpoint = fake_endpoint(local, fail=True)
    process = endpoint.process
    with pytest.raises(ValueError, match='retained'):
        endpoint.close()
    assert endpoint.process is process and process.poll() is None
    assert not endpoint.log.closed and not endpoint.qmp.closed
    owner = json.loads((local / 'cp-owner.json').read_text())
    assert owner['qmp'] == 'cp-qmp.sock' and owner['shutdown']['pid'] == process.pid
    assert owner['shutdown']['alive'] is True and owner['shutdown']['retained'] is True
    assert owner['shutdown']['signals_sent'] == []
    assert 'retained_error' in owner


def test_close_releases_and_saves_owner_on_rc0(local):
    endpoint = fake_endpoint(local)
    qmp = endpoint.qmp
    endpoint.records.append({'fixture_request':'content preserved'})
    result = endpoint.close()
    assert result['qmp_quit_confirmed'] is True and result['returncode'] == 0
    assert result['alive'] is False and result['signals_sent'] == []
    assert endpoint.process is None and endpoint.log is None and qmp.closed
    owner_path = local / 'cp-owner.json'
    owner = json.loads(owner_path.read_text())
    assert owner['shutdown'] == result
    assert owner['records'] == endpoint.records
    assert owner['records'][0] == {'fixture_request':'content preserved'}
    assert owner_path.stat().st_mode & 0o777 == 0o600
