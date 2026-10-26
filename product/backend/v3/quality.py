"""Descriptive anomaly clues with thresholds and original CSV record locations.

These checks never label equipment faults or silently remove observations.
"""
import numpy as np
import pandas as pd
from .data import load_dataset, local_index


def inspect_dataset(dataset_id):
    frame,meta=load_dataset(dataset_id)
    valid=np.isfinite(frame.load_kw)&(frame.load_kw>=0)
    y=frame.load_kw.where(valid)
    diff=y.diff().abs()
    changes=diff.dropna().to_numpy()
    median=float(np.median(changes)) if len(changes) else 0.
    mad=float(np.median(np.abs(changes-median))) if len(changes) else 0.
    p95=float(y.quantile(.95)) if valid.any() else 0.
    threshold=max(median+6*mad,p95*.25,1e-6)
    zero=y.eq(0)
    groups=(zero!=zero.shift()).cumsum()
    run_length=zero.groupby(groups).transform('size')
    minimum=max(2,round(6*60/meta['interval_minutes']))
    rules=[('invalid','无效或负负荷',~valid,{'rule':'有限且非负'}),
           ('unobserved','缺失或非原始观测',~frame.get('observed',valid).fillna(False).astype(bool),{'rule':'observed=true'}),
           ('jump','相邻间隔变化线索',diff>threshold,{'absolute_delta_kw':threshold,'method':'max(median(|Δ|)+6×MAD(|Δ|), P95(load)×0.25, 0.000001)'}),
           ('zero_run','连续零负荷线索',zero&(run_length>=minimum),{'minimum_intervals':minimum,'minimum_hours':6})]
    detections=[]
    local=local_index(frame,meta)
    for ident,label,mask,parameters in rules:
        positions=np.flatnonzero(mask.to_numpy())
        examples=[]
        for position in positions[:100]:
            row=frame.iloc[position]
            example={'timestamp':str(local[position]),'load_kw':float(row.load_kw) if np.isfinite(row.load_kw) else None,
                     'source_row':int(row.source_row) if 'source_row' in row and pd.notna(row.source_row) else None,
                     'source_timestamp':str(row.get('source_timestamp','')),
                     'delta_kw':float(diff.iloc[position]) if np.isfinite(diff.iloc[position]) else None}
            for field in ('source_row_start','source_row_end'):
                if field in row and pd.notna(row[field]):example[field]=int(row[field])
            examples.append(example)
        detections.append({'id':ident,'label':label,'count':len(positions),'threshold':parameters,
                           'examples':examples,'examples_truncated':len(positions)>100,
                           'handling':'保留原始记录，不自动删除或插补；用于人工核查，未作故障诊断'})
    return {'dataset_id':dataset_id,'quality':meta['quality'],'detections':detections,
            'normalized_sha256':meta['provenance']['normalized_sha256'],
            'source_rows_semantics':meta['provenance']['row_mapping'],
            'scope':'描述性检查，阈值不参与预测调参或独立验证选样；未验证故障标签'}
