"""Causal daily-origin load/PV forecasting with a fixed CPU model budget."""
import time

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from threadpoolctl import threadpool_limits

from ..forecast import MODEL_PARAMETERS, metrics, select_model

FEATURES = ['hour', 'weekday', 'month', 'sin_hour', 'cos_hour', 'lag_24h', 'lag_48h', 'lag_168h', 'lag_336h', 'previous_day_mean', 'previous_day_max', 'previous_week_mean']
PROTOCOL_ID = 'nengce-v3-data-20261004'


def _date(value, index):
    t = pd.Timestamp(value)
    if pd.isna(t) or t != t.normalize():
        raise ValueError('评估日期须为有效的完整日日期')
    if index.tz is not None:
        t = t.tz_localize(index.tz) if t.tz is None else t.tz_convert(index.tz)
    elif t.tz is not None:
        raise ValueError('源时间轴未知时不能使用带时区日期')
    return t


def feature_matrix(frame, column, dt):
    # Feature-only causal forward fill; never replace missing evaluation truth.
    y = frame[column].ffill(); idx = frame.index
    hour = idx.hour + idx.minute/60
    X = pd.DataFrame({'hour': hour, 'weekday': idx.dayofweek, 'month': idx.month,
                      'sin_hour': np.sin(hour*2*np.pi/24), 'cos_hour': np.cos(hour*2*np.pi/24)}, index=idx)
    for lag in (24, 48, 168, 336):
        values = y.shift(round(lag/dt))
        # In a 25-hour DST day, a 24-hour lag can reach the same forecast origin.
        # Use the already completed 48-hour lag there rather than future leakage.
        bad = (idx-pd.Timedelta(hours=lag)) >= idx.normalize()
        if bad.any():
            values.loc[bad] = y.shift(round((lag+24)/dt)).loc[bad]
        X[f'lag_{lag}h'] = values
    daily = y.resample('D').agg(['mean', 'max'])
    for field, values in [('previous_day_mean', daily['mean'].shift(1)),
                          ('previous_day_max', daily['max'].shift(1)),
                          ('previous_week_mean', daily['mean'].shift(1).rolling(7).mean())]:
        X[field] = values.reindex(idx.normalize()).to_numpy()
    return X[FEATURES]


