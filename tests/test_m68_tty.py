"""Real Linux character-device tests; synthetic confirmations, no artifacts/APIs."""
import io
import os
import pty
import select
import signal
import subprocess
import sys
import termios
import time

import pytest

from app import m68_authorization as auth
from test_m68 import offline

CHILD = '''
import os,sys,socket,termios

def forbidden(*a,**k):raise AssertionError('Network forbidden')
socket.create_connection=socket.getaddrinfo=socket.socket.connect=forbidden
sys.modules['app.m67_execution']=None
sys.modules['app.m67_transport']=None
from app.m68_authorization import confirm_account
before=termios.tcgetattr(1)
if sys.argv[1]=='pipe':
    read_fd,write_fd=os.pipe()
    os.write(write_fd,b'PIPE_MUST_NOT_BE_READ\\n')
    os.close(write_fd)
    os.dup2(read_fd,0)
    os.close(read_fd)
    assert not os.isatty(0)
result=confirm_account('SYNTHETICSELLER')
assert termios.tcgetattr(1)==before, 'Terminal flags not restored'
print('RESULT_TRUE' if result else 'RESULT_FALSE',flush=True)
'''


def test_linux_character_device_reproduces_buffered_update_failure():
    master,slave=pty.openpty()
    try:
        with pytest.raises(io.UnsupportedOperation):
            with open(os.ttyname(slave),'r+'):
                pass
        fd=os.open(os.ttyname(slave),os.O_RDWR|os.O_NOCTTY|os.O_CLOEXEC)
        with os.fdopen(fd,'r+b',buffering=0) as raw:
            assert raw.isatty() and not raw.seekable()
    finally:os.close(master);os.close(slave)


@pytest.mark.parametrize('stdin_mode',['tty','pipe'])
@pytest.mark.parametrize('seller,phrase,expected',[
    ('SYNTHETICSELLER',auth.CONFIRMATION,True),
    ('WRONG',auth.CONFIRMATION,False),('SYNTHETICSELLER','WRONG',False)])
def test_real_controlling_pty_hidden_confirmations_and_no_stdin_fallback(stdin_mode,seller,phrase,expected):
    pid,master=pty.fork()
    if pid==0:
        os.execv(sys.executable,[sys.executable,'-c',CHILD,stdin_mode])
    output=b'';reaped=False;deadline=time.monotonic()+15
    def until(marker):
        nonlocal output
        while marker not in output:
            remaining=deadline-time.monotonic()
            assert remaining>0,'PTY confirmation timed out'
            ready,_,_=select.select([master],[],[],remaining)
            assert ready,'PTY prompt unavailable'
            block=os.read(master,4096)
            assert block,'PTY unexpectedly closed'
            output+=block
    try:
        until(b'Privately verified seller ID (hidden): ')
        assert not termios.tcgetattr(master)[3]&(termios.ECHO|termios.ECHONL)
        os.write(master,seller.encode()+b'\n')
        until(b'PREPARE ONLY (hidden): ')
        assert not termios.tcgetattr(master)[3]&(termios.ECHO|termios.ECHONL)
        os.write(master,phrase.encode()+b'\n')
        until(b'RESULT_TRUE' if expected else b'RESULT_FALSE')
        _,status=os.waitpid(pid,0);reaped=True
        assert os.waitstatus_to_exitcode(status)==0
        assert b'SYNTHETICSELLER' not in output
        assert b'WRONG' not in output
        # Phrase appears once in the static prompt, never echoed as input.
        assert output.count(auth.CONFIRMATION.encode())==1
        assert b'PIPE_MUST_NOT_BE_READ' not in output
    finally:
        if not reaped:
            try:os.kill(pid,signal.SIGKILL)
            except ProcessLookupError:pass
            os.waitpid(pid,0)
        os.close(master)


@pytest.mark.parametrize('stdin_mode',['pipe','tty'])
def test_no_controlling_tty_rejects_even_tty_stdin(stdin_mode):
    script='''
import os,sys,socket
socket.create_connection=lambda *a,**k: (_ for _ in ()).throw(AssertionError('Network forbidden'))
from app.m68_authorization import confirm_account
assert sys.stdin.isatty()==(sys.argv[1]=='tty')
try:confirm_account('SYNTHETICSELLER')
except OSError:print('NO_CONTROLLING_TTY')
else:raise AssertionError('Unexpected stdin fallback')
'''
    master=slave=None
    try:
        if stdin_mode=='tty':master,slave=pty.openpty()
        result=subprocess.run([sys.executable,'-c',script,stdin_mode],start_new_session=True,
            stdin=slave if stdin_mode=='tty' else subprocess.DEVNULL,
            capture_output=True,text=True,timeout=10)
        assert result.returncode==0 and result.stdout.strip()=='NO_CONTROLLING_TTY'
    finally:
        if master is not None:os.close(master);os.close(slave)


@pytest.mark.parametrize('failure',[EOFError,KeyboardInterrupt,UnicodeError])
def test_echo_restored_on_hidden_input_failure(monkeypatch,failure):
    before=[0,0,0,termios.ECHO|termios.ECHONL,0,0,[]];changes=[]
    monkeypatch.setattr(auth.termios,'tcgetattr',lambda fd:before)
    monkeypatch.setattr(auth.termios,'tcsetattr',lambda fd,when,flags:changes.append(flags[:]))
    class Terminal:
        def fileno(self):return 123
        def write(self,text):assert 'SYNTHETICSELLER' not in text
        def flush(self):pass
        def readline(self):raise failure
    with pytest.raises(failure):auth._hidden_terminal_line(Terminal(),'Private prompt: ')
    assert changes[0][3]&(termios.ECHO|termios.ECHONL)==0
    assert changes[-1]==before


def test_echo_control_failure_never_reads_input(monkeypatch):
    before=[0,0,0,termios.ECHO,0,0,[]];changes=[]
    monkeypatch.setattr(auth.termios,'tcgetattr',lambda fd:before)
    def control(fd,when,flags):
        changes.append(flags[:])
        if len(changes)==1:raise termios.error('Synthetic control failure')
    monkeypatch.setattr(auth.termios,'tcsetattr',control)
    class Terminal:
        def fileno(self):return 123
        def write(self,text):assert text=='\n'
        def flush(self):pass
        def readline(self):pytest.fail('Must not read after echo-control failure')
    with pytest.raises(termios.error):auth._hidden_terminal_line(Terminal(),'Private prompt: ')
    assert changes[-1]==before
