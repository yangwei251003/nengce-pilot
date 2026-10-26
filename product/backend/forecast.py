import time
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from threadpoolctl import threadpool_limits

FEATURES=['hour','weekday','month','sin_hour','cos_hour','lag_24h','lag_48h','lag_168h','lag_336h','previous_day_mean','previous_day_max','previous_week_mean']
MODEL_PARAMETERS={'max_iter':140,'max_leaf_nodes':15,'learning_rate':.07,'l2_regularization':10,'early_stopping':False,'random_state':42}
PROTOCOL_ID='v2-rolling-20261004'


def feature_matrix(frame):
    y=frame.load_kw;idx=frame.index;X=pd.DataFrame(index=idx)
    X['hour']=idx.hour;X['weekday']=idx.dayofweek;X['month']=idx.month
    X['sin_hour']=np.sin(idx.hour*2*np.pi/24);X['cos_hour']=np.cos(idx.hour*2*np.pi/24)
    for lag in (24,48,168,336):X[f'lag_{lag}h']=y.shift(lag)
    day=y.resample('D').agg(['mean','max'])
    X['previous_day_mean']=day['mean'].shift(1).reindex(idx.normalize()).to_numpy()
    X['previous_day_max']=day['max'].shift(1).reindex(idx.normalize()).to_numpy()
    X['previous_week_mean']=day['mean'].shift(1).rolling(7).mean().reindex(idx.normalize()).to_numpy()
    return X[FEATURES]


def metrics(y,p,name):
    y=np.asarray(y,dtype=float);p=np.asarray(p,dtype=float)
    if y.ndim!=1 or p.shape!=y.shape or not len(y) or not np.isfinite(y).all() or not np.isfinite(p).all():
        raise ValueError('预测评分须为同长度非空有限一维数组')
    e=y-p
    return {'name':name,'mae_kw':float(np.mean(np.abs(e))),'wape_pct':float(np.abs(e).sum()/y.sum()*100) if y.sum()>0 else None,'rmse_kw':float(np.sqrt(np.mean(e**2))),'n':len(y)}


def _date_in_index_timezone(value,index):
    t=pd.Timestamp(value)
    if pd.isna(t):raise ValueError('评估日期无效')
    if index.tz is not None:
        t=t.tz_localize(index.tz) if t.tz is None else t.tz_convert(index.tz)
    elif t.tz is not None:
        raise ValueError('未知源时区的数据不能接受带时区评估日期')
    if t!=t.normalize():raise ValueError('评估日期必须为整日午夜')
    return t


def _validate_frame(frame):
    if not isinstance(frame.index,pd.DatetimeIndex) or len(frame)==0 or 'load_kw' not in frame:
        raise ValueError('预测需要带日期索引的非空小时负荷')
    idx=frame.index;y=frame.load_kw.to_numpy(dtype=float)
    if idx.hasnans or not idx.is_unique or not idx.is_monotonic_increasing or not np.isfinite(y).all() or (y<0).any():
        raise ValueError('负荷必须有限非负，时间不得重复、缺失或乱序')
    if not (idx.to_series().diff().dropna()==pd.Timedelta(hours=1)).all() or (idx.minute!=0).any() or (idx.second!=0).any() or (idx.microsecond!=0).any():
        raise ValueError('只支持连续整点小时数据')
    counts=frame.groupby(idx.normalize()).size()
    if idx[0].hour!=0 or idx[-1].hour!=23 or not (counts==24).all():
        raise ValueError('必须是完整24小时自然日，不支持夏令时变长日')


def select_model(validation,folds,failed=False):
    """Fixed before evaluation: best simple baseline, HGB needs 2% and 2/3 folds."""
    simple=2 if validation[2]['mae_kw']<=validation[1]['mae_kw'] else 1
    baseline=validation[simple]['mae_kw'];hgb=validation[0]['mae_kw']
    gain=(baseline-hgb)/baseline if baseline>0 else None
    wins=sum(f['models'][0]['mae_kw']<f['models'][simple]['mae_kw'] for f in folds)
    best=0 if not failed and gain is not None and gain>=.02 and wins>=2 else simple
    reason=(f'HGB在开发滚动验证MAE改善{gain*100:.2f}%，且胜出{wins}/3窗，达到冻结门槛。' if best==0 else
            '学习模型未达到冻结门槛或训练失败；按开发滚动验证MAE回退到'+validation[simple]['name']+'。')
    return best,reason,{'minimum_mae_improvement_pct':2.,'minimum_fold_wins':2,'observed_mae_improvement_pct':gain*100 if gain is not None else None,'observed_fold_wins':wins,'baseline':validation[simple]['name']}