def _channel(frame, column, X, start, end, boundaries, observed, dt, training_limit=None):
    available = X.notna().all(axis=1)
    test = (frame.index >= start) & (frame.index < end) & available
    names = ['HistGradientBoosting', 'Daily naive', 'Weekly naive']
    folds, ys, predictions, failures = [], [], [[], [], []], []
    model = None
    before = time.perf_counter()
    for fold_start, fold_end in zip(boundaries, boundaries[1:]):
        train = (frame.index < (min(fold_start,training_limit) if training_limit is not None else fold_start)) & available & observed
        valid = (frame.index >= fold_start) & (frame.index < fold_end) & available & observed
        if train.sum() < 30*24/dt or valid.sum() < 24/dt:
            raise ValueError('开发滚动验证的真实历史不足；至少需要75天连续历史')
        candidate = HistGradientBoostingRegressor(**MODEL_PARAMETERS)
        failure = None
        try:
            with threadpool_limits(limits=1):
                candidate.fit(X.loc[train], frame.loc[train, column])
                ph = np.maximum(0, candidate.predict(X.loc[valid]))
            model = candidate
        except Exception as exc:
            failure = f'{type(exc).__name__}: {exc}'
            failures.append(failure); model = None
            ph = X.loc[valid, 'lag_168h'].to_numpy()
        vp = [ph, X.loc[valid, 'lag_24h'].to_numpy(), X.loc[valid, 'lag_168h'].to_numpy()]
        y = frame.loc[valid, column].to_numpy(); ys.append(y)
        for i, prediction in enumerate(vp):
            predictions[i].append(prediction)
        folds.append({'start': str(fold_start), 'end': str(fold_end-pd.Timedelta(hours=dt)),
                      'train_end': str(frame.index[train][-1]), 'train_rows': int(train.sum()),
                      'models': [metrics(y, p, name) for p, name in zip(vp, names)], 'failure': failure})
    yv = np.concatenate(ys); vp = [np.concatenate(x) for x in predictions]
    validation = [metrics(yv, p, name) for p, name in zip(vp, names)]
    selected, reason, policy = select_model(validation, folds, bool(failures))
    if model is not None:
        with threadpool_limits(limits=1):
            ph = np.maximum(0, model.predict(X.loc[test]))
    else:
        ph = X.loc[test, 'lag_168h'].to_numpy()
    predictions = [ph, X.loc[test, 'lag_24h'].to_numpy(), X.loc[test, 'lag_168h'].to_numpy()]
    chosen = predictions[selected]; q = float(np.quantile(np.abs(yv-vp[selected]), .9))
    risk_q = float(np.quantile(np.maximum(0, vp[selected]-yv), .75))
    score_mask = observed.loc[test].to_numpy(dtype=bool) & np.isfinite(frame.loc[test,column].to_numpy())
    if not score_mask.any():
        raise ValueError('评估区间没有可评分的真实观测')
    scores = [metrics(frame.loc[test, column].to_numpy()[score_mask], p[score_mask], name) for p, name in zip(predictions, names)]
    weekly, hgb = scores[2]['wape_pct'], scores[0]['wape_pct']
    report = {'models': scores, 'validation': validation, 'rolling_validation': folds,
              'selected_model': names[selected], 'selection_reason': reason, 'selection_policy': policy,
              'improvement_vs_weekly_pct': (weekly-hgb)/weekly*100 if weekly else None,
              'train_end': folds[-1]['train_end'], 'train_rows': folds[-1]['train_rows'],
              'validation_period': [str(boundaries[0]), str(boundaries[-1]-pd.Timedelta(hours=dt))],
              'holdout_period': [str(start), str(end-pd.Timedelta(hours=dt))], 'features': FEATURES,
              'training_seconds': time.perf_counter()-before, 'hgb_available': not failures,
              'fallback_error': '; '.join(failures) or None,
              'risk_calibration': {'quantile': .75, 'positive_overprediction_q75_kw': risk_q,
                                   'cap_fraction': .35, 'sample_count': len(yv),
                                   'period_end': str(boundaries[-1]-pd.Timedelta(hours=dt)),
                                   'method': 'Positive selected-forecast residual q75 on development folds only'},
              'interval_method': 'Development absolute residual q90; empirical marginal interval, no guaranteed coverage',
              'interval_q90_kw': q,
              'scored_intervals': int(score_mask.sum()), 'evaluation_intervals': int(test.sum()),
              'observed_evaluation_pct': float(score_mask.mean()*100),
              'interval_coverage_pct': float(np.mean(((frame.loc[test,column].to_numpy()>=np.maximum(0,chosen-q)) & (frame.loc[test,column].to_numpy()<=chosen+q))[score_mask])*100)}
    # Per-source normalized residuals permit a development-only cross-site
    # calibration without importing external target values or comparing winners.
    normalization = max(float(frame.loc[(frame.index < boundaries[0]) & observed,column].mean()),1e-9)
    report['development_calibration_by_model'] = [
        {'model':name,'mean_scale_kw':normalization,
         'absolute_q90_fraction':float(np.quantile(np.abs(yv-p),.9)/normalization),
         'positive_q75_fraction':float(np.quantile(np.maximum(p-yv,0),.75)/normalization)}
        for p,name in zip(vp,names)]
    return test, predictions, chosen, q, report


def development_report(frame):
    """BDG2 development sites only; frozen calendar-quarter rolling folds."""
    dt = (frame.index[1]-frame.index[0]).total_seconds()/3600
    bounds = [_date(value,frame.index) for value in ('2017-01-01','2017-04-01','2017-07-01','2017-10-01')]
    observed = frame.observed.astype(bool) if 'observed' in frame else pd.Series(True,index=frame.index)
    # Test output is the final development fold, not Q4; only rolling_validation
    # and pooled validation choose the common policy.
    return _channel(frame,'load_kw',feature_matrix(frame,'load_kw',dt),bounds[2],bounds[3],bounds,observed,dt,training_limit=bounds[0])[-1]


def aggregate_development(reports):
    """Freeze one algorithm choice from all development sites, weighted by rows."""
    if not reports:
        raise ValueError('需要至少一个开发站点报告')
    names = ['HistGradientBoosting','Daily naive','Weekly naive']
    pooled = []
    for m,name in enumerate(names):
        n = sum(r['validation'][m]['n'] for r in reports)
        pooled.append({'name':name,'n':n,'mae_kw':sum(r['validation'][m]['mae_kw']*r['validation'][m]['n'] for r in reports)/n})
    folds = []
    for fold in range(3):
        values=[]
        for m,name in enumerate(names):
            n=sum(r['rolling_validation'][fold]['models'][m]['n'] for r in reports)
            values.append({'name':name,'n':n,'mae_kw':sum(r['rolling_validation'][fold]['models'][m]['mae_kw']*r['rolling_validation'][fold]['models'][m]['n'] for r in reports)/n})
        folds.append({'models':values})
    chosen,reason,policy=select_model(pooled,folds,any(not r['hgb_available'] for r in reports))
    # Median of development-building normalized residual quantiles avoids using
    # unknown external site scale. The latter comes from its 2016 history only.
    q90=float(np.median([r['development_calibration_by_model'][chosen]['absolute_q90_fraction'] for r in reports]))
    q75=float(np.median([r['development_calibration_by_model'][chosen]['positive_q75_fraction'] for r in reports]))
    return {'selected_index':chosen,'selected_model':names[chosen],'selection_reason':reason,'selection_policy':policy,
            'validation':pooled,'rolling_validation':folds,'absolute_q90_fraction':q90,'positive_q75_fraction':q75,
            'calibration_method':'Median development-building normalized residual quantile; external scale from 2016 only',
            'external_train_end':'2016-12-31','model_parameters':MODEL_PARAMETERS}


