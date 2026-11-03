"""No real sockets, interfaces, credentials or host sandbox paths are used."""
import json
from pathlib import Path
import os
import runpy
import socket
import sys
import pytest


@pytest.mark.parametrize('failure', ['namespace', 'interface', 'route', 'uid', 'gid', 'user_namespace'])
def test_no_connection_attempt_before_separation(monkeypatch, capsys, failure):
    monkeypatch.setattr(sys, 'argv', ['probe.py', 'net:[host]', '1234', '1234', 'user:[host]'])
    monkeypatch.setattr(os, 'getgid', lambda: 0 if failure == 'gid' else 1234)
    monkeypatch.setattr(os, 'getuid', lambda: 0 if failure == 'uid' else 1234)
    monkeypatch.setattr(os, 'readlink', lambda p: (
        'user:[host]' if failure == 'user_namespace' else 'user:[private]')
        if p.endswith('/user') else ('net:[host]' if failure == 'namespace' else 'net:[private]'))
    monkeypatch.setattr(socket, 'if_nameindex', lambda: [(1, 'eth0' if failure == 'interface' else 'lo')])
    monkeypatch.setattr(Path, 'read_text', lambda p: ('header\neth0 route' if failure == 'route' else 'header') if str(p).endswith('/route') else '')
    def forbidden(*args, **kwargs):
        raise AssertionError('socket creation attempted before separation checks passed')
    monkeypatch.setattr(socket, 'socket', forbidden)
    with pytest.raises(SystemExit) as error:
        runpy.run_path(str(Path(__file__).parents[1] / 'ops/m78_sandbox/probe.py'), run_name='__main__')
    assert error.value.code == 1
    assert not all(json.loads(capsys.readouterr().out).values())
