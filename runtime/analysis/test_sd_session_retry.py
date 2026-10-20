"""Execute the actual SDK closure without launching QEMU or changing guest state."""
import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest


@pytest.mark.parametrize('failures',[1,2])
def test_prior_sequence_is_recovered_before_another_flush(tmp_path,failures):
    path=Path(__file__).with_name('qemu-menu-probe.py')
    tree=ast.parse(path.read_text())
    function=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name=='export_virtual_sd')
    namespace=dict(out=tmp_path,manifest={'rm_file_image_bytes':512},virtual_hci=False,early_media_watch=None,request_queue_gdb=False,os=SimpleNamespace(environ={}),
                   pending_sd_sequence=[None],last_sd_export_sha=[None],
                   time=SimpleNamespace(monotonic_ns=iter((1000,2000)).__next__))
    exec(compile(ast.Module(body=[function],type_ignores=[]),str(path),'exec'),namespace)
    (tmp_path/'SD').mkdir()
    stopped=[];flushes=[];cancellations=[];reports=[]
    def quiesce(serial,sequence):
        assert not stopped,'a new flush must not replace an unrecovered owner sequence'
        stopped.append(sequence);flushes.append(sequence)
        return {'owner_stopped':True}
    def cancel(serial,sequence):
        cancellations.append(sequence)
        assert stopped==[sequence]
        if len(cancellations)<=failures:raise OSError('temporary cancel publication ENOSPC')
        stopped.clear();return {'ok':True,'status':'resumed'}
    def capture(out,total,**kwargs):
        kwargs['quiesce']()
        assert kwargs['expected_old_sha256']==(None if len(flushes)==1 else 'a'*64)
        return {'ok':True,'sha256':'a'*64,'card_published':True}
    with patch('sd_transport.export_card',side_effect=capture),\
         patch('sd_transport.report',side_effect=lambda parent,result:reports.append(dict(result))),\
         patch('sd_export_lifecycle.quiesce',side_effect=quiesce),\
         patch('sd_export_lifecycle.cancel_resume',side_effect=cancel),\
         patch('sd_flush_barrier.cancel_resume',side_effect=cancel):
        export=namespace['export_virtual_sd']
        assert export()['ok'] is False
        assert namespace['pending_sd_sequence']==[1000] and stopped==[1000]
        if failures==2:
            with pytest.raises(OSError,match='ENOSPC'):export()
            assert namespace['pending_sd_sequence']==[1000] and flushes==[1000]
        assert export()['ok'] is True
    assert flushes==[1000,2000]
    assert cancellations==[1000]*(failures+1)+[2000]
    assert namespace['pending_sd_sequence']==[None] and stopped==[]
    assert reports[0]['ok'] is False and reports[-1]['ok'] is True


def test_final_report_failure_keeps_written_digest_but_not_a_pending_owner(tmp_path):
    path=Path(__file__).with_name('qemu-menu-probe.py')
    function=next(n for n in ast.walk(ast.parse(path.read_text())) if isinstance(n,ast.FunctionDef) and n.name=='export_virtual_sd')
    namespace=dict(out=tmp_path,manifest={'rm_file_image_bytes':512},virtual_hci=False,early_media_watch=None,request_queue_gdb=False,os=SimpleNamespace(environ={}),
                   pending_sd_sequence=[None],last_sd_export_sha=[None],
                   time=SimpleNamespace(monotonic_ns=lambda:1000))
    exec(compile(ast.Module(body=[function],type_ignores=[]),str(path),'exec'),namespace)
    (tmp_path/'SD').mkdir()
    with patch('sd_transport.export_card',return_value={'ok':True,'sha256':'b'*64,'card_published':True}),\
         patch('sd_transport.report',side_effect=OSError('final report ENOSPC')),\
         patch('sd_export_lifecycle.cancel_resume',return_value={'ok':True,'status':'resumed'}):
        with pytest.raises(OSError,match='ENOSPC'):namespace['export_virtual_sd']()
    assert namespace['pending_sd_sequence']==[None]
    assert namespace['last_sd_export_sha']==['b'*64]


