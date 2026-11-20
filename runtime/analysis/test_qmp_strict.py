"""Synthetic QMP regressions; no QEMU, subprocesses or signals.

Run in a project test-group directory with TMPDIR and pytest --basetemp inside
that directory. Keep failed evidence files. Each test resets its request IDs.
"""
from contextlib import ExitStack
import errno
import itertools
import json
import os
from pathlib import Path
import socket
import struct
import threading
from types import SimpleNamespace

import pytest

import menu_live as live

RETAINED_SYNTHETIC_RESOURCES=[]
GREETING=b'{"QMP":{"version":{},"capabilities":[]}}\r\n'


def frame(value):return (json.dumps(value)+'\r\n').encode()


def ack(index=1,**body):return frame(dict(id=f'{index:032x}',**(body or {'return':{}})))


@pytest.fixture
def api(monkeypatch,tmp_path):
    raw=Path(os.environ['TMPDIR'])
    group=raw.resolve(strict=True)
    assert raw.is_absolute() and raw == group and not group.is_relative_to('/tmp') and not group.is_relative_to('/var/tmp')
    info=group.stat()
    assert info.st_uid==os.geteuid() and info.st_mode&0o777==0o700,'Private test group required'
    assert tmp_path.resolve().is_relative_to(group),'Keep pytest basetemp inside group TMPDIR'
    monkeypatch.setattr(live,'secrets',SimpleNamespace(
        token_hex=lambda _n,counter=itertools.count(1):f'{next(counter):032x}'))
    return live


@pytest.fixture
def channel(api,tmp_path):
    with ExitStack() as resources:
        client,peer=socket.socketpair()
        resources.enter_context(client);resources.enter_context(peer)
        client.settimeout(.05);peer.settimeout(.05)
        path=tmp_path/'qmp-rx.bin'
        fd=os.open(path,os.O_RDWR|os.O_CREAT|os.O_EXCL|os.O_CLOEXEC,0o600)
        stages=[]
        c=SimpleNamespace(api=api,client=client,peer=peer,fd=fd,path=path,
                          stages=stages,owner=SimpleNamespace(),threads=[])
        resources.callback(lambda:os.close(c.fd) if c.fd is not None else None)
        stream=api.QMPStrictStream(client,fd,stages.append,synthetic_only=True)
        c.stream=stream
        def close_stream():
            expected=getattr(c,'close_error',None)
            if expected is None:stream.close()
            else:
                with pytest.raises(type(expected)) as caught:stream.close()
                assert caught.value is expected
        resources.callback(close_stream)
        try:
            yield c
        finally:
            for worker in c.threads:
                if worker.ident is not None:worker.join(3)
            live=[worker for worker in c.threads if worker.is_alive()]
            if live:
                RETAINED_SYNTHETIC_RESOURCES.append((resources.pop_all(),c,live))
                raise RuntimeError('Synthetic workers unresolved; socket/FD references retained, no forced cleanup')


def greet(c):
    c.peer.sendall(GREETING)
    assert 'QMP' in c.stream.greeting(c.owner)


def rejected_again(c):
    with pytest.raises(RuntimeError):c.api.qmp_transaction(c.owner,c.stream,'quit')
    assert c.owner._menu_qmp_desynchronized and c.stream._failed


def test_greeting_events_and_success_keep_raw_and_legacy_shape(channel):
    c=channel
    event=frame({'event':'RESET'})
    reply=ack(**{'return':{'running':True}})
    c.peer.sendall(GREETING+event+reply)
    assert 'QMP' in c.stream.greeting(c.owner)
    assert c.api.qmp_transaction(c.owner,c.stream,'query-status')=={'return':{'running':True}}
    assert c.path.read_bytes()==GREETING+event+reply
    assert c.stages.count('frame')==3 and c.stages.count('ack')==2
    assert c.peer.recv(4096)==frame({'execute':'query-status','id':f'{1:032x}'}).replace(b'\r\n',b'\n')
    assert not c.owner._menu_qmp_desynchronized


