"""Pinned public data acquisition. Streaming downloads; no model evaluation."""
from pathlib import Path
import datetime, hashlib, json, time, urllib.request

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'data'/'v3'
TASKS=[
 ('rsf-measured-2011.csv','https://data.openei.org/files/358/rsfmeasureddata2011.csv','raw'),
 ('rsf-weather-2011.csv','https://data.openei.org/files/359/rsfweatherdata2011.csv','raw'),
 ('rsf-report-57785.pdf','https://docs.nlr.gov/docs/fy13osti/57785.pdf','raw'),
 ('bdg2-metadata.csv','https://media.githubusercontent.com/media/buds-lab/building-data-genome-project-2/v1.0/data/metadata/metadata.csv','raw'),
 ('bdg2-electricity.csv','https://media.githubusercontent.com/media/buds-lab/building-data-genome-project-2/v1.0/data/meters/raw/electricity.csv','raw'),
 ('bdg2-LICENSE.txt','https://raw.githubusercontent.com/buds-lab/building-data-genome-project-2/v1.0/LICENSE','licenses'),
 ('bdg2-master-LICENSE.txt','https://raw.githubusercontent.com/buds-lab/building-data-genome-project-2/master/LICENSE','licenses'),
 ('opsd-15min.csv','https://data.open-power-system-data.org/household_data/2020-04-15/household_data_15min_singleindex.csv','raw'),
 ('opsd-datapackage.json','https://data.open-power-system-data.org/household_data/2020-04-15/datapackage.json','licenses'),
 ('cc-by-4.0.html','https://creativecommons.org/licenses/by/4.0/legalcode.en','licenses'),
 ('rsf-source-measured.html','https://catalog.data.gov/dataset/nrel-rsf-measured-data-2011','licenses'),
 ('rsf-source-weather.html','https://catalog.data.gov/dataset/nrel-rsf-weather-data-2011','licenses'),
]

