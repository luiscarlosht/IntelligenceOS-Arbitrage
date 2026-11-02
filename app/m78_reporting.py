"""Deterministic private report serialization. No historical executor imports."""
import csv
from datetime import datetime
from io import BytesIO, StringIO
import json
import os
from pathlib import Path
import sqlite3
import zipfile

from openpyxl import Workbook


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True)


def cell(value):
    if isinstance(value, (dict, list)):
        value = encoded(value)
    if isinstance(value, str):
        if len(value) > 32767:
            raise ValueError('Excel cell exceeds evidence bound')
        if value.lstrip().startswith(('=', '+', '-', '@')):
            value = "'" + value
    return value


def write(path: Path, data: bytes):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def serialize(report: dict, stage: Path):
    write(stage/'M78_report.json', encoded(report).encode())
    tables = dict(catalog=report['catalog'], annotations=report['annotations'],
                  summary=[dict(metric=k, value=v) for k, v in sorted(report['summary'].items())])
    tables['identity_quality'] = [dict(asin=p['asin'], classification=p['classification'],
        missing_fields=p['missing_fields'], identity_conflicts=p['identity_conflicts'],
        field_provenance=p['field_provenance'], review_blocks=p['review_blocks']) for p in report['catalog']]
    tables['conflicts'] = [dict(asin=p['asin'], field=f,
        observed_values=p.get('observed_alternatives', {}).get(f),
        field_provenance=p['field_provenance'].get(f), resolution='UNRESOLVED')
        for p in report['catalog'] for f in p['identity_conflicts']]
    wb = Workbook()
    wb.remove(wb.active)
    wb.properties.created = wb.properties.modified = datetime(2000, 1, 1)
    dbpath = stage/'M78_catalog.sqlite3'
    write(dbpath, b'')
    with sqlite3.connect(dbpath) as db:
        db.execute('PRAGMA journal_mode=MEMORY')
        for name, rows in tables.items():
            fields = sorted({k for row in rows for k in row}) or ['asin']
            sheet = wb.create_sheet(name)
            sheet.append(fields)
            buf = StringIO(newline='')
            writer = csv.writer(buf)
            writer.writerow(fields)
            db.execute(f'CREATE TABLE {name} (ordinal INTEGER PRIMARY KEY, payload TEXT NOT NULL)')
            for ordinal, row in enumerate(rows):
                values = [cell(row.get(f)) for f in fields]
                writer.writerow(values)
                sheet.append(values)
                db.execute(f'INSERT INTO {name} VALUES (?, ?)', (ordinal, encoded(row)))
            write(stage/f'M78_{name}.csv', buf.getvalue().encode('utf-8-sig'))
    raw = BytesIO()
    from openpyxl.writer.excel import ExcelWriter
    ExcelWriter(wb, zipfile.ZipFile(raw, "w", zipfile.ZIP_DEFLATED)).save()
    result = BytesIO()
    with zipfile.ZipFile(raw) as src, zipfile.ZipFile(result, 'w', compression=zipfile.ZIP_DEFLATED) as dst:
        for name in sorted(src.namelist()):
            info = zipfile.ZipInfo(name, (2000, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o600 << 16
            dst.writestr(info, src.read(name))
    write(stage/'M78_review.xlsx', result.getvalue())