def test_matching_error_is_known_boundary_and_allows_next_command(channel):
    c=channel;greet(c)
    c.peer.sendall(ack(error={'desc':'refused'}))
    with pytest.raises(RuntimeError,match='refused'):
        c.api.qmp_transaction(c.owner,c.stream,'query-status')
    assert not c.owner._menu_qmp_desynchronized and not c.stream._failed
    c.peer.sendall(ack(2))
    assert c.api.qmp_transaction(c.owner,c.stream,'query-status')=={'return':{}}


@pytest.mark.parametrize('raw',[
    b'{"return":{},"id":"stale"}\n',
    b'{"return":{},"return":{},"id":"00000000000000000000000000000001"}\n',
    b'[]\n',b'{broken}\n',
    b'{"id":"00000000000000000000000000000001","return":{},"error":{}}\n',
])
def test_invalid_frame_latches_and_retains_exact_bytes(channel,raw):
    c=channel;greet(c);c.peer.sendall(raw)
    with pytest.raises((OSError,ValueError)):
        c.api.qmp_transaction(c.owner,c.stream,'query-status')
    assert c.path.read_bytes()==GREETING+raw
    rejected_again(c)


def test_half_frame_then_timeout_is_durable_before_failure(channel):
    c=channel;greet(c)
    half=b'{"return":{"running":'
    c.peer.sendall(half)
    with pytest.raises(TimeoutError):c.api.qmp_transaction(c.owner,c.stream,'query-status')
    assert c.path.read_bytes()==GREETING+half
    rejected_again(c)


def test_partial_greeting_and_eof_are_preserved(channel):
    c=channel
    partial=b'{"QMP":'
    c.peer.sendall(partial);c.peer.shutdown(socket.SHUT_WR)
    with pytest.raises(OSError):c.stream.greeting(c.owner)
    assert c.path.read_bytes()==partial
    rejected_again(c)


@pytest.mark.parametrize('stage',['send','recv-complete','frame','ack'])
def test_generation_failure_never_acknowledges_or_retries(channel,stage):
    c=channel;greet(c)
    reply=ack();c.peer.sendall(reply)
    def changed(current):
        c.stages.append(current)
        if current==stage:raise ValueError('synthetic generation changed')
    c.stream.check_generation=changed
    with pytest.raises(ValueError,match='generation changed'):
        c.api.qmp_transaction(c.owner,c.stream,'query-status')
    if stage!='send':assert c.path.read_bytes()==GREETING+reply
    rejected_again(c)


def test_every_buffered_frame_has_generation_check(channel):
    c=channel
    c.peer.sendall(GREETING+frame({'event':'STOP'})+ack())
    c.stream.greeting(c.owner)
    checks=[]
    def changed(stage):
        checks.append(stage)
        if stage=='frame' and checks.count('frame')==2:
            raise ValueError('generation changed before buffered ACK')
    c.stream.check_generation=changed
    with pytest.raises(ValueError,match='buffered ACK'):
        c.api.qmp_transaction(c.owner,c.stream,'query-status')
    assert checks.count('frame')==2
    rejected_again(c)


def test_evidence_replacement_or_append_fails_closed(channel):
    c=channel;greet(c)
    os.pwrite(c.fd,b'foreign append',len(GREETING))
    c.peer.sendall(ack())
    with pytest.raises(ValueError,match='identity or length'):
        c.api.qmp_transaction(c.owner,c.stream,'query-status')
    assert c.owner._menu_qmp_last_raw==ack()
    rejected_again(c)