def hashfile(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()

def main():
 freeze=json.loads((DATA/'protocol-freeze.json').read_text(encoding='utf-8-sig'))
 assert hashfile(ROOT/freeze['protocol_path'])==freeze['protocol_sha256'], 'Frozen protocol changed before acquisition'
 destlog=ROOT/'qa/v3/data-acquisition.json'
 records=json.loads(destlog.read_text(encoding='utf-8')) if destlog.exists() else []
 for name,url,subdir in TASKS:
  dest=DATA/subdir/name
  previous=next((r for r in reversed(records) if r['name']==name and r['status']=='PASS'),None)
  if previous and dest.exists() and hashfile(dest)==previous['sha256']:
   print('CACHED',name,flush=True);continue
  start=time.perf_counter();rec={'name':name,'url':url,'started_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'protocol_id':freeze['protocol_id']}
  try:
   dest.parent.mkdir(parents=True,exist_ok=True)
   req=urllib.request.Request(url,headers={'User-Agent':'NengcePilot/3 public research data (single stream)','Accept':'*/*'})
   with urllib.request.urlopen(req,timeout=120) as response, dest.with_suffix(dest.suffix+'.partial').open('wb') as f:
    size=0
    rec['content_type']=response.headers.get('Content-Type');rec['etag']=response.headers.get('ETag')
    rec['redirected']=response.url!=url
    while True:
     b=response.read(1024*1024)
     if not b:break
     size+=len(b)
     if size>1_000_000_000:raise ValueError('Dataset exceeds declared 1GB acquisition ceiling')
     f.write(b)
   temp=dest.with_suffix(dest.suffix+'.partial')
   if size<100:raise ValueError('Unexpected tiny file')
   if subdir=='raw' and b'<html' in temp.open('rb').read(1000).lower():raise ValueError('HTML error returned instead of CSV')
   temp.replace(dest)
   rec.update(status='PASS',bytes=size,sha256=hashfile(dest),local_path=str(dest.relative_to(ROOT)))
  except Exception as e:rec.update(status='FAIL',error=type(e).__name__+': '+str(e)[:600])
  rec['elapsed_seconds']=round(time.perf_counter()-start,3)
  records.append(rec);destlog.write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
  print(rec['status'],name,rec.get('bytes'),rec.get('error',''),flush=True)
  time.sleep(1)
 return 0 if all(any(x['name']==n and x['status']=='PASS' for x in records) for n,_,_ in TASKS) else 1

def prepare():
 import sys
 import numpy as np
 import pandas as pd
 sys.path.insert(0,str(ROOT/'product'))
 from backend.v3.data import save_dataset
 raw=DATA/'raw'
 protocol=json.loads((DATA/'protocol-freeze.json').read_text(encoding='utf-8-sig'))
 assert hashfile(ROOT/protocol['protocol_path'])==protocol['protocol_sha256']
 def source(*names):return [{'path':str((raw/n).relative_to(ROOT)),'sha256':hashfile(raw/n)} for n in names]
 def evaluation(year,role):
  if year==2011:return {'train_start':'2011-01-01','train_end':'2011-06-30','validation_start':'2011-07-01','validation_end':'2011-09-30','test_start':'2011-10-01','test_end':'2011-12-31','role':role,'protocol_id':protocol['protocol_id']}
  return {'train_start':'2016-01-01','train_end':'2016-12-31','validation_start':'2017-01-01','validation_end':'2017-09-30','test_start':'2017-10-01','test_end':'2017-12-31','role':role,'protocol_id':protocol['protocol_id']}
 def scope(dispatch=True,pv=False,demand=False,reason='示例合同计价，非实际客户账单'):
  return {'dispatch':dispatch,'energy_billing':dispatch,'demand_15min':demand and dispatch,'photovoltaic':pv,'reason':reason}
 catalog=[]
 # UCI: verify the existing frozen source before any transformation.
 from backend.data import reference_data
 hourly,oldmeta=reference_data()
 ref=ROOT/'data/reference'
 q=pd.read_csv(ref/'Steel_industry_data_normalized_v1.csv')
 idx=pd.to_datetime(q.effective_interval_end)-pd.Timedelta(minutes=15)
 quarter=pd.DataFrame({'load_kw':q.Usage_kWh.to_numpy()*4,'pv_kw':0.,'observed':True,
   'source_row':np.arange(len(q))+2,'source_timestamp':q.effective_interval_end.astype(str).to_numpy()},index=pd.DatetimeIndex(idx))
 for interval,frame in [(15,quarter),(60,quarter.resample('h').agg({'load_kw':'mean','pv_kw':'mean','observed':'all','source_row':'first','source_timestamp':'first'}))]:
  meta={**oldmeta,'dataset_id':f'uci-steel-{interval}min' if interval==15 else 'uci-steel-hourly',
   'source_id':'uci-steel-2018','name':f'UCI 钢厂 · 原生15分钟' if interval==15 else 'UCI 钢厂 · 小时聚合',
   'interval_minutes':interval,'time_axis':'source-local','billing_timezone':None,'pv_available':False,
   'scope':scope(demand=interval==15),'provenance':{**oldmeta['provenance'],
    'raw_files':[{'path':str((ref/n).relative_to(ROOT)),'sha256':hashfile(ref/n)} for n in ['Steel_industry_data.csv','Steel_industry_data_normalized_v1.csv']],
    'transformation':'UCI工程推断区间末减15分钟；Usage_kWh÷0.25平均kW；小时采用四点均值。原行政时区未知。'},
   'default_evaluation':{'train_start':'2018-01-01','train_end':'2018-08-31','validation_start':'2018-09-01','validation_end':'2018-11-30','test_start':'2018-12-01','test_end':'2018-12-31','role':'historical_regression','protocol_id':protocol['protocol_id']}}
  catalog.append(save_dataset(frame,meta));print('PREPARED',meta['dataset_id'],flush=True)
 # RSF: never treat total energy (which includes thermal allocations) as electric load.
 r=pd.read_csv(raw/'rsf-measured-2011.csv')
 electrical=['Total Mechanical (kW)','Total Lighting (kW)','Total Plug Loads (kW)','Total Data Center (kW)']
 elec=r[electrical].apply(pd.to_numeric,errors='coerce').sum(axis=1,min_count=len(electrical))
 signed_pv=pd.to_numeric(r['PV (kW)'],errors='coerce')
 pv=(-signed_pv).clip(lower=0)
 auxiliary=signed_pv.clip(lower=0)
 # Source PV is signed: generation is negative and small positive values draw
 # energy. Split its signs while conserving original net flow exactly.
 base_elec=elec.copy();elec=elec+auxiliary
 idx=pd.DatetimeIndex(pd.to_datetime(r['Date and Time'],format='%m/%d/%Y %H:%M')).tz_localize('Etc/GMT+7').tz_convert('UTC').tz_localize(None)
 frame=pd.DataFrame({'load_kw':elec.to_numpy(),'pv_kw':pv.to_numpy(),
  'observed':(np.isfinite(elec)&np.isfinite(pv)&(elec>=0)&(pv>=0)).to_numpy(),
  'source_row':np.arange(len(r))+2,'source_timestamp':r['Date and Time'].to_numpy(),
  'source_total_energy_kw':r['Total Building (kW)'].to_numpy(),'source_heating_energy_kw':r['Total Heating (kW)'].to_numpy(),
  'source_cooling_energy_kw':r['Total Cooling (kW)'].to_numpy(),
  'source_signed_pv_kw':signed_pv.to_numpy(),'pv_auxiliary_consumption_kw':auxiliary.to_numpy()},index=idx)
 remainder=pd.to_numeric(r['Total Building (kW)'],errors='coerce')-pd.to_numeric(r['Total Heating (kW)'],errors='coerce')-pd.to_numeric(r['Total Cooling (kW)'],errors='coerce')
 audit={'status':'PASS_boundary_restricted','rows':len(r),'electrical_columns':electrical,'formula':'sum named electrical subchannels; not whole-building utility meter',
  'total_minus_thermal_vs_subchannel_max_abs_kw':float((remainder-base_elec).abs().max()),
  'provider_imputation_flags_available':False,'pdf_pages_one_based':[12,14],
  'source_pv_generation_negative_count':int((signed_pv<0).sum()),'source_pv_auxiliary_positive_count':int((signed_pv>0).sum()),
  'source_net_equals_total_plus_signed_pv_max_abs_kw':float((r['Building Net (kW)']-r['Total Building (kW)']-signed_pv).abs().max()),
  'subload_sign_split_net_conservation_max_abs_kw':float(((elec-pv)-(base_elec+signed_pv)).abs().max()),
  'report_sha256':hashfile(raw/'rsf-report-57785.pdf')}
 (ROOT/'qa/v3/data-rsf-boundary.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf-8')
 # Invalid source targets are retained as NaN, never repaired to pretend measured truth.
 frame.loc[~frame.observed,['load_kw','pv_kw']]=np.nan
 meta={'dataset_id':'rsf-hourly','source_id':'rsf-2011','name':'RSF · 电气分项与同站PV研究场景',
  'interval_minutes':60,'source_type':'public_observed_provider_cleaned','time_axis':'UTC','timezone':'MST (fixed UTC-07:00)','billing_timezone':'Etc/GMT+7',
  'partial_meter_boundary':True,'original_observation_verified':False,'pv_available':True,
  'observed_semantics':'valid published measurement after provider cleaning; original sensor/imputation status unavailable',
  'scope':scope(pv=True,reason='已清洗电气分项与同站PV的假设连接研究场景；非整站真实电费/自用率；小时不认证15分钟需量'),
  'provenance':{'source_url':'https://data.openei.org/submissions/358','license':'CC BY 4.0 (OEDI individual dataset record)',
   'doi':'10.25984/1845288','attribution':'Sheppy, Beach, Pless; NREL RSF Measured Data 2011. DOE/NREL.',
   'raw_files':source('rsf-measured-2011.csv','rsf-weather-2011.csv','rsf-report-57785.pdf'),
   'transformation':'Electrical subchannels summed; Total Building includes thermal allocations and is NOT electric demand. Original PV negative means generation: pv_kw=max(-signed_pv,0); positive signed PV auxiliary consumption is added to subload, conserving net flow. Hourly label assumed interval start for illustrative replay; weather is fixed MST.',
   'warning':'报告第12页：发布者已插补但未给逐点标记。第14页：热/冷能源折算。子负荷配全部同站PV仅为假设连接情景，非原站自用率。'},
  'default_evaluation':evaluation(2011,'external_time')}
 catalog.append(save_dataset(frame,meta));print('PREPARED rsf-hourly',flush=True)
 # BDG2: streaming quality counts before deterministic selection; no model metrics.
 metadata=pd.read_csv(raw/'bdg2-metadata.csv').set_index('building_id')
 counts={};positive={};totals={};cols=None
 for chunk in pd.read_csv(raw/'bdg2-electricity.csv',chunksize=512):
  years=pd.to_datetime(chunk['timestamp']).dt.year;nums=chunk.drop(columns='timestamp').apply(pd.to_numeric,errors='coerce')
  cols=list(nums)
  for year in (2016,2017):
   v=nums.loc[years==year]
   if not len(v):continue
   ok=np.isfinite(v)&(v>=0)
   counts[year]=counts.get(year,pd.Series(0,index=cols,dtype='int64'))+ok.sum()
   positive[year]=positive.get(year,pd.Series(0,index=cols,dtype='int64'))+(v>0).sum()
   totals[year]=totals.get(year,0)+len(v)
 seed=protocol['seed'];order=lambda v:hashlib.sha256((seed+':'+str(v)).encode()).hexdigest()
 candidates=metadata.loc[metadata.index.intersection(cols)]
 candidates=candidates.loc[candidates.electricity.notna()]
 decisions=[];selected=[];selected_sites=[]
 for site in sorted(candidates.site_id.unique(),key=order):
  eligible=[]
  for bid in sorted(candidates.index[candidates.site_id==site],key=order):
   rates={str(y):{'valid_fraction':float(counts[y][bid]/totals[y]),'positive_fraction':float(positive[y][bid]/totals[y])} for y in (2016,2017)}
   good=all(v['valid_fraction']>=.95 and v['positive_fraction']>=.05 for v in rates.values())
   decisions.append({'building_id':bid,'site_id':site,'eligible':good,'quality':rates,'reason':'quality_pass' if good else 'predeclared_quality_threshold'})
   if good:eligible.append(bid)
  if len(eligible)>=4 and len(selected_sites)<6:
   role='development' if len(selected_sites)<3 else 'external'
   selected_sites.append(site)
   selected.extend({'building_id':b,'site_id':site,'role':role} for b in eligible[:4])
 selection={'status':'PASS' if len(selected)==24 else 'BLOCKED','protocol_id':protocol['protocol_id'],'seed':seed,'selected_sites':selected_sites,'selected':selected,'decisions':decisions,'model_evaluation_performed':False}
 (ROOT/'qa/v3/data-bdg2-selection.json').write_text(json.dumps(selection,ensure_ascii=False,indent=2),encoding='utf-8')
 ids=[x['building_id'] for x in selected]
 small=pd.read_csv(raw/'bdg2-electricity.csv',usecols=['timestamp']+ids)
 idx=pd.DatetimeIndex(pd.to_datetime(small.timestamp))
 raw_sources=source('bdg2-electricity.csv','bdg2-metadata.csv')
 for s in selected:
  bid=s['building_id'];m=metadata.loc[bid];v=pd.to_numeric(small[bid],errors='coerce');valid=np.isfinite(v)&(v>=0)
  f=pd.DataFrame({'load_kw':v.where(valid).to_numpy(),'pv_kw':0.,'observed':valid.to_numpy(),'source_row':np.arange(len(v))+2,'source_timestamp':small.timestamp.to_numpy()},index=idx)
  did='bdg2-'+bid.lower().replace('_','-')
  meta={'dataset_id':did,'source_id':'bdg2-v1.0','name':f"BDG2 · {bid} · {'外部留出' if s['role']=='external' else '开发'}",'site_id':s['site_id'],
   'building_id':bid,'building_usage':str(m.primaryspaceusage),'interval_minutes':60,'source_type':'public_observed',
   'time_axis':'source-local','timezone':str(m.timezone)+' (published local clock; DST fold unavailable)','source_timezone':str(m.timezone),'billing_timezone':None,
   'scope':scope(reason='作者发布的本地小时轴；DST fold不可恢复，仅小时示例情景，非实际合同账单'),
   'provenance':{'source_url':'https://github.com/buds-lab/building-data-genome-project-2/tree/v1.0','license':'MIT (fixed v1.0 repository LICENSE; current master differs)',
    'license_path':'data/v3/licenses/bdg2-LICENSE.txt','license_sha256':hashfile(DATA/'licenses/bdg2-LICENSE.txt'),'doi':'10.5281/zenodo.3887306',
    'attribution':'Miller et al. (2020), Building Data Genome Project 2; BUDS Lab.','raw_files':raw_sources,
    'transformation':f'Raw electricity column {bid}, hourly kWh / 1h = average kW; no target interpolation; published local clock retained.',
    'warning':'公共建筑基准，非客户收益；源数据本地小时轴无逐行UTC偏移，不能恢复DST重复时刻。'},'default_evaluation':evaluation(2016,s['role'])}
  catalog.append(save_dataset(f,meta))
 print('PREPARED BDG2',len(selected),'buildings',len(selected_sites),'sites',flush=True)
 # OPSD cumulative registers: forward differences represent the following interval.
 header=pd.read_csv(raw/'opsd-15min.csv',nrows=0).columns
 sites=['industrial1','industrial2','industrial3','public1','public2']
 channels=[c for c in header if any(c.startswith('DE_KN_'+s+'_') for s in sites)]
 o=pd.read_csv(raw/'opsd-15min.csv',usecols=['utc_timestamp','cet_cest_timestamp','interpolated']+channels)
 idx=pd.DatetimeIndex(pd.to_datetime(o.utc_timestamp,utc=True)).tz_localize(None)
 markers=o.interpolated.fillna('').astype(str);raw_sources=source('opsd-15min.csv')
 for site in sites:
  grid='DE_KN_'+site+'_grid_import';pvcols=[c for c in channels if c.startswith('DE_KN_'+site+'_pv')]
  rgrid=pd.to_numeric(o[grid],errors='coerce');energy=rgrid.shift(-1)-rgrid
  pve=pd.Series(0.,index=o.index)
  valid=np.isfinite(energy)&(energy>=0)
  observed=valid & ~markers.str.contains(grid,regex=False)&~markers.shift(-1).fillna('').str.contains(grid,regex=False)
  for c in pvcols:
   reg=pd.to_numeric(o[c],errors='coerce');diff=reg.shift(-1)-reg;pve=pve+diff
   valid &= np.isfinite(diff)&(diff>=0)
   observed &= ~markers.str.contains(c,regex=False)&~markers.shift(-1).fillna('').str.contains(c,regex=False)
  observed &= valid
  f=pd.DataFrame({'load_kw':(energy*4).where(valid).to_numpy(),'pv_kw':(pve*4).where(valid).to_numpy(),'observed':observed.to_numpy(),
   'source_row':np.arange(len(o))+2,'source_row_end':np.arange(len(o))+3,'source_timestamp':o.utc_timestamp.to_numpy(),
   'source_grid_import_register_kwh':rgrid.to_numpy(),'source_interpolated':markers.to_numpy()},index=idx)
  finite=np.flatnonzero(valid.to_numpy())
  if len(finite):f=f.iloc[finite[0]:finite[-1]+1]
  else:continue
  meta={'dataset_id':'opsd-'+site,'source_id':'opsd-2020-04-15','name':'OPSD · '+site+' · 多通道诊断',
   'site_id':site,'interval_minutes':15,'source_type':'public_observed_with_interpolation','time_axis':'UTC','timezone':'Europe/Berlin','billing_timezone':'Europe/Berlin',
   'pv_available':bool(pvcols),'channel_only':True,'partial_meter_boundary':True,
   'scope':scope(False,bool(pvcols),reason='累计净进口/PV寄存器诊断；缺整站总负荷/出口或既有DER边界证明，拒绝调度和收益核算'),
   'provenance':{'source_url':'https://data.open-power-system-data.org/household_data/2020-04-15/','license':'CC BY 4.0',
    'attribution':'Open Power System Data (2020). Household Data, 2020-04-15. CoSSMic / ISC Konstanz.',
    'raw_files':raw_sources,'channels':[grid]+pvcols,
    'transformation':'Published cumulative kWh registers: (register[t+1]-register[t])/0.25; both endpoint interpolation flags retained. Negative/reset/missing differences remain NaN.',
    'warning':'源15min文件是累计kWh，不是区间电量；插补点非原始观测。无完整计量边界时不能把净表当无储能负荷。'},
   'default_evaluation':{'role':'channel_only','protocol_id':protocol['protocol_id'],'test_start':str((f.index[-1]-pd.Timedelta(days=89)).date()),'test_end':str(f.index[-1].date())}}
  catalog.append(save_dataset(f,meta));print('PREPARED',meta['dataset_id'],flush=True)
 summary={'status':'PASS' if len(selected)==24 else 'BLOCKED','protocol_id':protocol['protocol_id'],'datasets':len(catalog),
  'bdg2_buildings':len(selected),'bdg2_sites':len(selected_sites),'bdg2_development':sum(x['role']=='development' for x in selected),
  'bdg2_external':sum(x['role']=='external' for x in selected),'raw_bytes':sum(p.stat().st_size for p in raw.glob('*') if p.is_file()),
  'model_evaluation_performed':False,'entries':[{'dataset_id':m['dataset_id'],'rows':m['rows'],'dispatch':m['scope']['dispatch'],'quality_missing':m['quality']['missing'],'complete_months':len(m['quality']['complete_months']),'demand_eligible':m['demand_eligible']} for m in catalog]}
 (ROOT/'qa/v3/data-preparation.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
 (DATA/'catalog-manifest.json').write_text(json.dumps({'protocol':protocol,'datasets':[{'dataset_id':m['dataset_id'],'sha256':m['provenance']['normalized_sha256']} for m in catalog]},ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps({k:v for k,v in summary.items() if k!='entries'},ensure_ascii=False),flush=True)
 return 0 if summary['status']=='PASS' else 1

if __name__=='__main__':
 import sys
 raise SystemExit(prepare() if '--prepare' in sys.argv else main())