def train_forecasts(frame,eval_start,eval_end):
    _validate_frame(frame)
    start=_date_in_index_timezone(eval_start,frame.index)
    end=_date_in_index_timezone(eval_end,frame.index)+pd.DateOffset(days=1)
    if end<=start:raise ValueError('评估日期必须为递增完整日')
    if start<frame.index[0]+pd.Timedelta(days=75):raise ValueError('评估前至少需要75天历史（含验证），不能用未来补齐')
    if end>frame.index[-1]+pd.Timedelta(hours=1):raise ValueError('评估日期超出数据范围')
    if (end-start).days>62:raise ValueError('单次回放上限62天')
    fixed=frame.index.tz is None and frame.index[0]==pd.Timestamp('2018-01-01') and frame.index[-1]==pd.Timestamp('2018-12-31 23:00')
    reference=fixed and start>=pd.Timestamp('2018-12-01')
    boundaries=list(pd.date_range('2018-09-01','2018-12-01',freq='MS')) if reference else [start-pd.Timedelta(days=d) for d in (21,14,7,0)]
    X=feature_matrix(frame);available=X.notna().all(axis=1)
    test=(frame.index>=start)&(frame.index<end)&available
    if test.sum()!=int((end-start).total_seconds()/3600):raise ValueError('回放区间数据不完整')
    names=['HistGradientBoosting','Daily naive','Weekly naive']
    t=time.perf_counter();failures=[];folds=[];ys=[];predictions=[[],[],[]];model=None
    for fold_start,fold_end in zip(boundaries,boundaries[1:]):
        train=(frame.index<fold_start)&available
        valid=(frame.index>=fold_start)&(frame.index<fold_end)&available
        if train.sum()<30*24 or valid.sum()!=int((fold_end-fold_start).total_seconds()/3600):raise ValueError('滚动验证历史不足或不完整')
        candidate=HistGradientBoostingRegressor(**MODEL_PARAMETERS)
        failure=None
        try:
            with threadpool_limits(limits=1):
                candidate.fit(X.loc[train],frame.load_kw.loc[train]);ph=np.maximum(0,candidate.predict(X.loc[valid]))
            model=candidate
        except Exception as error:
            failure=f'{type(error).__name__}: {error}';failures.append(failure);model=None;ph=X.loc[valid,'lag_168h'].to_numpy()
        vp=[ph,X.loc[valid,'lag_24h'].to_numpy(),X.loc[valid,'lag_168h'].to_numpy()]
        y=frame.load_kw.loc[valid].to_numpy();ys.append(y)
        for i,p in enumerate(vp):predictions[i].append(p)
        folds.append({'start':str(fold_start),'end':str(fold_end-pd.Timedelta(hours=1)),'train_end':str(frame.index[train][-1]),'train_rows':int(train.sum()),'models':[metrics(y,p,n) for p,n in zip(vp,names)],'failure':failure})
    yvalid=np.concatenate(ys);vp=[np.concatenate(p) for p in predictions]
    vm=[metrics(yvalid,p,n) for p,n in zip(vp,names)]
    best,reason,policy=select_model(vm,folds,bool(failures))
    if model is not None:
        with threadpool_limits(limits=1):ptest=np.maximum(0,model.predict(X.loc[test]))
    else:ptest=X.loc[test,'lag_168h'].to_numpy()
    tp=[ptest,X.loc[test,'lag_24h'].to_numpy(),X.loc[test,'lag_168h'].to_numpy()]
    tm=[metrics(frame.load_kw.loc[test],p,n) for p,n in zip(tp,names)]
    chosen=tp[best];q=float(np.quantile(np.abs(yvalid-vp[best]),.9))
    overprediction=np.maximum(0,vp[best]-yvalid);risk_q=float(np.quantile(overprediction,.75))
    out=frame.loc[test].copy();out['forecast_kw']=chosen;out['hgb_kw']=ptest;out['daily_naive_kw']=tp[1];out['weekly_naive_kw']=tp[2]
    out['lower_kw']=np.maximum(0,chosen-q);out['upper_kw']=chosen+q
    w=tm[2]['wape_pct'];h=tm[0]['wape_pct']
    report={'models':tm,'validation':vm,'rolling_validation':folds,'selected_model':names[best],'selection_reason':reason,'selection_policy':policy,
        'protocol_id':PROTOCOL_ID,'improvement_vs_weekly_pct':((w-h)/w*100 if w else None),'train_end':folds[-1]['train_end'],'train_rows':folds[-1]['train_rows'],
        'validation_period':[str(boundaries[0]),str(boundaries[-1]-pd.Timedelta(hours=1))],'holdout_period':[str(start),str(end-pd.Timedelta(hours=1))],
        'evaluation_role':'historical_regression' if reference else 'exploratory_subperiod','new_independent_generalization_evidence':False,
        'features':FEATURES,'training_seconds':time.perf_counter()-t,'fallback_error':'; '.join(failures) if failures else None,'hgb_available':not failures,
        'risk_calibration':{'quantile':.75,'positive_overprediction_q75_kw':risk_q,'cap_fraction':.35,'sample_count':len(yvalid),'period_end':str(boundaries[-1]-pd.Timedelta(hours=1)),'method':'max(prediction - observed, 0) on rolling development validation only'},
        'interval_method':'Rolling development absolute residual q90; empirical, no coverage guarantee',
        'interval_coverage_pct':float(np.mean((out.load_kw>=out.lower_kw)&(out.load_kw<=out.upper_kw))*100),
        'notes':['Fixed model and selection thresholds, zero tuning budget; final HGB trained before last validation window.','Daily origins use only completed prior days; no future reactive power/CO2/Load_Type.','December 2018 was already disclosed: historical regression only, not a new blind test.','Hourly source-local replay; unknown source timezone is not invented.','L1 preserves explicit HGB comparison even when B2 falls back.']}
    return out,report