def evaluate_external(frame, frozen_policy, metadata=None):
    """Single BDG2 Q4 evaluation; all algorithm decisions arrive frozen from dev."""
    metadata=metadata or {}; dt=(frame.index[1]-frame.index[0]).total_seconds()/3600
    X=feature_matrix(frame,'load_kw',dt); available=X.notna().all(axis=1)
    observed=frame.observed.astype(bool) if 'observed' in frame else pd.Series(True,index=frame.index)
    train=(frame.index>=_date('2016-01-01',frame.index)) & (frame.index<_date('2017-01-01',frame.index)) & observed & available
    test=(frame.index>=_date('2017-10-01',frame.index)) & (frame.index<_date('2018-01-01',frame.index)) & available
    if train.sum()<30*24/dt or test.sum()<24/dt:
        raise ValueError('外部评测缺少2016训练或2017Q4评分记录')
    model=HistGradientBoostingRegressor(**MODEL_PARAMETERS)
    with threadpool_limits(limits=1):
        model.fit(X.loc[train],frame.load_kw.loc[train]); ph=np.maximum(0,model.predict(X.loc[test]))
    predictions=[ph,X.loc[test,'lag_24h'].to_numpy(),X.loc[test,'lag_168h'].to_numpy()]
    chosen=predictions[int(frozen_policy['selected_index'])]
    score=observed.loc[test].to_numpy(dtype=bool)&np.isfinite(frame.load_kw.loc[test].to_numpy())
    scale=max(float(frame.load_kw.loc[train].mean()),1e-9)
    q=scale*frozen_policy['absolute_q90_fraction']; y=frame.load_kw.loc[test].to_numpy()
    out=frame.loc[test].copy();out['forecast_kw']=chosen;out['hgb_kw']=ph
    out['daily_naive_kw'],out['weekly_naive_kw']=predictions[1],predictions[2]
    out['lower_kw'],out['upper_kw']=np.maximum(0,chosen-q),chosen+q
    models=[metrics(y[score],p[score],name) for p,name in zip(predictions,['HistGradientBoosting','Daily naive','Weekly naive'])]
    return out,{'dataset_id':metadata.get('dataset_id'),'evaluation_role':'external','selected_model':frozen_policy['selected_model'],
                'selection_reason':'冻结development sites汇总政策；本外部站不重新选赢家。','policy':frozen_policy,
                'new_independent_generalization_evidence':True,'train_start':'2016-01-01','train_end':'2016-12-31',
                'test_start':'2017-10-01','test_end':'2017-12-31','training_rows':int(train.sum()),
                'scored_intervals':int(score.sum()),'evaluation_intervals':int(test.sum()),'observed_evaluation_pct':float(score.mean()*100),
                'models':models,'selected_metrics':metrics(y[score],chosen[score],frozen_policy['selected_model']),
                'interval_coverage_pct':float(np.mean(((y>=np.maximum(0,chosen-q))&(y<=chosen+q))[score])*100),
                'notes':['No external-site 2017 observations used for training or model selection.',
                         'Daily-origin lag features may consume completed previous days in Q4; no target-day values enter forecasts.',
                         'Missing test truth excluded and coverage disclosed, never interpolated for a score.']}


