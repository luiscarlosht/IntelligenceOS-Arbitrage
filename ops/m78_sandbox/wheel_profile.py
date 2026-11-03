"""Strict offline wheel extraction; trust pins are reviewed independently of staging."""
import base64
import csv
from email.parser import BytesParser
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import stat
import zipfile

PROFILE = 'm78-wheels-no-bytecode-v1'
# PyPI release file SHA-256 metadata; see M78_DEPENDENCY_TRUST.md for origins
# and the required independent review. These are not publisher attestations.
WHEELS = {
    'openpyxl-3.1.5-py2.py3-none-any.whl':
        '5282c12b107bffeef825f4617dc029afaf41d0ea60823bbb665ef3079dc79de2',
    'et_xmlfile-2.0.0-py3-none-any.whl':
        '7a91720bc756843502c3b7504c77b8fe44217c85c537d85037f0f536151b2caa',
}
PACKAGES = {'openpyxl': '3.1.5', 'et_xmlfile': '2.0.0'}
MAX_BYTES = 16 * 1024 * 1024


def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key')
        result[key] = value
    return result


def safe_name(name: str) -> None:
    path = PurePosixPath(name)
    if (not path.parts or path.is_absolute() or str(path) != name
            or '..' in path.parts or '\\' in name or ':' in name
            or any(ord(c) < 32 or ord(c) > 126 for c in name)):
        raise ValueError('unsafe archive/manifest path')
    if '__pycache__' in path.parts or path.suffix.lower() in ('.pyc', '.pyo', '.pth', '.so', '.dll', '.pyd'):
        raise ValueError('bytecode or executable installation hook rejected')


def dependency_name(name: str) -> None:
    safe_name(name)
    root = PurePosixPath(name).parts[0]
    if root not in {*PACKAGES, *(f'{p}-{v}.dist-info' for p, v in PACKAGES.items())}:
        raise ValueError('unexpected dependency package/version')


def validate_files(files: dict) -> None:
    if not isinstance(files, dict):
        raise ValueError('manifest files must be a mapping')
    code = []
    deps = []
    for name, sha in files.items():
        safe_name(name)
        if not isinstance(sha, str) or not re.fullmatch('[0-9a-f]{64}', sha):
            raise ValueError('invalid manifest SHA-256')
        if name.startswith('dependencies/'):
            dependency_name(name.removeprefix('dependencies/'))
            deps.append(name)
        elif name.startswith('app/') and name.endswith('.py') or name == 'ops/m78_offline.py':
            code.append(name)
        else:
            raise ValueError('unexpected source path/type')
    if len(code) != 127 or 'ops/m78_offline.py' not in code or not deps:
        raise ValueError('126 app sources, one ops source and wheel dependencies required')
    for package, version in PACKAGES.items():
        for name in (f'{package}/__init__.py', *(f'{package}-{version}.dist-info/{n}'
                     for n in ('METADATA', 'WHEEL', 'RECORD'))):
            if 'dependencies/' + name not in files:
                raise ValueError('incomplete pinned dependency package')


def decode_manifest(raw: bytes) -> dict:
    data = json.loads(raw, object_pairs_hook=unique)
    if (not isinstance(data, dict) or set(data) != {'profile', 'source_commit', 'wheels', 'files'}
            or data['profile'] != PROFILE or data['wheels'] != WHEELS
            or not isinstance(data['source_commit'], str)
            or not re.fullmatch('[0-9a-f]{40}', data['source_commit'])):
        raise ValueError('explicit pinned bytecode-free manifest required; no legacy fallback')
    validate_files(data['files'])
    return data


def wheel_files(raw: bytes, package: str, version: str) -> dict[str, bytes]:
    """Only two purelib wheels are supported. Never execute archive contents."""
    dist = f'{package}-{version}.dist-info'
    files = {}
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries = archive.infolist()
        if len(entries) > 1024 or sum(i.file_size for i in entries) > MAX_BYTES:
            raise ValueError('wheel exceeds extraction limits')
        for info in entries:
            name = info.filename
            safe_name(name)
            mode = info.external_attr >> 16
            if (info.is_dir() or info.flag_bits & 1 or mode & 0o7000
                    or stat.S_IFMT(mode) not in (0, stat.S_IFREG)
                    or name in files or name.split('/')[0] not in (package, dist)):
                raise ValueError('unsafe/duplicate wheel member')
            files[name] = archive.read(info)
    metadata = BytesParser().parsebytes(files.get(dist + '/METADATA', b''))
    wheel = BytesParser().parsebytes(files.get(dist + '/WHEEL', b''))
    normalized = metadata.get('Name', '').lower().replace('-', '_')
    if (normalized != package or metadata.get('Version') != version
            or wheel.get('Wheel-Version') != '1.0' or wheel.get('Root-Is-Purelib') != 'true'
            or not wheel.get_all('Tag') or any(not t.endswith('-none-any') for t in wheel.get_all('Tag'))):
        raise ValueError('pinned purelib wheel metadata required')
    requires = metadata.get_all('Requires-Dist', [])
    if requires != (['et-xmlfile'] if package == 'openpyxl' else []):
        raise ValueError('unexpected runtime dependency requirements')
    record = dist + '/RECORD'
    seen = set()
    for row in csv.reader(io.StringIO(files.get(record, b'').decode('utf-8'), newline='')):
        if len(row) != 3 or row[0] in seen or row[0] not in files:
            raise ValueError('invalid/duplicate wheel RECORD')
        name, sha, size = row
        seen.add(name)
        if name == record:
            if sha or size:
                raise ValueError('RECORD self entry must be unhashed')
        else:
            wanted = 'sha256=' + base64.urlsafe_b64encode(hashlib.sha256(files[name]).digest()).decode().rstrip('=')
            if sha != wanted or size != str(len(files[name])):
                raise ValueError('wheel RECORD integrity mismatch')
    if seen != set(files) or package + '/__init__.py' not in files:
        raise ValueError('incomplete wheel RECORD/package')
    return files


def authenticated_files(wheelhouse: Path) -> dict[str, bytes]:
    if wheelhouse.is_symlink() or not wheelhouse.is_dir() or {p.name for p in wheelhouse.iterdir()} != set(WHEELS):
        raise ValueError('wheelhouse must contain exactly the two approved wheels')
    result = {}
    for filename, sha in sorted(WHEELS.items()):
        path = wheelhouse / filename
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > MAX_BYTES:
            raise ValueError('regular bounded single-link wheel required')
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != sha:
            raise ValueError('independent wheel SHA-256 mismatch')
        package = filename.split('-')[0]
        for name, contents in wheel_files(raw, package, PACKAGES[package]).items():
            if name in result:
                raise ValueError('colliding wheel paths')
            result[name] = contents
    return dict(sorted(result.items()))
