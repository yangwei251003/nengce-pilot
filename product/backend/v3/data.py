"""Auditable data adapters. No download, interpolation or model selection at runtime."""
from __future__ import annotations
from pathlib import Path
from functools import lru_cache
import csv, hashlib, io, json, re
from zoneinfo import ZoneInfo
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT/'data'/'v3'
CATALOG = DATA/'catalog'
UPLOADS = DATA/'private-imports'
MAX_BYTES = 20*1024*1024
MAX_ROWS = 100_000
PROTOCOL_ID = 'nengce-v3-data-20261004'

def sha256(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()

@lru_cache(maxsize=80)
def _checked_hash(path, size, modified_ns):
    return sha256(path)

def verified_hash(path):
    p=Path(path);s=p.stat()
    return _checked_hash(str(p),s.st_size,s.st_mtime_ns)

def _json(p): return json.loads(Path(p).read_text(encoding='utf-8-sig'))

def local_index(frame, meta):
    idx=pd.DatetimeIndex(frame.index)
    if meta.get('time_axis')=='UTC':
        return idx.tz_localize('UTC').tz_convert(meta.get('billing_timezone') or 'UTC')
    return idx

def quality_report(frame, meta):
    """Complete months require every expected interval and a valid published target.

    original_observation_verified prevents cleaned/unknown points qualifying as
    measured demand even where the published series is complete.
    """
    step=int(meta['interval_minutes']);idx=local_index(frame,meta)
    numeric=frame[['load_kw','pv_kw']].apply(pd.to_numeric,errors='coerce')
    valid=np.isfinite(numeric).all(axis=1)&(numeric>=0).all(axis=1)
    observed=frame.get('observed',valid).fillna(False).astype(bool)&valid
    periods=idx.tz_localize(None).to_period('M') if idx.tz is not None else idx.to_period('M')
    months=[]
    if len(idx):
        for period in pd.period_range(periods.min(),periods.max(),freq='M'):
            start=period.start_time;end=(period+1).start_time
            if idx.tz is not None:start=start.tz_localize(idx.tz);end=end.tz_localize(idx.tz)
            expected=pd.date_range(start,end,freq=f'{step}min',inclusive='left')
            mask=np.asarray(periods==period);part=idx[mask]
            exact=len(part)==len(expected) and part.equals(expected)
            nobs=int(observed.to_numpy()[mask].sum())
            complete=bool(exact and nobs==len(expected))
            months.append({'month':str(period),'expected':len(expected),'rows':len(part),
                'observed':nobs,'complete':complete,'demand_eligible':bool(complete and step==15 and meta.get('original_observation_verified',True) and meta.get('scope',{}).get('dispatch',False))})
    return {'passed':bool(valid.all() and idx.is_unique),'missing':int((~valid).sum()),
        'duplicates':int(idx.duplicated().sum()),'negative':int((numeric<0).any(axis=1).sum()),
        'unobserved':int((~observed).sum()),'raw_interval_minutes':step,
        'complete_months':[x['month'] for x in months if x['complete']],
        'demand_complete_months':[x['month'] for x in months if x['demand_eligible']],
        'monthly_coverage':months,'coverage_calendar':'source-local',
        'original_observation_verified':meta.get('original_observation_verified',True)}

def save_dataset(frame, meta, directory=None):
    """Used by pinned acquisition and authorized imports; preserves missing targets."""
    dest=Path(directory or CATALOG)/meta['dataset_id'];dest.mkdir(parents=True,exist_ok=True)
    frame=frame.copy();frame.index.name='timestamp'
    meta=dict(meta)
    meta['unit']='kW';meta['rows']=len(frame)
    meta['rows_hourly']=len(frame) if meta['interval_minutes']==60 else None
    idx=local_index(frame,meta)
    meta['start']=str(idx[0]);meta['end']=str(idx[-1])
    meta.setdefault('source_id',meta['dataset_id'])
    meta.setdefault('public_data',True);meta['privacy']='public' if meta['public_data'] else 'private'
    meta.setdefault('billing_identity','illustrative')
    meta.setdefault('actual_tariff_applicability','unverified')
    meta.setdefault('pv_available',False)
    meta.setdefault('original_observation_verified',True)
    meta['quality']=quality_report(frame,meta)
    meta['demand_eligible']=bool(meta['quality']['demand_complete_months'])
    meta['demand_status']='illustrative_complete_15min_month' if meta['demand_eligible'] else ('ineligible_hourly' if meta['interval_minutes']!=15 else 'ineligible_observation_or_boundary')
    meta.setdefault('provenance',{})['protocol_id']=PROTOCOL_ID
    meta['provenance']['row_mapping']='source_row is original CSV record number including header (first data record=2); source_timestamp retains original label; quoted multiline records count as one record'
    frame.to_csv(dest/'series.csv',encoding='utf-8',lineterminator='\n')
    meta['provenance']['normalized_sha256']=sha256(dest/'series.csv')
    (dest/'metadata.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    return meta

def list_datasets():
    out=[]
    for root in (CATALOG,UPLOADS):
        if root.exists():
            for p in sorted(root.glob('*/metadata.json')):
                try:
                    meta = _json(p)
                    missing = [raw['path'] for raw in meta.get('provenance', {}).get('raw_files', [])
                               if not (ROOT/Path(raw['path'].replace('\\','/'))).is_file()]
                    meta['runtime_ready'] = not missing
                    meta['runtime_missing'] = missing
                    out.append(meta)
                except (OSError,ValueError):continue
    priority={'uci-steel-15min':0,'rsf-hourly':1,'uci-steel-hourly':2}
    return sorted(out,key=lambda m:(priority.get(m['dataset_id'],3),m['dataset_id']))

datasets=list_datasets

def load_dataset(dataset_id):
    if not isinstance(dataset_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,120}',dataset_id):
        raise ValueError('未知数据集')
    dest=(UPLOADS if dataset_id.startswith('csv-') else CATALOG)/dataset_id
    if not (dest/'metadata.json').is_file():raise ValueError('未知数据集')
    meta=_json(dest/'metadata.json')
    if verified_hash(dest/'series.csv')!=meta['provenance']['normalized_sha256']:
        raise ValueError('规范化数据SHA256与审计记录不符，拒绝计算')
    for raw in meta['provenance'].get('raw_files',[]):
        p=ROOT/Path(raw['path'].replace('\\','/'))
        if not p.is_file() or verified_hash(p)!=raw['sha256']:
            raise ValueError('原始数据SHA256与审计记录不符，拒绝计算')
    frame=pd.read_csv(dest/'series.csv',parse_dates=['timestamp']).set_index('timestamp')
    if 'observed' in frame:frame['observed']=frame['observed'].fillna(False).astype(bool)
    return frame,meta

def import_csv(csv_text, name, timezone, unit, authorized, interval_minutes=60, pv_column=None):
    errors=[];count=0
    def error(row,field,value,reason):
        nonlocal count
        count+=1
        if len(errors)<100:errors.append({'row':int(row),'field':field,'value':str(value)[:160],'reason':reason})
    def invalid():return {'valid':False,'errors':errors,'error_count':count,'errors_truncated':count>len(errors)}
    if not authorized:error(0,'authorized',False,'请确认拥有上传和使用数据的授权');return invalid()
    if not isinstance(csv_text,str):error(0,'csv','','必须提供UTF-8 CSV文本');return invalid()
    try:raw_bytes=csv_text.encode('utf-8')
    except UnicodeError:error(0,'csv','','CSV含无效Unicode字符');return invalid()
    if len(raw_bytes)>MAX_BYTES:error(0,'size',len(raw_bytes),'CSV实际UTF-8字节不可超过20 MiB');return invalid()
    if isinstance(interval_minutes,bool) or interval_minutes not in (15,60):error(0,'interval_minutes',interval_minutes,'仅支持原生15或60分钟数据');return invalid()
    if unit not in ('kW','kWh'):error(0,'unit',unit,'只接受kW或每个申报间隔的kWh');return invalid()
    timezone=str(timezone or '').strip()
    unknown=timezone in ('source-local-unknown','source-local','unknown')
    if not timezone:error(0,'timezone','','需明确IANA时区（如Asia/Shanghai）或source-local-unknown');return invalid()
    if not unknown:
        try:ZoneInfo(timezone)
        except Exception:error(0,'timezone',timezone,'不识别的IANA时区');return invalid()
    try:
        headers=next(csv.reader(io.StringIO(csv_text.lstrip('\ufeff'))))
        if len(headers)!=len(set(headers)):error(1,'header',headers,'CSV含重复列名');return invalid()
        original=pd.read_csv(io.StringIO(csv_text),nrows=MAX_ROWS+1)
    except Exception:error(0,'csv','','CSV格式不可解析');return invalid()
    if len(original)>MAX_ROWS:error(0,'length',len(original),'CSV不可超过100000行');return invalid()
    col='load_kw' if unit=='kW' else 'load_kwh'
    if any(c not in original for c in ('timestamp',col)):
        error(1,'header',headers,f'需要timestamp,{col}；时间为区间开始');return invalid()
    if pv_column is None:
        auto='pv_kw' if unit=='kW' else 'pv_kwh'
        pv_column=auto if auto in original else None
    if pv_column is not None and (not isinstance(pv_column,str) or pv_column not in original or pv_column in ('timestamp',col)):
        error(1,'pv_column',pv_column,'光伏列需为独立存在的同单位数值列');return invalid()
    stamps=original['timestamp'].astype(str)
    hasoffset=stamps.str.contains(r'(?:[zZ]|[+-]\d\d:?\d\d)$',regex=True)
    try:
        if hasoffset.any():
            if not hasoffset.all() or unknown:raise ValueError('offset requires known timezone')
            dt=pd.to_datetime(stamps,utc=True,errors='coerce',format='mixed')
            dates=pd.DatetimeIndex(dt).tz_convert(timezone)
            # A declared region may not silently contradict each input offset.
            for i,s in enumerate(stamps):
                if not pd.isna(dt.iloc[i]) and pd.Timestamp(s).utcoffset()!=dates[i].utcoffset():
                    error(i+2,'timestamp',s,'时间偏移与声明IANA时区不一致')
        else:
            dt=pd.to_datetime(stamps,errors='coerce',format='mixed')
            dates=pd.DatetimeIndex(dt)
            if dates.tz is not None:raise ValueError('unexpected timezone')
            if not unknown:dates=dates.tz_localize(timezone,ambiguous='raise',nonexistent='raise')
    except Exception:
        error(0,'timestamp','','混合偏移、夏令时歧义或无效时间；DST请提供逐行明确偏移');return invalid()
    invalid_dates=np.flatnonzero(dates.isna())
    for i in invalid_dates[:100]:error(i+2,'timestamp',stamps.iloc[i],'无法解析时间')
    if len(invalid_dates)>100:count+=len(invalid_dates)-100
    load=pd.to_numeric(original[col],errors='coerce')
    pv=pd.to_numeric(original[pv_column],errors='coerce') if pv_column else pd.Series(0.,index=original.index)
    for field,values in ((col,load),(pv_column or 'pv_kw',pv)):
        bad=np.flatnonzero((~np.isfinite(values)|(values<0)).to_numpy())
        for i in bad[:100]:error(i+2,field,original[field].iloc[i] if field in original else '', '须为有限非负数')
        if len(bad)>100:count+=len(bad)-100
    min_rows=90*24*60//interval_minutes
    if len(original)<min_rows:error(0,'length',len(original),'至少提供90天连续数据用于训练、校准与回放')
    if count:return invalid()
    axis=dates.tz_convert('UTC').tz_localize(None) if dates.tz is not None else dates
    grid=(dates.minute%interval_minutes==0)&(dates.second==0)&(dates.microsecond==0)&(dates.nanosecond==0)
    bad=np.flatnonzero(~grid)
    for i in bad[:100]:error(i+2,'timestamp',stamps.iloc[i],'时间必须为完整申报间隔开始')
    if len(bad)>100:count+=len(bad)-100
    gaps=np.flatnonzero(np.diff(axis.asi8)!=pd.Timedelta(minutes=interval_minutes).value)+1
    for i in gaps[:100]:error(i+2,'timestamp',stamps.iloc[i],'按原顺序须连续，不接受重复、乱序或缺口')
    if len(gaps)>100:count+=len(gaps)-100
    if dates[0].hour!=0 or dates[0].minute!=0 or (dates[-1]+pd.Timedelta(minutes=interval_minutes)).hour!=0 or (dates[-1]+pd.Timedelta(minutes=interval_minutes)).minute!=0:
        error(0,'timestamp','','需要完整源时区日：从00:00开始并在最后一个间隔结束至次日00:00')
    if count:return invalid()
    name=str(name or '用户授权CSV')[:120]
    signature=json.dumps([unit,timezone,name,interval_minutes,pv_column],ensure_ascii=False).encode('utf-8')
    ident='csv-'+hashlib.sha256(raw_bytes+b'\0'+signature).hexdigest()[:20]
    dest=UPLOADS/ident
    if (dest/'metadata.json').exists():
        _,meta=load_dataset(ident)
        return {'valid':True,'errors':[],'error_count':0,'dataset':meta,'reused':True}
    factor=60/interval_minutes if unit=='kWh' else 1
    frame=pd.DataFrame({'load_kw':load.to_numpy()*factor,'pv_kw':pv.to_numpy()*factor,'observed':True,
        'source_row':np.arange(len(load))+2,'source_timestamp':stamps.to_numpy()},index=axis)
    dest.mkdir(parents=True,exist_ok=True);(dest/'raw.csv').write_bytes(raw_bytes)
    localstart=dates[0].tz_localize(None) if dates.tz is not None else dates[0]
    localend=dates[-1].tz_localize(None) if dates.tz is not None else dates[-1]
    teststart=max(localend.normalize()-pd.Timedelta(days=29),localstart.normalize()+pd.Timedelta(days=75))
    valstart=teststart-pd.Timedelta(days=21)
    meta={'dataset_id':ident,'name':name,'source_type':'user_authorized_observed','public_data':False,
        'source_id':ident,'timezone':timezone,'billing_timezone':None if unknown else timezone,
        'time_axis':'source-local' if unknown else 'UTC','interval_minutes':interval_minutes,'pv_available':bool(pv_column),
        'scope':{'dispatch':True,'energy_billing':True,'demand_15min':interval_minutes==15,'photovoltaic':bool(pv_column),'reason':'用户申报的负荷/PV表计边界，未独立核验；仅示例合同计价'},
        'provenance':{'source':'User authorized CSV','license':'User attested; not independently verified',
            'raw_files':[{'path':str((dest/'raw.csv').relative_to(ROOT)),'sha256':sha256(dest/'raw.csv')}],
            'raw_sha256':sha256(dest/'raw.csv'),'transformation':f'{unit} converted to average kW using {interval_minutes} minute interval; no sorting/imputation',
            'warning':'私人数据默认不可外发；授权声明不代表平台核实产权或现场计量边界'},
        'default_evaluation':{'train_start':str(localstart.date()),'train_end':str((valstart-pd.Timedelta(days=1)).date()),
            'validation_start':str(valstart.date()),'validation_end':str((teststart-pd.Timedelta(days=1)).date()),
            'test_start':str(teststart.date()),'test_end':str(localend.date()),'role':'user_exploratory','protocol_id':PROTOCOL_ID}}
    meta=save_dataset(frame,meta,UPLOADS)
    return {'valid':True,'errors':[],'error_count':0,'dataset':meta,'reused':False}