def train_forecasts(frame, eval_start, eval_end, metadata=None, protocol_id=None):
    metadata = metadata or {}
    if not isinstance(frame.index, pd.DatetimeIndex) or len(frame) < 2 or not frame.index.is_unique or not frame.index.is_monotonic_increasing:
        raise ValueError('数据须有连续、递增且不重复的时间索引')
    idx = frame.index
    dt = (idx[1]-idx[0]).total_seconds()/3600
    if dt not in (.25, 1.) or not (idx.to_series().diff().dropna() == pd.Timedelta(hours=dt)).all():
        raise ValueError('引擎仅接受原生连续15分钟或小时数据')
    for column in ('load_kw', 'pv_kw'):
        if column not in frame or np.isinf(frame[column]).any() or (frame[column] < 0).any():
            raise ValueError('负荷和光伏观测必须是有限非负功率，缺失值须显式标记')
    start = _date(eval_start, idx); end = _date(eval_end, idx)+pd.DateOffset(days=1)
    if start < idx[0]+pd.Timedelta(days=75) or end <= start or end > idx[-1]+pd.Timedelta(hours=dt):
        raise ValueError('日期需包含完整回放日，评估前至少75天历史，且不超出来源范围')
    if (end-start).total_seconds() > 367*86400:
        raise ValueError('单次预测评分最多366个日历日')
    default = metadata.get('default_evaluation', {})
    frozen = bool(protocol_id and protocol_id == default.get('protocol_id') and default.get('test_start') and default.get('test_end') and
                  start >= _date(default['test_start'],idx) and end <= _date(default['test_end'],idx)+pd.DateOffset(days=1))
    full_frozen_window = bool(frozen and str(start.date()) == default.get('test_start') and str((end-pd.DateOffset(days=1)).date()) == default.get('test_end'))
    if frozen and default.get('validation_start') and default.get('validation_end'):
        dev_start = _date(default['validation_start'], idx)
        dev_end = _date(default['validation_end'], idx)+pd.DateOffset(days=1)
        if dev_end > start:
            raise ValueError('冻结开发验证区间不得侵入留出期')
        months = pd.date_range(dev_start,dev_end,freq='MS')
        boundaries = [months[i] for i in range(0,len(months),(len(months)-1)//3)] if len(months)>=4 and (len(months)-1)%3==0 else [x.normalize() for x in pd.date_range(dev_start,dev_end,periods=4)]
    elif idx[0].year == 2018 and start >= _date('2018-12-01', idx) and metadata.get('dataset_id', '').startswith('uci-'):
        boundaries = list(pd.date_range(_date('2018-09-01', idx), _date('2018-12-01', idx), freq='MS'))
    else:
        boundaries = [start-pd.DateOffset(days=d) for d in (21,14,7,0)]
    observed = frame['observed'].astype(bool) if 'observed' in frame else pd.Series(True, index=idx)
    training_limit = _date(default['train_end'],idx)+pd.DateOffset(days=1) if frozen and default.get('train_end') and not metadata.get('dataset_id','').startswith('uci-') else None
    test, predictions, chosen, q, report = _channel(frame, 'load_kw', feature_matrix(frame, 'load_kw', dt), start, end, boundaries, observed, dt,training_limit)
    expected = pd.date_range(start, end, freq=pd.Timedelta(hours=dt), inclusive='left')
    if not idx[test].equals(expected):
        raise ValueError('回放日期的完整区间缺失，不能插值冒充实测')
    out = frame.loc[test].copy()
    out['forecast_kw'], out['hgb_kw'], out['daily_naive_kw'], out['weekly_naive_kw'] = chosen, predictions[0], predictions[1], predictions[2]
    out['lower_kw'], out['upper_kw'] = np.maximum(0, chosen-q), chosen+q
    if frame.pv_kw.max() > 0:
        _, pp, pc, pq, pv_report = _channel(frame, 'pv_kw', feature_matrix(frame,'pv_kw',dt), start,end,boundaries,observed,dt,training_limit)
        out['pv_forecast_kw'], out['pv_hgb_kw'], out['pv_weekly_naive_kw'] = pc, pp[0], pp[2]
        out['pv_lower_kw'], out['pv_upper_kw'] = np.maximum(0,pc-pq), pc+pq
    else:
        for field in ('pv_forecast_kw','pv_hgb_kw','pv_weekly_naive_kw','pv_lower_kw','pv_upper_kw'):
            out[field] = 0.
        pv_report = {'selected_model': 'Zero PV (source has no PV)', 'available': False,
                     'selection_reason': '来源无光伏计量，不构造合成光伏作为实测证据。'}
    role = default.get('role') if frozen else 'historical_regression' if metadata.get('dataset_id','').startswith('uci-') else 'exploratory_subperiod'
    # Cross-site selection must be supplied from development sites, never silently
    # inferred from an external site's own 2017 validation performance.
    external_selection_missing = frozen and role == 'external' and metadata.get('dataset_id','').startswith('bdg')
    if external_selection_missing:
        role = 'exploratory_external_site_selection_not_frozen'
    report.update(pv=pv_report, protocol_id=protocol_id or 'exploratory-unregistered',
                  evaluation_role=role, new_independent_generalization_evidence=bool(full_frozen_window and role in ('external','external_time')),
                  protocol_matched=frozen, protocol_complete_window=full_frozen_window, external_selection_missing=external_selection_missing, interval_hours=dt,
                  notes=['Fixed model budget: one HGB configuration, seed 42, three development folds.',
                         'Day-ahead features use completed prior days; no future observed weather, reactive power, CO2 or Load_Type.',
                         'Each daily origin may use newly completed prior days; test observations never change frozen model selection.',
                         'Forecast intervals are development residual summaries, not calibrated joint safety guarantees.',
                         'All tariffs and battery characteristics are illustrative, not measured client savings.'])
    return out, report
