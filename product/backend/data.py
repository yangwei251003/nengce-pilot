from pathlib import Path
import hashlib,json,io
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
REFERENCE=ROOT.parent/'data'/'reference'
UPLOADS=ROOT/'outputs'/'datasets'

def sha256(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def reference_data():
    p=REFERENCE/'Steel_industry_data_normalized_v1.csv'
    audit=json.loads((REFERENCE/'timestamp_audit.json').read_text(encoding='utf-8'))
    if sha256(p)!=audit['derived_sha256'] or sha256(REFERENCE/'Steel_industry_data.csv')!=audit['raw_sha256']:
        raise ValueError('参考文件SHA256与来源审计不符，拒绝计算')
    raw=pd.read_csv(p)
    end=pd.to_datetime(raw.effective_interval_end)
    if len(raw)!=35040 or not end.is_unique or not (end.diff().dropna()==pd.Timedelta(minutes=15)).all():
        raise ValueError('参考数据间隔审计失败，不能运行')
    energy=pd.to_numeric(raw.Usage_kWh,errors='raise')
    if energy.isna().any() or (energy<0).any() or not np.isfinite(energy).all(): raise ValueError('参考能量无效')
    start=end-pd.Timedelta(minutes=15)
    # Quarter-hour interval energy -> average kW; mean four quarters conserves kWh.
    quarter=pd.DataFrame({'load_kw':energy.to_numpy()*4},index=pd.DatetimeIndex(start))
    hourly=quarter.resample('h').mean()
    assert abs(hourly.load_kw.sum()-energy.sum())<1e-6
    provenance=json.loads((REFERENCE/'provenance.json').read_text(encoding='utf-8'))
    meta={'dataset_id':'uci-steel-hourly','name':'UCI 钢铁行业公开负荷 · 小时聚合',
        'rows_raw':len(raw),'rows_hourly':len(hourly),'start':str(hourly.index[0]),'end':str(hourly.index[-1]),
        'source_type':'public_observed','unit':'kW','timezone':'source-local; UCI未提供时区',
        'interval_minutes':60,'quality':{'passed':True,'missing':0,'duplicates':0,'negative':0,
        'energy_conserved':True,'raw_interval_minutes':15,'timestamp_inference':True},
        'provenance':{'source_url':'https://archive.ics.uci.edu/dataset/851/steel%2Bindustry%2Benergy%2Bconsumption',
        'license':'CC BY 4.0','doi':'10.24432/C52G8C','normalized_sha256':sha256(p),
        'raw_sha256':sha256(REFERENCE/'Steel_industry_data.csv'),
        'attribution':'V E, S., Shin, C., & Cho, Y. (2021). Steel Industry Energy Consumption. UCI.',
        'transformation':'NSM=0日期加一天推断区间末，减15分钟得区间始；区间kWh×4，再四点均值成小时kW。',
        'warning':'午夜含义为工程推断，未由作者确认；公开韩国工厂负荷+合成中国币种电价和电池，非客户收益。'}}
    return hourly,meta

def load_dataset(dataset_id):
    if dataset_id=='uci-steel-hourly': return reference_data()
    if not dataset_id.startswith('csv-') or not dataset_id[4:].isalnum(): raise ValueError('未知数据集')
    p=UPLOADS/dataset_id
    if not (p/'metadata.json').exists(): raise ValueError('未知数据集')
    meta=json.loads((p/'metadata.json').read_text(encoding='utf-8'))
    if sha256(p/'raw.csv')!=meta['provenance']['raw_sha256'] or sha256(p/'hourly.csv')!=meta['provenance'].get('hourly_sha256'):
        raise ValueError('导入数据SHA256与审计记录不符，拒绝计算')
    frame=pd.read_csv(p/'hourly.csv',parse_dates=['timestamp']).set_index('timestamp')
    return frame,meta

def datasets():
    out=[reference_data()[1]]
    if UPLOADS.exists():
        for p in sorted(UPLOADS.glob('csv-*/metadata.json')): out.append(json.loads(p.read_text(encoding='utf-8')))
    return out

def import_csv(csv_text,name,timezone,unit,authorized):
    errors=[]
    if not authorized: return {'valid':False,'errors':[{'row':0,'field':'authorized','value':False,'reason':'请确认拥有上传与使用数据的授权'}]}
    if unit not in ('kW','kWh'): return {'valid':False,'errors':[{'row':0,'field':'unit','value':unit,'reason':'只接受明确的 kW 或每小时区间 kWh'}]}
    if not timezone.strip(): return {'valid':False,'errors':[{'row':0,'field':'timezone','value':timezone,'reason':'必须注明时区，未知可写source-local-unknown'}]}
    try: frame=pd.read_csv(io.StringIO(csv_text))
    except Exception as e: return {'valid':False,'errors':[{'row':0,'field':'csv','value':'','reason':str(e)}]}
    if set(['timestamp','load_kw' if unit=='kW' else 'load_kwh'])-set(frame.columns):
        return {'valid':False,'errors':[{'row':1,'field':'header','value':list(frame.columns),'reason':'必需 timestamp,load_kw；能量单位使用 timestamp,load_kwh。时间为小时区间开始。'}]}
    col='load_kw' if unit=='kW' else 'load_kwh'
    # Require local, exact hour-start timestamps. Offsets/DST need a separate policy.
    try:
        dates=pd.to_datetime(frame.timestamp,errors='coerce')
        if not isinstance(dates.dtype, np.dtypes.DateTime64DType) or dates.dt.tz is not None:
            return {'valid':False,'errors':[{'row':0,'field':'timestamp','value':'','reason':'请使用无偏移的本地整点时间，并在时区字段声明时区；本版不支持偏移混合或夏令时转换。'}]}
    except (ValueError, TypeError, AttributeError):
        return {'valid':False,'errors':[{'row':0,'field':'timestamp','value':'','reason':'时间格式不一致；须为无偏移的本地整点时间。'}]}
    nums=pd.to_numeric(frame[col],errors='coerce')
    for i in frame.index:
        if pd.isna(dates[i]): errors.append({'row':int(i+2),'field':'timestamp','value':str(frame.timestamp[i]),'reason':'无法解析时间'})
        elif dates[i]!=dates[i].floor('h'): errors.append({'row':int(i+2),'field':'timestamp','value':str(frame.timestamp[i]),'reason':'时间必须是完整小时区间开始，不接受分钟或秒偏移'})
        if not np.isfinite(nums[i]) or nums[i]<0: errors.append({'row':int(i+2),'field':col,'value':str(frame[col][i]),'reason':'负荷须为有限非负数'})
    if not errors:
        for i in range(1,len(dates)):
            if dates[i]-dates[i-1]!=pd.Timedelta(hours=1): errors.append({'row':i+2,'field':'timestamp','value':str(frame.timestamp[i]),'reason':'V1 CSV须按原顺序连续小时数据，不允许重复、乱序、缺口或夏令时变化'})
    if len(frame)<24*90: errors.append({'row':0,'field':'length','value':len(frame),'reason':'训练/验证/回放至少需要90天连续小时数据'})
    if errors:return {'valid':False,'errors':errors[:100],'error_count':len(errors)}
    hourly=pd.DataFrame({'load_kw':nums.to_numpy()},index=pd.DatetimeIndex(dates))
    if hourly.index[0].hour!=0 or hourly.index[-1].hour!=23: return {'valid':False,'errors':[{'row':0,'field':'timestamp','value':'','reason':'数据必须从00:00开始、23:00结束，覆盖完整天'}]}
    ident='csv-'+hashlib.sha256((csv_text+'\0'+unit+'\0'+timezone+'\0'+name[:120]).encode('utf-8')).hexdigest()[:16]
    meta={'dataset_id':ident,'name':name[:120],'rows_raw':len(frame),'rows_hourly':len(frame),
        'start':str(dates.iloc[0]),'end':str(dates.iloc[-1]),'source_type':'user_authorized_observed','unit':'kW',
        'timezone':timezone,'interval_minutes':60,'quality':{'passed':True,'missing':0,'duplicates':0,'negative':0},
        'provenance':{'raw_sha256':hashlib.sha256(csv_text.encode()).hexdigest(),'source':'User uploaded CSV','license':'User attested authorization; not independently verified','transformation':'Hourly interval-start CSV, no imputation; kWh / 1 hour if supplied.'}}
    dest=UPLOADS/ident;dest.mkdir(parents=True,exist_ok=True)
    if (dest/'metadata.json').exists():
        load_dataset(ident)  # An identical import is immutable and checked before reuse.
        return {'valid':True,'dataset':json.loads((dest/'metadata.json').read_text(encoding='utf-8')),'errors':[]}
    (dest/'raw.csv').write_bytes(csv_text.encode('utf-8'))
    hourly.to_csv(dest/'hourly.csv',index_label='timestamp',encoding='utf-8',lineterminator='\n')
    meta['provenance']['hourly_sha256']=sha256(dest/'hourly.csv')
    meta['provenance']['row_mapping']='hourly row i maps to original CSV line i+2; no sorting, resampling or imputation'
    (dest/'metadata.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf-8')
    return {'valid':True,'dataset':meta,'errors':[]}