def test_fd_callback_preserves_real_scm_rights(channel,tmp_path):
    c=channel;greet(c);c.peer.sendall(ack())
    passed=os.open(tmp_path/'owned-payload',os.O_RDWR|os.O_CREAT|os.O_EXCL|os.O_CLOEXEC,0o600)
    received=[]
    try:
        os.write(passed,b'synthetic fd\n')
        sent=[]
        def send(encoded):
            sent.append(encoded)
            return c.client.sendmsg([encoded],[(socket.SOL_SOCKET,socket.SCM_RIGHTS,struct.pack('i',passed))])
        assert c.api.qmp_transaction(c.owner,c.stream,'getfd',{'fdname':'owned'},send=send)=={'return':{}}
        wire,ancillary,flags,_=c.peer.recvmsg(4096,socket.CMSG_SPACE(struct.calcsize('i')))
        for level,kind,payload in ancillary:
            if level==socket.SOL_SOCKET and kind==socket.SCM_RIGHTS:
                received.extend(struct.unpack('i'*(len(payload)//struct.calcsize('i')),payload))
        assert flags==0 and wire==sent[0] and len(sent)==1 and len(received)==1
        assert os.pread(received[0],32,0)==b'synthetic fd\n'
    finally:
        for fd in received:os.close(fd)
        os.close(passed)


def test_partial_fd_send_latches_without_receiving(channel):
    c=channel;greet(c);sent=[]
    def partial(raw):sent.append(raw);return len(raw)-1
    with pytest.raises(OSError,match='Short QMP descriptor'):
        c.api.qmp_transaction(c.owner,c.stream,'getfd',{'fdname':'owned'},send=partial)
    assert len(sent)==1 and c.path.read_bytes()==GREETING
    rejected_again(c)


def test_concurrent_rejection_cannot_be_cleared_by_inflight_ack(channel):
    c=channel;greet(c);c.peer.sendall(ack())
    entered=threading.Event();release=threading.Event();errors=[]
    def block(stage):
        if stage=='ack':
            entered.set()
            if not release.wait(2):raise TimeoutError('synthetic test barrier expired')
    c.stream.check_generation=block
    def primary():
        try:c.api.qmp_transaction(c.owner,c.stream,'query-status')
        except BaseException as error:errors.append(error)
    worker=threading.Thread(target=primary)
    c.threads.append(worker)
    worker.start()
    try:
        assert entered.wait(2),'primary did not reach ACK barrier'
        with pytest.raises(RuntimeError,match='failure latched'):
            c.api.qmp_transaction(c.owner,c.stream,'quit')
    finally:
        release.set();worker.join(3)
    assert not worker.is_alive() and len(errors)==1
    assert c.path.read_bytes()==GREETING+ack()
    assert json.loads(c.peer.recv(4096))['execute']=='query-status'
    rejected_again(c)


@pytest.mark.parametrize('boundary',['fstat','pwrite','fsync','pread'])
def test_swallowed_rx_evidence_reentry_records_outer_bytes_but_rejects_ack(channel,monkeypatch,boundary):
    c=channel;greet(c);c.peer.sendall(ack())
    original=getattr(os,boundary)
    seen=[]
    def call(fd,*args):
        result=original(fd,*args)
        if fd==c.stream._rx_fd and not seen:
            seen.append(boundary)
            with pytest.raises(RuntimeError,match='reentrant RX evidence'):
                c.stream._record(b'must-never-be-written')
        return result
    with monkeypatch.context() as patched:
        patched.setattr(os,boundary,call)
        with pytest.raises(RuntimeError,match='failure latched'):
            c.api.qmp_transaction(c.owner,c.stream,'query-status')
    assert seen==[boundary]
    assert c.stream._received==len(GREETING)+len(ack()) and not c.stream._recording
    assert c.path.read_bytes()==GREETING+ack()
    assert c.stream._failure_requested.is_set()
    rejected_again(c)


def test_announced_concurrent_failure_blocks_ack_while_state_update_waits(channel):
    c=channel;greet(c);c.peer.sendall(ack())
    entered=threading.Event();resume=threading.Event();errors=[]
    def pause(stage):
        if stage=='ack':
            entered.set()
            if not resume.wait(2):raise TimeoutError('synthetic ACK barrier expired')
    c.stream.check_generation=pause
    def request(name):
        try:c.api.qmp_transaction(c.owner,c.stream,name)
        except BaseException as error:errors.append((name,error))
    primary=threading.Thread(target=request,args=('query-status',))
    secondary=threading.Thread(target=request,args=('quit',))
    c.threads.extend((primary,secondary));primary.start()
    try:
        assert entered.wait(2)
        # Hold only the state mutation lock; failure announcement must precede it.
        with c.stream._state:
            secondary.start()
            assert c.stream._failure_requested.wait(1)
            resume.set()
    finally:
        resume.set()
        for worker in c.threads:
            if worker.ident is not None:worker.join(3)
    assert all(not worker.is_alive() for worker in c.threads)
    assert {name for name,_error in errors}=={'query-status','quit'}
    assert c.path.read_bytes()==GREETING+ack()
    assert json.loads(c.peer.recv(4096))['execute']=='query-status'
    rejected_again(c)


def test_requires_greeting(channel):
    c=channel
    with pytest.raises(RuntimeError,match='boundary unavailable'):
        c.api.qmp_transaction(c.owner,c.stream,'query-status')
    assert c.path.read_bytes()==b''
    rejected_again(c)


def test_cannot_rebind_owner(channel):
    c=channel;greet(c)
    other=SimpleNamespace()
    with pytest.raises(RuntimeError,match='boundary unavailable'):
        c.api.qmp_transaction(other,c.stream,'query-status')
    assert c.owner._menu_qmp_desynchronized and other._menu_qmp_desynchronized
    rejected_again(c)


def test_legacy_stream_remains_unchanged(api):
    class Legacy:
        def write(self,raw):self.request=json.loads(raw);return len(raw)
        def flush(self):pass
        def readline(self,_limit):return frame({'id':self.request['id'],'return':{}})
    owner=SimpleNamespace()
    assert api.qmp_transaction(owner,Legacy(),'query-status')=={'return':{}}
    assert owner._menu_qmp_desynchronized is False


@pytest.mark.parametrize('when',['waiting','consumed'])
@pytest.mark.parametrize('reject',['transaction','close'])
def test_failure_during_recv_still_durably_records_consumed_bytes(channel,monkeypatch,when,reject):
    c=channel;greet(c)
    c.client.settimeout(2)
    entered=threading.Event();consumed=threading.Event();release=threading.Event()
    original=socket.socket.recv
    errors=[]
    reply=ack()
    def controlled_recv(sock,*args):
        if sock is not c.client:return original(sock,*args)
        entered.set()
        raw=original(sock,*args)
        consumed.set()
        if not release.wait(2):raise TimeoutError('synthetic consumed-RX barrier expired')
        return raw
    def request():
        try:c.api.qmp_transaction(c.owner,c.stream,'query-status')
        except BaseException as error:errors.append(error)
    worker=threading.Thread(target=request)
    c.threads.append(worker)
    with monkeypatch.context() as patched:
        patched.setattr(socket.socket,'recv',controlled_recv)
        worker.start()
        try:
            assert entered.wait(1),'primary never entered recv'
            if when=='consumed':
                c.peer.sendall(reply)
                assert consumed.wait(1),'primary never consumed reply'
            with pytest.raises(RuntimeError,match='failure latched'):
                if reject=='transaction':c.api.qmp_transaction(c.owner,c.stream,'quit')
                else:c.stream.close()
            if when=='waiting':c.peer.sendall(reply)
            assert consumed.wait(1)
        finally:
            release.set();worker.join(3)
    assert not worker.is_alive() and len(errors)==1
    assert isinstance(errors[0],RuntimeError) and 'failure latched' in str(errors[0])
    assert c.path.read_bytes()==GREETING+reply
    assert c.stream._received==len(GREETING)+len(reply)
    assert c.owner._menu_qmp_last_raw==reply
    assert not c.stream._acknowledged and not c.stream._recording
    assert json.loads(c.peer.recv(4096))['execute']=='query-status'
    rejected_again(c)
    with pytest.raises(TimeoutError):c.peer.recv(4096)


@pytest.mark.parametrize('boundary',['fstat','pwrite','fsync','pread'])
@pytest.mark.parametrize('reenter',[False,True])
def test_logging_failure_keeps_original_error_even_after_latch(channel,monkeypatch,boundary,reenter):
    c=channel;greet(c);c.peer.sendall(ack())
    original=getattr(os,boundary)
    failure=OSError('synthetic original evidence failure')
    seen=[]
    def broken(fd,*args):
        if fd==c.stream._rx_fd and not seen:
            seen.append(boundary)
            if reenter:
                with pytest.raises(RuntimeError,match='reentrant RX evidence'):
                    c.stream._record(b'must-never-be-written')
            else:c.stream._fail(c.owner)
            raise failure
        return original(fd,*args)
    with monkeypatch.context() as patched:
        patched.setattr(os,boundary,broken)
        with pytest.raises(OSError) as caught:
            c.api.qmp_transaction(c.owner,c.stream,'query-status')
    assert caught.value is failure and seen==[boundary]
    assert c.owner._menu_qmp_last_raw==ack()
    assert c.stream._received==len(GREETING) and not c.stream._recording
    assert c.stream._failure_requested.is_set()
    rejected_again(c)


def test_caller_fd_close_and_number_reuse_cannot_redirect_rx(channel,tmp_path):
    c=channel
    source=c.fd
    private=c.stream._rx_fd
    assert source!=private and not os.get_inheritable(private)
    os.close(source);c.fd=None
    foreign=os.open(tmp_path/'foreign-source-number',os.O_RDWR|os.O_CREAT|os.O_EXCL|os.O_CLOEXEC,0o600)
    try:
        if foreign!=source:
            os.dup2(foreign,source,inheritable=False)
            os.close(foreign)
        foreign=source
        os.write(foreign,b'untouched foreign data')
        greet(c);c.peer.sendall(ack())
        assert c.api.qmp_transaction(c.owner,c.stream,'query-status')=={'return':{}}
        assert c.path.read_bytes()==GREETING+ack()
        assert os.pread(foreign,128,0)==b'untouched foreign data'
        c.stream.close()
        assert os.pread(foreign,128,0)==b'untouched foreign data'
    finally:
        os.close(foreign)


@pytest.mark.parametrize('replace',[False,True])
def test_external_private_fd_close_or_reuse_is_rejected(channel,tmp_path,replace):
    c=channel
    private=c.stream._rx_fd
    os.close(private)
    expected=OSError
    foreign=None
    try:
        if replace:
            foreign=os.open(tmp_path/'forbidden-private-reuse',os.O_RDWR|os.O_CREAT|os.O_EXCL|os.O_CLOEXEC,0o600)
            if foreign!=private:
                os.dup2(foreign,private,inheritable=False)
                os.close(foreign)
                foreign=private
            os.write(private,b'foreign private number')
            expected=ValueError
        c.peer.sendall(GREETING)
        with pytest.raises(expected):c.stream.greeting(c.owner)
        assert c.path.read_bytes()==b'' and c.stream._received==0
        assert c.owner._menu_qmp_last_raw==GREETING
        rejected_again(c)
        with pytest.raises(expected) as caught:c.stream.close()
        c.close_error=caught.value
        assert c.stream._closed and c.stream._rx_fd is None
        assert c.stream._close_error is caught.value
        if replace:assert os.pread(private,128,0)==b'foreign private number'
    finally:
        # Release only this test's foreign FD; never restore the adapter's retired number.
        if foreign is not None:os.close(foreign)


@pytest.mark.parametrize('reason',['ebadf','identity','fstat-error'])
def test_close_identity_failure_cannot_touch_reused_same_inode_fd(channel,monkeypatch,tmp_path,reason):
    c=channel;greet(c)
    private=c.stream._rx_fd
    original_close,original_fstat=os.close,os.fstat
    failure=OSError(errno.EIO,'synthetic fstat failure before close')
    expected=ValueError if reason=='identity' else OSError
    owned=[];checks=[];closes=[]
    def check(fd):
        if fd==private:
            checks.append(fd)
            if reason=='fstat-error':raise failure
        return original_fstat(fd)
    def close(fd):
        if fd==private:
            closes.append(fd)
            raise AssertionError('Adapter must never close an unverified or retired FD number')
        return original_close(fd)
    try:
        if reason in ('ebadf','identity'):original_close(private)
        else:owned.append(private)  # Known synthetic duplicate; explicit fixture owner cleanup only.
        if reason=='identity':
            foreign=os.open(tmp_path/'foreign-before-retirement',os.O_RDWR|os.O_CREAT|os.O_EXCL|os.O_CLOEXEC,0o600)
            owned.append(foreign)
            if foreign!=private:
                os.dup2(foreign,private,inheritable=False)
                owned.append(private)
            os.write(private,b'foreign evidence FD')
        with monkeypatch.context() as patched:
            patched.setattr(os,'fstat',check)
            patched.setattr(os,'close',close)
            with pytest.raises(expected) as first:c.stream.close()
            error=first.value;c.close_error=error
            if reason=='ebadf':assert error.errno==errno.EBADF
            if reason=='identity':assert 'identity or length changed' in str(error)
            if reason=='fstat-error':assert error is failure
            assert c.stream._rx_fd is None and c.stream._closed
            assert c.stream._close_error is error
            assert c.stream._failed and c.stream._failure_requested.is_set()
            assert c.owner._menu_qmp_desynchronized
            assert checks==[private] and closes==[]
            if reason!='ebadf':
                # Only this fixture knows the still-live FD's provenance; the adapter may not retry it.
                info=original_fstat(private)
                identity=(info.st_dev,info.st_ino,info.st_mode,info.st_uid,info.st_nlink)
                if reason=='identity':assert identity!=c.stream._rx_identity
                else:assert identity==c.stream._rx_identity
                original_close(private);owned.remove(private)
            # Intentional new consumer, never cleanup restoration of an adapter-owned FD.
            replacement=os.open(c.path,os.O_RDWR|os.O_CLOEXEC)
            owned.append(replacement)
            if replacement!=private:
                os.dup2(replacement,private,inheritable=False)
                owned.append(private)
            info=original_fstat(private)
            assert (info.st_dev,info.st_ino,info.st_mode,info.st_uid,info.st_nlink)==c.stream._rx_identity
            with pytest.raises(expected) as second:c.stream.close()
            assert second.value is error and checks==[private] and closes==[]
            assert os.pread(private,1024,0)==GREETING
        # Unpatched retry would really close the same-inode new consumer if retirement failed.
        with pytest.raises(expected) as third:c.stream.close()
        assert third.value is error
        assert os.pread(private,1024,0)==GREETING
        assert original_fstat(c.fd).st_ino==original_fstat(private).st_ino
        assert os.pread(c.fd,1024,0)==GREETING and c.path.read_bytes()==GREETING
        c.client.sendall(b'client still open');assert c.peer.recv(64)==b'client still open'
        c.peer.sendall(b'peer still open');assert c.client.recv(64)==b'peer still open'
        rejected_again(c)
    finally:
        # All entries are known test-owned lifetimes; no attempt to restore a retired number.
        for fd in owned:original_close(fd)


def test_real_owner_adapter_is_fixed_unavailable(channel):
    c=channel
    with pytest.raises(RuntimeError,match='real owner adapter unavailable'):
        c.api.QMPStrictStream(c.client,c.fd,c.stages.append)
    with pytest.raises(RuntimeError,match='real owner adapter unavailable'):
        c.api.QMPStrictStream(c.client,c.fd,c.stages.append,synthetic_only=False)
    assert c.path.read_bytes()==b''


def test_shared_inode_prior_same_length_overwrite_is_explicitly_out_of_scope(channel):
    c=channel;greet(c)
    # Cooperative-contract limit: identity/size checks cannot authenticate the old prefix.
    before=os.fstat(c.fd)
    assert os.pwrite(c.fd,b'X',0)==1
    after=os.fstat(c.stream._rx_fd)
    assert (before.st_dev,before.st_ino,before.st_size)==(after.st_dev,after.st_ino,after.st_size)
    c.peer.sendall(ack())
    assert c.api.qmp_transaction(c.owner,c.stream,'query-status')=={'return':{}}
    assert c.path.read_bytes()==b'X'+GREETING[1:]+ack()
    # This synthetic outcome is a documented limitation, never an immutable-RX receipt.
    with pytest.raises(RuntimeError,match='real owner adapter unavailable'):
        c.api.QMPStrictStream(c.client,c.fd,c.stages.append)


def test_close_eio_after_real_release_cannot_close_reused_same_inode_fd(channel,monkeypatch):
    c=channel;greet(c)
    private=c.stream._rx_fd
    original=os.close
    failure=OSError(errno.EIO,'synthetic close failed after real release')
    c.close_error=failure
    calls=[];replacement=[]
    def close_then_fail(fd):
        if fd!=private:return original(fd)
        calls.append(fd)
        assert calls==[private],'Adapter retried an uncertain close'
        assert c.stream._rx_fd is None and c.stream._closed
        original(fd)
        replacement.append(os.open(c.path,os.O_RDWR|os.O_CLOEXEC))
        if replacement[0]!=private:
            os.dup2(replacement[0],private,inheritable=False)
            replacement.append(private)
        info=os.fstat(private)
        assert (info.st_dev,info.st_ino,info.st_mode,info.st_uid,info.st_nlink)==c.stream._rx_identity
        raise failure
    try:
        with monkeypatch.context() as patched:
            patched.setattr(os,'close',close_then_fail)
            with pytest.raises(OSError) as first:c.stream.close()
            assert first.value is failure and first.value.errno==errno.EIO
            assert c.stream._rx_fd is None and c.stream._closed
            assert c.stream._close_error is failure
            assert c.stream._failed and c.stream._failure_requested.is_set()
            assert c.owner._menu_qmp_desynchronized
            with pytest.raises(OSError) as second:c.stream.close()
            assert second.value is failure and calls==[private]
            assert os.pread(private,1024,0)==GREETING
        # With the shim removed, a retry would really close the newly opened same inode.
        with pytest.raises(OSError) as third:c.stream.close()
        assert third.value is failure and os.pread(private,1024,0)==GREETING
        rejected_again(c)
        assert c.path.read_bytes()==GREETING and os.pread(c.fd,1024,0)==GREETING
        assert c.client.fileno()>=0
    finally:
        # These are newly opened test-owned FDs; the adapter has permanently retired its number.
        for fd in replacement:original(fd)


def test_explicit_close_only_releases_private_duplicate_and_is_idempotent(channel):
    c=channel;greet(c)
    private=c.stream._rx_fd
    c.stream.close();c.stream.close()
    with pytest.raises(OSError):os.fstat(private)
    assert os.pread(c.fd,1024,0)==GREETING
    assert c.client.fileno()>=0 and c.stream._rx_fd is None
    with pytest.raises(RuntimeError,match='closed'):
        c.api.qmp_transaction(c.owner,c.stream,'query-status')
    assert c.path.read_bytes()==GREETING