@pytest.mark.parametrize('resume_fails',[False,True])
def test_debug_CPU_resume_precedes_old_sequence_recovery_and_new_flush(tmp_path,resume_fails):
    import json
    path=Path(__file__).with_name('qemu-menu-probe.py')
    function=next(n for n in ast.walk(ast.parse(path.read_text())) if isinstance(n,ast.FunctionDef) and n.name=='export_virtual_sd')
    events=[];running=[False]
    def qmp(command):
        events.append(command)
        if command=='cont':
            if resume_fails:raise RuntimeError('debugger CPU resume failed')
            running[0]=True;return {'return':{}}
        return {'return':{'running':running[0],'status':'running' if running[0] else 'debug'}}
    namespace=dict(out=tmp_path,manifest={'rm_file_image_bytes':512},virtual_hci=False,early_media_watch=None,request_queue_gdb=True,
                   qmp=qmp,json=json,os=SimpleNamespace(environ={}),pending_sd_sequence=[77],last_sd_export_sha=[None],
                   time=SimpleNamespace(monotonic_ns=lambda:1000))
    exec(compile(ast.Module(body=[function],type_ignores=[]),str(path),'exec'),namespace)
    (tmp_path/'SD').mkdir()
    def prior(serial,sequence):
        assert running[0] and sequence==77;events.append('prior-recovery');return {'ok':True,'status':'resumed'}
    def quiesce(serial,sequence):
        assert running[0] and sequence==1000;events.append('flush');return {'owner_stopped':True}
    def capture(out,total,**kwargs):
        kwargs['quiesce']();return {'ok':True,'sha256':'c'*64,'card_published':True}
    with patch('sd_transport.export_card',side_effect=capture) as export_card,\
         patch('sd_transport.report'),patch('sd_flush_barrier.cancel_resume',side_effect=prior),\
         patch('sd_export_lifecycle.quiesce',side_effect=quiesce),\
         patch('sd_export_lifecycle.cancel_resume',return_value={'ok':True,'status':'resumed'}):
        if resume_fails:
            with pytest.raises(RuntimeError,match='CPU resume failed'):namespace['export_virtual_sd']()
            assert namespace['pending_sd_sequence']==[77] and events==['query-status','cont']
            export_card.assert_not_called()
        else:
            assert namespace['export_virtual_sd']()['ok']
            assert events==['query-status','cont','query-status','prior-recovery','flush']
            assert namespace['pending_sd_sequence']==[None]


def test_observed_UI_branch_captures_bound_process_workers_not_only_UI(tmp_path):
    import re
    path=Path(__file__).with_name('qemu-menu-probe.py')
    function=next(n for n in ast.walk(ast.parse(path.read_text())) if isinstance(n,ast.FunctionDef) and n.name=='export_virtual_sd')
    commands=[]
    def serial(proc,out,command,**kwargs):commands.append(command);return b'POWER_THREAD 333 worker\n'
    namespace=dict(out=tmp_path,manifest={'rm_file_image_bytes':512},virtual_hci=False,early_media_watch=None,request_queue_gdb=False,
                   os=SimpleNamespace(environ={'A7C2_CAPTURE_POWER_STACK':'1'}),re=re,serial_command=serial,proc=object(),
                   pending_sd_sequence=[None],last_sd_export_sha=[None],time=SimpleNamespace(monotonic_ns=lambda:1000))
    exec(compile(ast.Module(body=[function],type_ignores=[]),str(path),'exec'),namespace)
    (tmp_path/'console.log').write_text('OBS CREATE_SCREEN_UI_THREAD pid=217 tid=302\n');(tmp_path/'SD').mkdir()
    with patch('sd_transport.export_card',return_value={'ok':True,'sha256':'d'*64,'card_published':True}),\
         patch('sd_transport.report'),patch('sd_export_lifecycle.cancel_resume',return_value={'ok':True,'status':'resumed'}):
        assert namespace['export_virtual_sd']()['ok']
    assert len(commands)==1 and 'for t in /proc/217/task/[0-9]*' in commands[0]
    assert 'POWER_UI_TID=302' in commands[0] and 'POWER_THREAD' in commands[0]
    assert commands[0].isascii() and '/proc/[0-9]*/maps' not in commands[0]


def test_sequence_stack_command_rejects_unbound_process_ids():
    from request_queue_watch import sequence_stack_command
    for pid in ('217;exit',True,0,1,2**31):
        with pytest.raises(ValueError):sequence_stack_command(pid,302)
