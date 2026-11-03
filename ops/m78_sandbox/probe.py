"""Synthetic security checks only. Any assertion failure means NOT READY."""
import json
import os
from pathlib import Path
import socket
import sys
import uuid

results = {}


def check(name, condition):
    results[name] = bool(condition)


check('nonroot_uid', os.getuid() == int(sys.argv[2]) != 0)
check('distinct_network_namespace', os.readlink('/proc/self/ns/net') != sys.argv[1])
check('loopback_only', {name for _, name in socket.if_nameindex()} <= {'lo'})
routes = Path('/proc/net/route').read_text().splitlines()[1:]
check('no_ipv4_routes', not routes)
# Every non-loopback IPv6 route must be absent, including default routes.
routes6 = Path('/proc/net/ipv6_route').read_text().splitlines()
check('no_external_ipv6_routes', all(row.split()[-1] == 'lo' for row in routes6))
# Never attempt even a diagnostic connection until separation is established.
if not all(results.values()):
    print(json.dumps(results, sort_keys=True, indent=2), flush=True)
    raise SystemExit(1)
for family, address in [(socket.AF_INET, ('1.1.1.1', 443)),
                        (socket.AF_INET6, ('2606:4700:4700::1111', 443))]:
    with socket.socket(family, socket.SOCK_STREAM) as sock:
        sock.settimeout(1)
        try:
            sock.connect(address)
            denied = False
        except OSError:
            denied = True
        check(f'connect_denied_{family}', denied)
for folder in ('/app', '/deps', '/evidence', '/usr', '/tmp', '/'):
    path = Path(folder) / ('m78-denial-' + uuid.uuid4().hex)
    try:
        path.write_text('synthetic')
        path.unlink()
        denied = False
    except OSError:
        denied = True
    check('write_denied_' + folder, denied)
for path in ('/root', '/home', '/mnt', '/opt', '/etc/shadow', '/run', '/var'):
    item = Path(path)
    check('host_hidden_' + path, not item.exists() or
          (item.is_dir() and not any(item.iterdir())))
for folder in ('/app', '/deps', '/evidence'):
    list(Path(folder).iterdir())
    check('readable_' + folder, os.access(folder, os.R_OK | os.X_OK))
for file in ('/app/app/m78.py', '/app/ops/m78_offline.py'):
    with open(file, 'rb') as stream:
        check('code_read_' + file, bool(stream.read(1)))
check('evidence_empty', not any(Path('/evidence').iterdir()))
import openpyxl
import et_xmlfile
check('pinned_openpyxl', openpyxl.__version__ == '3.1.5')
check('pinned_et_xmlfile', et_xmlfile.__version__ == '2.0.0')
path = Path('/output') / ('probe-' + uuid.uuid4().hex)
path.write_text('synthetic security probe')
check('output_read_write', path.read_text() == 'synthetic security probe')
path.unlink()
status = Path('/proc/self/status').read_text()
check('no_capabilities', 'CapEff:\t0000000000000000' in status)
check('no_new_privileges', 'NoNewPrivs:\t1' in status)
print(json.dumps(results, sort_keys=True, indent=2), flush=True)
raise SystemExit(0 if all(results.values()) else 1)
