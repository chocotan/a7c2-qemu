#!/usr/bin/env python3
"""Host-only handoff checks; temporary executables replace all guest programs."""
import argparse
import ast
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

HERE=Path(__file__).resolve().parent
RUNNER=(HERE/'run-full-system.py').read_text()
TREE=ast.parse(RUNNER)
WRAPPER=(HERE/'guest/bootin-wrapper').read_text()
PIN='dab3ce4b6c28a6c9ffd9f0b893dce1d08f3ee7302a09df87e518409e728be2f2'


def api():
    names={'validate_bootin_handoff','prepare_bootin_handoff','main','FullFirmwareMonitor','finish_owned_run'}
    nodes=[node for node in TREE.body if
           (isinstance(node,(ast.FunctionDef,ast.ClassDef)) and node.name in names) or
           (isinstance(node,ast.Assign) and any(isinstance(target,ast.Name) and target.id=='BOOTIN_ORIGINAL_SHA256' for target in node.targets))]
    namespace=dict(argparse=argparse,hashlib=hashlib,json=json,os=os,Path=Path,re=re,sys=sys,HERE=HERE,
                   tempfile=tempfile,terminate_owned=Mock(),
                   FirmwareMonitor=type('Monitor',(),{'__init__':lambda self,path:None,'check':lambda self:None}),
                   signal=SimpleNamespace(SIGTERM=15,signal=Mock()),
                   runpy=SimpleNamespace(run_path=lambda _: {'open_runtime_lock':lambda _:object(),'card_receipt':lambda _:None,'validate_runtime':lambda *args:None}),
                   subprocess=SimpleNamespace(Popen=Mock(side_effect=AssertionError('VM forbidden'))))
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(HERE/'run-full-system.py'),'exec'),namespace)
    return namespace


