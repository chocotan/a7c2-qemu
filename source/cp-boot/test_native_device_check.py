"""Host checks for evidence paths; no QEMU or firmware is started."""
from pathlib import Path
import os
import runpy
import pytest
from types import SimpleNamespace


def checker():
    return runpy.run_path(str(Path(__file__).with_name('check-native-qemu.py')))


def test_batch_collects_content_failures_and_keeps_later_results():
    record=checker()['record_check'];result={'checks':{}}
    def bad():raise ValueError('model did not consume bytes')
    record(result,'first',bad)
    record(result,'second',lambda:{'readback':123})
    assert 'first' not in result['checks']
    assert result['checks']['second']=={'readback':123}
    assert 'model did not consume bytes' in result['check_errors']['first']['error']
    assert 'ValueError' in result['check_errors']['first']['traceback']


def test_batch_does_not_treat_broken_transport_as_content_failure():
    result={'checks':{}}
    def broken():raise ConnectionError('QEMU owner disconnected')
    with pytest.raises(ConnectionError):checker()['record_check'](result,'dma',broken)
    assert result=={'checks':{}}


def test_malformed_transport_is_not_a_content_failure():
    api=checker()
    transport=runpy.run_path(str(Path(__file__).with_name('native-qtest.py')))['QtestTransportError']
    result={'checks':{}}
    def broken():raise transport('qtest FAIL or mismatched QMP id')
    with pytest.raises(ConnectionError, match='mismatched'):
        api['record_check'](result,'device',broken)
    assert result=={'checks':{}}


@pytest.mark.parametrize('reply', [[], ['garbage'], ['0xzz'], ['0x1'], ['0x0102'], ['0x 1'], None])
def test_malformed_qtest_bytes_terminate_batch(reply):
    api=checker()
    result={'checks':{}}
    machine=SimpleNamespace(qtest=lambda _command: reply)
    with pytest.raises(api['QtestTransportError']):
        api['record_check'](result,'read',lambda:api['bytes_at'](machine,0,1))
    assert result=={'checks':{}}


@pytest.mark.parametrize('failure', ['none', 'transport', 'stop-stuck'])
def test_dfs_clock_runs_and_always_restores_pause(failure):
    api=checker()
    class ClockFixture:
        def __init__(self):
            self.running=False;self.events=[];self.registers={};self.target=0
        def command(self,name):
            self.events.append(name)
            if name=='cont':self.running=True
            if name=='stop' and failure!='stop-stuck':self.running=False
            return {'running':self.running} if name=='query-status' else {}
        def write(self,address,value):
            self.registers[address]=value
            if address==0xf1388f54:self.target=value
            if address==0xf1388f50:self.registers[0xf1388f58]=0x100
        def read(self,address):return self.registers.get(address,0)
        def qtest(self,command):
            assert command=='clock_step 1000000' and self.running
            if failure=='transport':raise api['QtestTransportError']('fixture transport failure')
            self.registers[0xf1388f48]=1;self.registers[0xf1388f58]=self.target&0xff
    cp=ClockFixture()
    if failure=='transport':
        with pytest.raises(ConnectionError,match='fixture transport'):
            api['dfs_transactions'](cp)
    elif failure=='stop-stuck':
        result={'checks':{}}
        with pytest.raises(ConnectionError,match='restore paused'):
            api['record_check'](result,'dfs',lambda:api['dfs_transactions'](cp))
            api['record_check'](result,'later',lambda:None)
        assert result=={'checks':{}} and cp.running
    else:
        api['dfs_transactions'](cp)
    if failure!='stop-stuck':assert not cp.running
    assert cp.events[-2:]==['stop','query-status']
    assert cp.events.count('cont')==1 and cp.events.count('stop')==1


def test_single_scu_selection_never_claims_full_batch(tmp_path, monkeypatch):
    api=checker();namespace=api['run'].__globals__
    binary=tmp_path/'fixture-qemu';binary.write_bytes(b'not executed')
    class Endpoint:
        def __init__(self,_binary,_pair,_out,side,**kwargs):
            self.side=side;self.process=object();self.values={}
            if side=='ap':assert kwargs['p1_spi_component'] is False
        def write(self,address,value):self.values[address]=value
        def read(self,address):return self.values.get(address,0)
        def close(self):
            self.process=None
            return {'qmp_quit_confirmed':True,'returncode':0,'alive':False,'signals_sent':[]}
    def prepare(pair,_binary):
        pair.mkdir(mode=0o700)
        return {'fixture':True}
    def load(path):
        if str(path).endswith('native-link.py'):return {'prepare':prepare}
        if str(path).endswith('native-qtest.py'):return {'NativeEndpoint':Endpoint}
        raise AssertionError(path)
    monkeypatch.setattr(namespace['runpy'],'run_path',load)
    monkeypatch.setitem(namespace,'scu_i2c',lambda _cp:{'fixture':True})
    result=api['run'](binary,tmp_path/'output',only='scu_i2c')
    assert result['schema']=='a7c2-native-device-batch-v3'
    assert result['selected_checks_verified'] and not result['verified']
    assert result['selection']=='scu_i2c' and result['executed_checks']==['scu_i2c']
    assert list(result['checks'])==['scu_i2c'] and not result['original_cp_consumption_verified']


def test_rejected_reads_direct_child_fd_output_with_integer_log_name(tmp_path):
    path=tmp_path/'cp.stderr'
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'wb') as stream:
        assert isinstance(stream.name,int)
        def read(address):
            os.write(stream.fileno(),b'CP_SCU op=read bank=0 value=0x0 result=1\n')
            return 0
        machine=SimpleNamespace(log=stream,out=tmp_path,side='cp',read=read)
        result=checker()['rejected'](machine,0xf10120fc,'CP_SCU')
        assert result['address']=='0xf10120fc' and 'result=1' in result['raw_log']


def test_connected_uses_fixed_endpoint_log_paths(tmp_path):
    ap=tmp_path/'ap.stderr';cp=tmp_path/'cp.stderr'
    ap.write_bytes(b'AP_CP_GPIO op=receive result=0\n')
    cp.write_bytes(b'AP_CP_GPIO op=receive result=0\n')
    def forbidden(*args):raise AssertionError('Both peer snapshots are already recorded')
    checker()['connected'](SimpleNamespace(out=tmp_path,side='ap',log=None,command=forbidden),
                           SimpleNamespace(out=tmp_path,side='cp',log=None,command=forbidden))
