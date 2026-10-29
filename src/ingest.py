"""Preserve selected federal aggregate facts and original worksheet numeric tokens."""
import argparse,csv,gzip,hashlib,io,json,posixpath,zipfile
from collections import Counter
from datetime import datetime,timezone
from decimal import Decimal
from pathlib import Path
import xml.etree.ElementTree as ET

NS={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
REL='http://schemas.openxmlformats.org/officeDocument/2006/relationships'
def workbook_rows(data,sheet_name):
    """Read OOXML values directly so decimal source tokens never round through float."""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        strings=[]
        if 'xl/sharedStrings.xml' in z.namelist():strings=[''.join(e.itertext()) for e in ET.fromstring(z.read('xl/sharedStrings.xml'))]
        workbook=ET.fromstring(z.read('xl/workbook.xml'));relationships={r.get('Id'):r.get('Target') for r in ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))}
        matches=[s for s in workbook.find('s:sheets',NS) if s.get('name')==sheet_name];assert len(matches)==1
        target=relationships[matches[0].get('{'+REL+'}id')]
        member=target.lstrip('/') if target.startswith('/') else posixpath.normpath(posixpath.join('xl',target))
        for event,row in ET.iterparse(io.BytesIO(z.read(member)),events=['end']):
            if row.tag!='{'+NS['s']+'}row':continue
            values={}
            for cell in row:
                ref=cell.get('r');kind=cell.get('t','n');v=cell.find('s:v',NS);token='' if v is None else v.text or ''
                if kind=='s':value=strings[int(token)] if token else ''
                elif kind=='inlineStr':value=''.join(cell.find('s:is',NS).itertext())
                else:value=token
                values[''.join(c for c in ref if c.isalpha())]=(value,kind)
            yield int(row.get('r')),values
            row.clear()

def ingest(raw_dir,root='.'):
    root=Path(root);raw_dir=Path(raw_dir);cfg=json.loads((root/'protocol.json').read_text(encoding='utf-8'))
    archives=json.loads((root/'data/source/archives.json').read_text(encoding='utf-8'));records=[];manifest=[];counts=Counter();keys=set();plant_context={}
    selected=set(cfg['coal_codes']+cfg['natural_gas_codes']+cfg['diagnostic_fuels'])
    fields=['year','plant','chp','state','prime_mover','fuel','nuclear_unit','elec_mmbtu','net_mwh']
    for arc in archives:
        data=(raw_dir/f'f923_{arc["year"]}.zip').read_bytes();assert hashlib.sha256(data).hexdigest()==arc['sha256']
        with zipfile.ZipFile(io.BytesIO(data)) as z:book=z.read(arc['selected_member'])
        columns=None;source_rows=0;selected_rows=0
        for rownum,cells in workbook_rows(book,cfg['source_sheet']):
            if rownum==cfg['source_header_row']:
                columns={name:next(col for col,(value,kind) in cells.items() if value==label) for name,label in cfg['source_fields'].items()};continue
            if rownum<=cfg['source_header_row']:continue
            source_rows+=1
            fuel=cells.get(columns['fuel'],('',''))[0]
            if fuel not in selected:continue
            raw=[cells.get(columns[name],('',''))[0] for name in fields]
            year,plant,chp,state,pm,fuel,nuclear,f,g=raw
            assert Decimal(year)==arc['year'] and Decimal(plant)==int(Decimal(plant)) and Decimal(plant)>0
            assert pm in cfg['allowed_prime_movers'],pm
            plant_id=str(int(Decimal(plant)));key=(int(year),plant_id,pm,fuel);assert key not in keys,key;keys.add(key)
            context=(state,chp)
            assert plant_context.setdefault((int(year),plant_id),context)==context,(year,plant_id)
            digest=hashlib.sha256('\x1f'.join(raw).encode()).hexdigest()
            records.append([arc['year'],rownum,*raw[1:],cells.get(columns['elec_mmbtu'],('',''))[1],cells.get(columns['net_mwh'],('',''))[1],digest])
            selected_rows+=1;counts[(arc['year'],fuel)]+=1
        assert columns is not None
        manifest.append(dict(year=arc['year'],archive_sha256=arc['sha256'],workbook_sha256=hashlib.sha256(book).hexdigest(),source_rows=source_rows,selected_rows=selected_rows,columns=columns))
    buf=io.StringIO(newline='');w=csv.writer(buf,lineterminator='\n');w.writerow(['year','source_row','plant','chp','state','prime_mover','fuel','nuclear_unit','elec_mmbtu_raw','net_mwh_raw','fuel_xml_type','generation_xml_type','selected_fields_sha256']);w.writerows(records)
    packed=gzip.compress(buf.getvalue().encode(),mtime=0);out=root/'data/source';(out/'annual_cells.csv.gz').write_bytes(packed)
    result=dict(timestamp_utc=datetime.now(timezone.utc).isoformat(),status='SOURCE_PROJECTION_CREATED_NOT_YET_INDEPENDENTLY_VERIFIED',years=manifest,selected_rows=len(records),rows_by_year_fuel=[dict(year=y,fuel=f,rows=n) for (y,f),n in sorted(counts.items())],selected_sha256=hashlib.sha256(packed).hexdigest(),units=dict(fuel='MMBtu for electricity',generation='net MWh'),provenance='Exact XML text/numeric tokens; sheet and row locators; SHA256 joins year+eight selected original fields by U+001F. Diagnostic WH rows are not assigned to coal/NG.',excluded='Source workbooks, other sheets, monthly values, monetary values, plant/operator/contact names and coordinates')
    (out/'manifest.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:result[k] for k in ['status','selected_rows','selected_sha256','rows_by_year_fuel']}))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('raw_dir');p.add_argument('--root',default='.');a=p.parse_args();ingest(a.raw_dir,a.root)