class Handoff(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base=Path(self.temporary.name)
        self.paths={
            'wrapper_sha256':self.base/'root/simulation/p15-wrapper-source',
            'derived_usr_sha256':self.base/'root/partitions/a7c2-usr.img',
            'virtual_sd_sha256':self.base/'root/partitions/bootin-sd-ext2.img',
        }
        self.metadata=dict(schema=1,original_elf_sha256=PIN,virtual_sd_present=True,case='valid-sd')
        for key,path in self.paths.items():
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_bytes(('host fixture '+key).encode())
            self.metadata[key]=hashlib.sha256(path.read_bytes()).hexdigest()
        self.api=api()
        self.validate=self.api['validate_bootin_handoff']
        self.prepare=self.api['prepare_bootin_handoff']

    def validate_metadata(self,metadata=None,stage='init2',handoff='p15-wrapper'):
        return self.validate(stage,handoff,{'bootin_wrapper_experiment':self.metadata if metadata is None else metadata},self.base)

    def test_default_ignores_experiment_and_keeps_original_three_commands(self):
        self.assertIsNone(self.validate('mounts','simulation-bind',{'bootin_wrapper_experiment':object()},None))
        commands=[]
        self.prepare(lambda command:commands.append(command),'simulation-bind',None,None)
        self.assertEqual(commands,[
            'cp /usr/bin/bootin.elf /simulation/bootin-original',
            'chmod 755 /simulation/bootin-original',
            'mount -o bind /simulation/bootin-wrapper /usr/bin/bootin.elf'])

    def test_all_declared_cases_and_absent_card(self):
        for case in ('plain','valid-sd','absent-sd','bad-sd'):
            metadata={**self.metadata,'case':case}
            with self.subTest(case=case):self.assertEqual(self.validate_metadata(metadata),metadata)
        absent={**self.metadata,'virtual_sd_present':False,'virtual_sd_sha256':None,'case':'plain',
                'trusted_virtual_sd_sha256':'retained extra','source_usr_sha256':'retained source'}
        self.assertEqual(self.validate_metadata(absent),absent)
        self.paths['virtual_sd_sha256'].unlink()
        self.assertEqual(self.validate_metadata(absent),absent)
        with self.assertRaisesRegex(ValueError,'ordinary'):self.validate_metadata()

    def test_missing_metadata_invalid_stage_and_schema_fields(self):
        with self.assertRaisesRegex(ValueError,'bootin_wrapper_experiment'):
            self.validate('init2','p15-wrapper',{},self.base)
        for stage in ('mounts','drivers'):
            with self.subTest(stage=stage),self.assertRaisesRegex(ValueError,'requires init2'):
                self.validate_metadata(stage=stage)
        for key in self.metadata:
            metadata=dict(self.metadata);metadata.pop(key)
            with self.subTest(missing=key),self.assertRaises(ValueError):self.validate_metadata(metadata)
        for key,value in (('schema',True),('schema',2),('virtual_sd_present',1),('case','VALID-SD'),
                          ('original_elf_sha256','a'*64),('original_elf_sha256',PIN.upper()),
                          ('wrapper_sha256','A'*64),('derived_usr_sha256',[]),('virtual_sd_sha256','x')):
            with self.subTest(key=key,value=value),self.assertRaises(ValueError):
                self.validate_metadata({**self.metadata,key:value})

    def test_hash_mismatch_and_nonordinary_inputs(self):
        for key,path in self.paths.items():
            original=path.read_bytes()
            path.write_bytes(b'changed')
            with self.subTest(key=key,kind='hash'),self.assertRaisesRegex(ValueError,'SHA256 differs'):
                self.validate_metadata()
            path.unlink()
            source=self.base/(key+'.fixture');source.write_bytes(original)
            path.symlink_to(source)
            with self.subTest(key=key,kind='symlink'),self.assertRaisesRegex(ValueError,'ordinary'):
                self.validate_metadata()
            path.unlink();path.mkdir()
            with self.subTest(key=key,kind='directory'),self.assertRaisesRegex(ValueError,'ordinary'):
                self.validate_metadata()
            path.rmdir();path.write_bytes(original)

    def test_linked_input_directories_are_rejected(self):
        for name in ('simulation','partitions'):
            directory=self.base/'root'/name
            moved=self.base/(name+'-source');directory.rename(moved);directory.symlink_to(moved,target_is_directory=True)
            with self.subTest(name=name),self.assertRaisesRegex(ValueError,'ordinary'):self.validate_metadata()
            directory.unlink();moved.rename(directory)

    def guest_run(self,commands,wrong_path=None,response=None,fail=None):
        hashes={'/usr/bin/bootin.elf':self.metadata['wrapper_sha256'],
                '/usr/bin/bootin-original':PIN,
                '/partitions/bootin-sd-ext2.img':self.metadata['virtual_sd_sha256']}
        def run(command,**kwargs):
            commands.append(command)
            if command==fail:raise RuntimeError('Guest command failed, return code 7')
            if command.startswith('/usr/bin/openssl dgst -sha256 '):
                path=command.split()[-1]
                if path==wrong_path:return response
                return f'SHA256({path})= {hashes[path]}\r\nMENU_DIAG_COMMAND_DONE_fixture:0\n'.encode()
            return b'MENU_DIAG_COMMAND_DONE_fixture:0\n'
        return run

    def test_guest_pins_before_readonly_card_attachment_and_no_entry_bind(self):
        commands=[]
        run=Mock(wraps=self.guest_run(commands))
        self.prepare(run,'p15-wrapper',self.metadata,self.base)
        self.assertEqual([call.kwargs['timeout'] for call in run.call_args_list[:3]],[30,30,120])
        checks=json.loads((self.base/'bootin-handoff-readback.json').read_text())
        self.assertEqual(len(checks),3)
        self.assertTrue(all(row['verified'] and row['raw_output_hex'] for row in checks))
        self.assertEqual(commands[-5:],[
            '[ ! -e /dev/loop18 ] && [ ! -L /dev/loop18 ]',
            'busybox mknod /dev/loop18 b 7 18',
            '/simulation/attach-loop 18 /partitions/bootin-sd-ext2.img ro',
            'ln -s /dev/loop18 /dev/mmca2',
            '[ "$(busybox readlink /dev/mmca2)" = /dev/loop18 ]'])
        self.assertTrue(all(not command.startswith(('cp ','mount ')) for command in commands))
        self.assertLess(commands.index('[ ! -e /dev/mmca2 ] && [ ! -L /dev/mmca2 ]'),commands.index('busybox mknod /dev/loop18 b 7 18'))

    def test_absent_card_creates_no_node_or_link(self):
        commands=[]
        self.prepare(self.guest_run(commands),'p15-wrapper',
                     {**self.metadata,'virtual_sd_present':False,'virtual_sd_sha256':None},self.base)
        self.assertEqual(len(json.loads((self.base/'bootin-handoff-readback.json').read_text())),2)
        self.assertTrue(all('loop18' not in command and not command.startswith('ln ') for command in commands))

    def test_guest_digest_mismatch_or_ambiguous_output_stops_before_card(self):
        path='/usr/bin/bootin.elf'
        for response in (b'no digest\n',f'SHA256({path})= {"0"*64}\n'.encode(),
                         f'SHA256({path})= {self.metadata["wrapper_sha256"].upper()}\n'.encode(),
                         (f'SHA256({path})= {self.metadata["wrapper_sha256"]}\n'*2).encode()):
            commands=[]
            with self.subTest(response=response),self.assertRaisesRegex(RuntimeError,'SHA256 differs'):
                self.prepare(self.guest_run(commands,path,response),'p15-wrapper',self.metadata,self.base)
            self.assertEqual(len(commands),1)
            self.assertFalse(json.loads((self.base/'bootin-handoff-readback.json').read_text())[-1]['verified'])

    def test_existing_nodes_and_command_failure_stop_setup(self):
        for command in ('[ ! -e /dev/mmca2 ] && [ ! -L /dev/mmca2 ]',
                        '[ ! -e /dev/loop18 ] && [ ! -L /dev/loop18 ]',
                        '/simulation/attach-loop 18 /partitions/bootin-sd-ext2.img ro'):
            commands=[]
            with self.subTest(command=command),self.assertRaisesRegex(RuntimeError,'return code 7'):
                self.prepare(self.guest_run(commands,fail=command),'p15-wrapper',self.metadata,self.base)
            self.assertEqual(commands[-1],command)
            self.assertNotIn('ln -s /dev/loop18 /dev/mmca2',commands)

    def test_handoff_failure_is_failed_in_live_and_terminal_evidence(self):
        (self.base/'console.log').write_bytes(b'FULLSYSTEM_BOOTIN_HANDOFF_FAILED sha256\n')
        with self.assertRaisesRegex(RuntimeError,'bootin handoff failed'):
            self.api['FullFirmwareMonitor'](self.base/'console.log').check()
        for prior in (None,'preserved original error'):
            result={'state':'observation-completed'}
            if prior:result['error']=prior
            self.api['finish_owned_run'](None,result,self.base)
            self.assertEqual(result['state'],'failed')
            self.assertTrue(result['terminal_evidence_checked'])
            self.assertIn('bootin handoff',result['terminal_errors'][0])
            if prior:self.assertEqual(result['error'],prior)

    def test_cli_rejects_invalid_stage_choice_and_missing_metadata_before_vm(self):
        (self.base/'full-system.json').write_text('{}')
        self.api.update(BASE=self.base,HERE=self.base)
        for flags,message in ((['--bootin-handoff','p15-wrapper'],'requires init2'),
                              (['--stage','drivers','--bootin-handoff','p15-wrapper'],'requires init2'),
                              (['--stage','init2','--bootin-handoff','p15-wrapper'],'bootin_wrapper_experiment'),
                              (['--bootin-handoff','P15-WRAPPER'],'invalid choice')):
            error=io.StringIO()
            with self.subTest(flags=flags),patch.object(sys,'argv',['run-full-system.py',*flags]),contextlib.redirect_stderr(error):
                with self.assertRaises(SystemExit) as stopped:self.api['main']()
            self.assertEqual(stopped.exception.code,2)
            self.assertIn(message,error.getvalue())
        self.api['subprocess'].Popen.assert_not_called()

    def test_explicit_cmdline_and_preparation_are_wired_in_main(self):
        main=next(node for node in TREE.body if isinstance(node,ast.FunctionDef) and node.name=='main')
        gate=next(node for node in ast.walk(main) if isinstance(node,ast.If) and
                  'handoff.append(\'fullsystem.bootin-handoff=p15-wrapper\')' in ast.unparse(node))
        for mode,expected in (('simulation-bind',[]),('p15-wrapper',['fullsystem.bootin-handoff=p15-wrapper'])):
            namespace={'args':SimpleNamespace(bootin_handoff=mode),'handoff':[]}
            exec(compile(ast.Module(body=[gate],type_ignores=[]),'handoff-cmdline','exec'),namespace)
            self.assertEqual(namespace['handoff'],expected)
        self.assertIn('prepare_bootin_handoff(run,args.bootin_handoff,bootin_experiment,out)',RUNNER)


@unittest.skipUnless(shutil.which('openssl'),'requires host openssl')
class Wrapper(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root=Path(self.temporary.name)
        self.capture=self.root/'captured.json'
        self.cmdline=self.root/'cmdline'
        self.cmdline.write_text('fullsystem.bootin-handoff=p15-wrapper')
        self.targets={path:self.root/name for path,name in (
            ('/usr/bin/bootin-original','usr-original'),('/log/a7c2/bootin-original','log-original'),
            ('/simulation/bootin-original','simulation-original'))}
        fixture=('#!'+sys.executable+'\nimport json,os,sys\n'
                 'from pathlib import Path\n'
                 'Path(os.environ["BOOTIN_TEST_CAPTURE"]).write_text(json.dumps('
                 '{"argv":sys.argv,"pid":os.getpid(),"gpe":os.environ.get("QEMU_SOFTWARE_GPE")}))\n')
        for target in self.targets.values():target.write_text(fixture);target.chmod(0o755)
        self.digest=hashlib.sha256(fixture.encode()).hexdigest()
        body=WRAPPER.replace(PIN,self.digest).replace('/proc/cmdline',str(self.cmdline))
        for path,target in self.targets.items():body=body.replace(path,str(target))
        for name in ('seed-power-on','init-clock','ramfb-viewer'):
            stub=self.root/name;stub.write_text('#!/bin/sh\nexit 0\n');stub.chmod(0o755)
            body=body.replace('/simulation/'+name,str(stub))
        logs=self.root/'qemu';logs.mkdir()
        self.body=body.replace('/log/qemu',str(logs)).replace('/simulation/menu-observe.so','')
        self.environment={**os.environ,'LD_PRELOAD':'','BOOTIN_TEST_CAPTURE':str(self.capture)}

    def run_wrapper(self,args,body=None):
        return subprocess.run(['/bin/sh','-c',self.body if body is None else body,'bootin-wrapper',*args],
                              env=self.environment,capture_output=True,text=True,timeout=10)

    def test_allowed_targets_and_argument_boundaries_preserve_full_adapter(self):
        extra=['dmode=3','argument with spaces','',"literal;$()'\"",'--original-elf','unchanged']
        for path in ('/usr/bin/bootin-original','/log/a7c2/bootin-original'):
            result=self.run_wrapper(['--original-elf',str(self.targets[path]),*extra])
            self.assertEqual(result.returncode,0,result.stderr+result.stdout)
            captured=json.loads(self.capture.read_text())
            self.assertEqual(captured['argv'],[str(self.targets[path]),*extra])
            self.assertEqual(captured['gpe'],'1')
            self.assertIn('FULLSYSTEM_BOOTIN_ENTER',result.stdout)
            markers=re.findall(r'FULLSYSTEM_BOOTIN_ORIGINAL path=(\S+) pid=(\d+) argc=(\d+)',result.stdout)
            self.assertEqual(markers,[(str(self.targets[path]),str(captured['pid']),str(len(extra)))])

    def test_default_arguments_are_unchanged_without_hash_check(self):
        self.cmdline.write_text('')
        body=self.body.replace('/usr/bin/openssl','/host-test-must-not-run-openssl')
        result=self.run_wrapper(['dmode=3','two words',''],body)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertNotIn('FULLSYSTEM_BOOTIN_ORIGINAL',result.stdout)
        self.assertEqual(json.loads(self.capture.read_text())['argv'],
                         [str(self.targets['/simulation/bootin-original']),'dmode=3','two words',''])

    def test_exact_profile_and_literal_paths_required_before_adapter(self):
        target=str(self.targets['/usr/bin/bootin-original'])
        for cmdline in ('','fullsystem.bootin-handoff=simulation-bind','fullsystem.bootin-handoff=P15-WRAPPER',
                        'prefixfullsystem.bootin-handoff=p15-wrapper','fullsystem.bootin-handoff=p15-wrapper-extra'):
            self.cmdline.write_text(cmdline)
            result=self.run_wrapper(['--original-elf',target])
            self.assertNotEqual(result.returncode,0)
            self.assertIn('HANDOFF_FAILED profile',result.stdout)
            self.assertNotIn('FULLSYSTEM_BOOTIN_ENTER',result.stdout)
        self.cmdline.write_text('fullsystem.bootin-handoff=p15-wrapper')
        for args in (['--original-elf'],['--original-elf','/tmp/evil'],
                     ['--original-elf',str(self.targets['/simulation/bootin-original'])],
                     ['--original-elf',target+'/../usr-original']):
            result=self.run_wrapper(args)
            self.assertNotEqual(result.returncode,0)
            self.assertIn('HANDOFF_FAILED path',result.stdout)
        self.assertFalse(self.capture.exists())

    def test_missing_nonexecutable_changed_elf_and_openssl_failure(self):
        target=self.targets['/usr/bin/bootin-original'];original=target.read_bytes()
        target.chmod(0o644)
        self.assertIn('HANDOFF_FAILED executable',self.run_wrapper(['--original-elf',str(target)]).stdout)
        target.chmod(0o755);target.write_bytes(original+b'\n# changed\n')
        self.assertIn('HANDOFF_FAILED sha256',self.run_wrapper(['--original-elf',str(target)]).stdout)
        target.unlink()
        self.assertIn('HANDOFF_FAILED executable',self.run_wrapper(['--original-elf',str(target)]).stdout)
        target.write_bytes(original);target.chmod(0o755)
        stub=self.root/'openssl-fail';stub.write_text('#!/bin/sh\nexit 7\n');stub.chmod(0o755)
        result=self.run_wrapper(['--original-elf',str(target)],self.body.replace('/usr/bin/openssl',str(stub)))
        self.assertIn('HANDOFF_FAILED digest',result.stdout)
        self.assertFalse(self.capture.exists())

    def test_uppercase_or_multiline_digest_is_rejected(self):
        target=self.targets['/usr/bin/bootin-original']
        for output in (f'SHA256({target})= {self.digest.upper()}',
                       f'SHA256({target})= {self.digest}\nSHA256({target})= {self.digest}'):
            stub=self.root/'openssl-output'
            stub.write_text('#!'+sys.executable+'\nprint('+repr(output)+')\n');stub.chmod(0o755)
            result=self.run_wrapper(['--original-elf',str(target)],self.body.replace('/usr/bin/openssl',str(stub)))
            self.assertNotEqual(result.returncode,0)
            self.assertIn('HANDOFF_FAILED sha256',result.stdout)
        self.assertFalse(self.capture.exists())


if __name__=='__main__':unittest.main()
