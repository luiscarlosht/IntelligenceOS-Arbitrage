"""M84 release preparation only: never installs, changes ACLs, starts services or calls APIs."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
from ops.m78_sandbox.wheel_profile import authenticated_files,WHEELS,safe_name
from app.evidence_io import publication,json_write,safe,digest
from app.m78_reporting import write,encoded

PROFILE='sales-intelligence-offline-v1'
DESTINATION=Path('/mnt/intelligenceos_data/arbitrage/intelligence-isolated')
STATE_ROOT=Path('/var/lib/intelligenceos-sales')
ENTRY='''# Reviewed offline entrypoint. Python -I -S -B required.
import hashlib,json,os,sys
from pathlib import Path
if not (sys.flags.isolated and sys.flags.no_site and sys.dont_write_bytecode):
    raise SystemExit('Use python3 -I -S -B run.py')
root=Path(__file__).resolve().parent
expected=os.environ.get('INTELLIGENCE_RELEASE_SHA256','')
raw=(root/'manifest.json').read_bytes()
if len(expected)!=64 or hashlib.sha256(raw).hexdigest()!=expected:
    raise SystemExit('Owner-reviewed manifest SHA-256 required')
manifest=json.loads(raw)
objects=list(root.rglob('*'))
if any(p.is_symlink() or not (p.is_file() or p.is_dir()) for p in objects):
    raise SystemExit('Only regular nonsymlink release objects permitted')
actual={str(p.relative_to(root)) for p in objects if p.is_file()}
if actual!=set(manifest['files'])|{'manifest.json'}:
    raise SystemExit('Unexpected or missing release files')
for name,sha in manifest['files'].items():
    p=root/name
    if p.is_symlink() or any(x.is_symlink() for x in p.parents) or p.stat().st_nlink!=1 or hashlib.sha256(p.read_bytes()).hexdigest()!=sha:
        raise SystemExit('Release file drift')
sys.path.insert(0,str(root/'runtime'))
from app.decision_pipeline import main
raise SystemExit(main())
'''


def git(repo:Path,*args) -> bytes:
    return subprocess.run(['git','-C',str(repo),*args],check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env={'PATH':os.defpath,'GIT_CONFIG_NOSYSTEM':'1'}).stdout


def source(repo:Path,commit:str) -> dict[str,bytes]:
    if not re.fullmatch('[0-9a-f]{40}',commit):raise ValueError('Reviewed full Git source commit required')
    files={}
    for entry in git(repo,'ls-tree','-rz',commit,'--','app').split(b'\0'):
        if not entry:continue
        metadata,name=entry.split(b'\t');mode,kind,oid=metadata.decode().split();name=name.decode()
        if not name.endswith('.py'):continue
        safe_name(name)
        if mode!='100644' or kind!='blob':raise ValueError('Only ordinary Git Python sources permitted')
        files['runtime/'+name]=git(repo,'cat-file','blob',oid)
    if 'runtime/app/decision_pipeline.py' not in files:raise ValueError('Integrated decision pipeline missing from reviewed source')
    return files


def build(repo:Path,commit:str,wheelhouse:Path,output:Path):
    repo=safe(repo);wheelhouse=safe(wheelhouse)
    sources=source(repo,commit)
    dependencies={'runtime/'+k.removeprefix('dependencies/'):v for k,v in authenticated_files(wheelhouse).items()}
    if sources.keys()&dependencies.keys():raise ValueError('Source/dependency collision')
    files=dict(sources,**dependencies);files['run.py']=ENTRY.encode()
    manifest=dict(schema=1,profile=PROFILE,source_commit=commit,wheels=WHEELS,
        files={name:hashlib.sha256(raw).hexdigest() for name,raw in sorted(files.items())},
        source_files={name.removeprefix('runtime/'):hashlib.sha256(raw).hexdigest() for name,raw in sorted(sources.items())},
        entry_sha256=hashlib.sha256(ENTRY.encode()).hexdigest(),bytecode=False,live_acquisition_enabled=False)
    with publication(output,[repo,wheelhouse]) as stage:
        for name,raw in sorted(files.items()):
            safe_name(name);path=stage/name;path.parent.mkdir(parents=True,exist_ok=True,mode=0o700);write(path,raw)
        json_write(stage/'manifest.json',manifest)
    return dict(manifest_sha256=digest(output/'manifest.json'),files=len(files),source_commit=commit,profile=PROFILE,
        deployment_authorized=False,readiness='REQUIRES_INDEPENDENT_REPRODUCTION_AND_TARGET_CHECKS')


def inspect_release(root:Path,expected:str,repo:Path,commit:str,wheelhouse:Path):
    # Rebuild expected bytes from independently reviewed Git and authenticated artifacts.
    root=safe(root)
    if digest(root/'manifest.json')!=expected:raise ValueError('Reviewed manifest pin mismatch')
    from app.evidence_io import pinned
    manifest=pinned(root/'manifest.json',expected)
    sources=source(safe(repo),commit)
    dependencies={'runtime/'+k.removeprefix('dependencies/'):v for k,v in authenticated_files(safe(wheelhouse)).items()}
    files=dict(sources,**dependencies);files['run.py']=ENTRY.encode()
    expected_manifest=dict(schema=1,profile=PROFILE,source_commit=commit,wheels=WHEELS,
        files={n:hashlib.sha256(v).hexdigest() for n,v in sorted(files.items())},
        source_files={n.removeprefix('runtime/'):hashlib.sha256(v).hexdigest() for n,v in sorted(sources.items())},
        entry_sha256=hashlib.sha256(ENTRY.encode()).hexdigest(),bytecode=False,live_acquisition_enabled=False)
    if manifest!=expected_manifest:raise ValueError('Source/wheel/entry profile mismatch')
    actual={str(p.relative_to(root)) for p in root.rglob('*') if p.is_file()}
    if actual!=set(files)|{'manifest.json'}:raise ValueError('Extra/missing release files')
    for path in root.rglob('*'):
        safe(path)
        if path.is_file() and path.stat().st_nlink!=1:raise ValueError('Hardlinked release file')
        if not path.is_file() and not path.is_dir():raise ValueError('Special release object')
    if any(digest(root/name)!=hashlib.sha256(raw).hexdigest() for name,raw in files.items()):raise ValueError('Release byte mismatch')
    return dict(integrity='PASS',source_commit=commit,dependency_integrity='PASS',independent_authentication='OWNER_REVIEW_REQUIRED',deployment_authorized=False)


def host_preflight() -> dict:
    """Read only; target must be absent. Never opens account credential files."""
    import pwd,grp
    issues=[];mount=Path('/mnt/intelligenceos_data');parent=DESTINATION.parent
    for path in (Path('/mnt'),mount,parent):
        try:
            info=path.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid!=0 or info.st_mode&0o022:issues.append('UNSAFE_ANCESTOR:'+str(path))
            if {'system.posix_acl_access','system.posix_acl_default'}&set(os.listxattr(path,follow_symlinks=False)):issues.append('ACL:'+str(path))
        except OSError:issues.append('UNREADABLE_ANCESTOR:'+str(path))
    if DESTINATION.exists() or DESTINATION.is_symlink():issues.append('DESTINATION_MUST_BE_ABSENT')
    try:
        mounts=[line.split() for line in Path('/proc/self/mountinfo').read_text().splitlines()]
        selected=[fields for fields in mounts if fields[4]==str(mount)]
        if len(selected)!=1 or 'rw' not in selected[0][5].split(','):issues.append('DEDICATED_RW_MOUNT_REQUIRED')
        if mount.stat().st_dev==mount.parent.stat().st_dev:issues.append('DISTINCT_VOLUME_REQUIRED')
    except OSError:issues.append('MOUNT_UNREADABLE')
    try:
        if pwd.getpwuid(997).pw_gid!=986 or grp.getgrgid(986).gr_gid!=986:issues.append('ACCOUNT_MISMATCH')
    except KeyError:issues.append('ACCOUNT_MISSING')
    for status in Path('/proc').glob('[0-9]*/status'):
        try:
            uid=next(line for line in status.read_text().splitlines() if line.startswith('Uid:')).split()[1:]
            if '997' in uid:issues.append('DEDICATED_ACCOUNT_BUSY');break
        except (OSError,StopIteration):issues.append('PROCESS_AUDIT_INCOMPLETE');break
    return dict(mode='READ_ONLY_PREFLIGHT',destination=str(DESTINATION),issues=issues,
        host_facts='PASS' if not issues else 'FAIL',target_security='NOT_TESTED',
        independent_dependency_authentication='OWNER_REVIEW_REQUIRED',readiness='FAIL',deployment_authorized=False)



def configuration(path:Path,expected:str) -> dict:
    """Validate local proposed configuration; no file creation or execution."""
    from app.evidence_io import pinned
    from datetime import datetime
    data=pinned(path,expected)
    if (set(data)!={'schema','mode','release','release_sha256','manifest','manifest_sha256','history','output','as_of'}
            or type(data['schema']) is not int or data['schema']!=1 or data['mode']!='OFFLINE_REPORT_ONLY'):
        raise ValueError('Exact offline configuration required')
    for key in ('release_sha256','manifest_sha256'):
        if not isinstance(data[key],str) or not re.fullmatch('[a-f0-9]{64}',data[key]):raise ValueError('Reviewed configuration pins required')
    release=safe(Path(data['release']));manifest=safe(Path(data['manifest']));history=safe(Path(data['history']));output=safe(Path(data['output']))
    if release!=DESTINATION/'release':raise ValueError('Fixed isolated release path required')
    # Validate the intended layout without touching /mnt or resolving runtime input contents.
    if not history.is_relative_to(STATE_ROOT/'state') or not output.is_relative_to(STATE_ROOT/'reports') or output==STATE_ROOT/'reports':
        raise ValueError('Dedicated state/report layout required')
    if manifest!=STATE_ROOT/'inputs/manifest.json':raise ValueError('Fixed read-only staged manifest path required')
    if manifest.is_relative_to(STATE_ROOT/'state') or manifest.is_relative_to(STATE_ROOT/'reports') or manifest.is_relative_to(release):
        raise ValueError('Read-only input manifest must be separate')
    if datetime.fromisoformat(data['as_of']).tzinfo is None:raise ValueError('Aware report review time required')
    return dict(configuration='PASS',mode='OFFLINE_REPORT_ONLY',deployment_authorized=False,
        target_security='NOT_TESTED',readiness='FAIL',next_action='Owner review, artifact authentication and separately authorized isolated host validation')


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    for name in ('build','verify'):
        q=sub.add_parser(name);q.add_argument('--repo',type=Path,required=True);q.add_argument('--commit',required=True)
        q.add_argument('--wheelhouse',type=Path,required=True);q.add_argument('--output' if name=='build' else '--release',type=Path,required=True)
        if name=='verify':q.add_argument('--manifest-sha256',required=True)
    q=sub.add_parser('config-check');q.add_argument('--config',type=Path,required=True);q.add_argument('--sha256',required=True)
    sub.add_parser('host-preflight');a=p.parse_args(argv)
    try:
        if a.command=='build':result=build(a.repo,a.commit,a.wheelhouse,a.output)
        elif a.command=='verify':result=inspect_release(a.release,a.manifest_sha256,a.repo,a.commit,a.wheelhouse)
        elif a.command=='config-check':result=configuration(a.config,a.sha256)
        else:result=host_preflight()
        print(json.dumps(result,sort_keys=True));return 0 if a.command!='host-preflight' or not result['issues'] else 1
    except (ValueError,OSError,subprocess.CalledProcessError) as exc:
        print(json.dumps(dict(status='FAIL_CLOSED',error_type=type(exc).__name__)),file=sys.stderr);return 1


if __name__=='__main__':raise SystemExit(main())
