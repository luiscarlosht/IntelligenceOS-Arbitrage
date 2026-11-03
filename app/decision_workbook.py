"""Deterministic formula-safe decision workbook; formulas are audit aids, not gate inputs."""
from datetime import datetime
from io import BytesIO
import zipfile
from decimal import Decimal
from openpyxl import Workbook
from app.m79 import MemoryExcelWriter
from app.m78_reporting import cell,write
from app.opportunity_engine import COSTS

FIELDS=('asin','evidence_class','status','purchase_price','sale_price',*COSTS,'acquisition_cost','net_profit','roi_percent','markup_percent','margin_percent','flags','purchase_authorized')


def workbook(report:dict,path):
    wb=Workbook();wb.remove(wb.active);wb.properties.created=wb.properties.modified=datetime(2000,1,1)
    tables={'Executive':[dict(metric=k,value=v) for k,v in report['executive'].items()],
        'Research_Top20':report['research_top20'],'Demand_Competition':report['amazon']['rows'],
        'Comparable_Categories':report['amazon']['category_groups'],'Profitability':report['opportunities'],
        'Historical_Unobserved':report.get('historical_unobserved',[]),'Data_Quality':report['data_quality'],'Observation_History':report['history'],'Weekly':report['weekly'],
        'Inventory_Proposals':report['inventory_proposals'],
        'Provenance':[dict(path=k,sha256=v) for k,v in report['input_sha256'].items()],
        'Method':[dict(topic=k,detail=v) for k,v in report['method'].items()]}
    for name,rows in tables.items():
        sheet=wb.create_sheet(name);fields=list(FIELDS) if name=='Profitability' else sorted({k for r in rows for k in r}) or ['status']
        sheet.append(fields)
        if not rows:sheet.append(['UNKNOWN: no supported observations or candidates'])
        for i,row in enumerate(rows,2):
            values=[cell(row.get(key,'UNKNOWN')) for key in fields]
            if name=='Profitability' and row['net_profit']!='UNKNOWN':
                # Numeric inputs were validated with Decimal. Excel precision never decides eligibility.
                for key in ('purchase_price','sale_price',*COSTS):values[fields.index(key)]=float(Decimal(str(row[key] if key in row else row['costs'][key])))
                from openpyxl.utils import get_column_letter as letter
                col=lambda key:f'{letter(fields.index(key)+1)}{i}'
                acq='+'.join(col(k) for k in ('purchase_price',*COSTS[:6]))
                values[fields.index('acquisition_cost')]='='+acq
                values[fields.index('net_profit')]='='+col('sale_price')+'-'+col('acquisition_cost')+'-'+'-'.join(col(k) for k in COSTS[6:])
                for key,denom in (('roi_percent','acquisition_cost'),('markup_percent','acquisition_cost'),('margin_percent','sale_price')):
                    values[fields.index(key)]='='+col('net_profit')+'/'+col(denom)+'*100'
            sheet.append(values)
        sheet.freeze_panes='B2';sheet.auto_filter.ref=sheet.dimensions
    raw=BytesIO();MemoryExcelWriter(wb,zipfile.ZipFile(raw,'w',zipfile.ZIP_DEFLATED)).save()
    result=BytesIO()
    with zipfile.ZipFile(raw) as src,zipfile.ZipFile(result,'w',zipfile.ZIP_DEFLATED) as dst:
        for name in sorted(src.namelist()):
            info=zipfile.ZipInfo(name,(2000,1,1,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED;info.external_attr=0o600<<16;info.create_system=3
            dst.writestr(info,src.read(name))
    write(path,result.getvalue())
