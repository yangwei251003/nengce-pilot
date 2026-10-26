import time
import numpy as np
from scipy.optimize import milp, Bounds, LinearConstraint
from scipy.sparse import lil_matrix


def solve_plan(load,prices,battery,initial_kwh=None,target_kwh=None,time_limit=5.0,discharge_limit=None):
    """Hourly no-export single-battery MILP. Load passed explicitly; never accesses dataset."""
    load=np.asarray(load,dtype=float);prices=np.asarray(prices,dtype=float)
    if load.ndim!=1 or prices.shape!=load.shape or not load.size or not np.isfinite(load).all() or not np.isfinite(prices).all() or (load<0).any() or (prices<0).any():raise ValueError('规划输入必须是同长度一维有限非负负荷和电价')
    n=len(load)
    b=battery;cap=b.capacity_kwh; power=b.power_kw
    initial=cap*b.initial_soc if initial_kwh is None else initial_kwh
    target=cap*b.initial_soc if target_kwh is None else target_kwh
    low,high=cap*b.min_soc,cap*b.max_soc
    if not np.isfinite([initial,target,time_limit]).all() or time_limit<=0 or not low-1e-7<=initial<=high+1e-7 or not low-1e-7<=target<=high+1e-7:
        raise ValueError('初末电量必须在SOC范围内，时限必须有限且为正')
    limits=load if discharge_limit is None else np.asarray(discharge_limit,dtype=float)
    if limits.shape!=load.shape or not np.isfinite(limits).all() or (limits<0).any() or (limits>load+1e-7).any():
        raise ValueError('放电安全上界须与负荷等长、有限且位于零至预测负荷之间')
    # Variables: charge[n], discharge[n], next_energy[n], charging_mode_binary[n].
    obj=np.r_[prices+b.degradation_per_kwh,-prices+b.degradation_per_kwh,np.zeros(2*n)]
    lower=np.r_[np.zeros(2*n),np.full(n,low),np.zeros(n)]
    upper=np.r_[np.full(2*n,power),np.full(n,high),np.ones(n)]
    # Avoid redundant bounds for the original formulation: equivalent MILPs can
    # choose different cost-tied schedules, which then replay differently.
    if discharge_limit is not None:upper[n:2*n]=np.minimum(power,limits)
    lower[3*n-1]=upper[3*n-1]=target
    A=lil_matrix((4*n,4*n));lo=np.full(4*n,-np.inf);hi=np.zeros(4*n)
    for t in range(n):
        A[t,t]=-b.charge_efficiency;A[t,n+t]=1/b.discharge_efficiency;A[t,2*n+t]=1
        if t: A[t,2*n+t-1]=-1;lo[t]=hi[t]=0
        else:lo[t]=hi[t]=initial
        A[n+t,t]=1;A[n+t,3*n+t]=-power;hi[n+t]=0
        A[2*n+t,n+t]=1;A[2*n+t,3*n+t]=power;hi[2*n+t]=power
        A[3*n+t,n+t]=1;A[3*n+t,t]=-1;hi[3*n+t]=load[t]
    before=time.perf_counter()
    res=milp(obj,integrality=np.r_[np.zeros(3*n),np.ones(n)],bounds=Bounds(lower,upper),
        constraints=LinearConstraint(A.tocsc(),lo,hi),options={'time_limit':time_limit,'mip_rel_gap':1e-7})
    status={0:'optimal',1:'feasible_time_limit',2:'infeasible',3:'unbounded',4:'error'}.get(res.status,'error')
    valid=False
    if res.x is not None:
        lhs=A@res.x
        valid=bool(np.all(lhs>=lo-1e-5) and np.all(lhs<=hi+1e-5) and np.all(res.x>=lower-1e-5) and np.all(res.x<=upper+1e-5) and np.all(np.abs(res.x[3*n:]-np.round(res.x[3*n:]))<1e-5))
    if not valid:status='infeasible' if res.status==2 else 'failed_no_valid_incumbent'
    result={'status':status,'feasible':valid,'optimal':bool(res.status==0 and valid),
        'elapsed_seconds':time.perf_counter()-before,'message':str(res.message),
        'mip_gap':float(res.mip_gap) if getattr(res,'mip_gap',None) is not None else None}
    if valid:
        c=np.maximum(0,res.x[:n]);d=np.maximum(0,res.x[n:2*n]);e=res.x[2*n:3*n]
        result.update(charge_kw=c,discharge_kw=d,soc_kwh=e,grid_kw=np.maximum(0,load+c-d),
            forecast_plan_cost=float(np.dot(load+c-d,prices)+b.degradation_per_kwh*np.sum(c+d)))
    return result


def solve_risk_plan(load,prices,battery,discharge_limit,initial_kwh=None,target_kwh=None,time_limit=5.0):
    """Try the restrictive margin, then explicitly degrade at the SAME actual SOC.

    A successful fallback is physically feasible, but not a successful margin
    policy. Both statuses are preserved; if neither works no action is invented.
    """
    restricted=solve_plan(load,prices,battery,initial_kwh,target_kwh,time_limit,discharge_limit)
    if restricted['feasible']:
        restricted.update(margin_plan_status=restricted['status'],margin_plan_failed=False,fallback_used=False)
        return restricted
    fallback=solve_plan(load,prices,battery,initial_kwh,target_kwh,time_limit)
    fallback.update(margin_plan_status=restricted['status'],margin_plan_failed=True,fallback_used=bool(fallback['feasible']),
        margin_failure_message=restricted['message'],margin_attempt_elapsed_seconds=restricted['elapsed_seconds'])
    return fallback


def execute_step(actual,charge,discharge,energy,battery):
    """Safety simulation observes realized average load only AFTER chosen setpoint."""
    if not np.isfinite([actual,charge,discharge,energy]).all() or min(actual,charge,discharge)<-1e-7:
        raise ValueError('执行输入必须有限，负荷及动作必须非负')
    if charge>1e-7 and discharge>1e-7:raise ValueError('执行器收到同时充放电，拒绝')
    actual=max(0,float(actual));charge=max(0,float(charge));discharge=max(0,float(discharge))
    b=battery;low=b.capacity_kwh*b.min_soc;high=b.capacity_kwh*b.max_soc
    if not low-1e-6<=energy<=high+1e-6:raise ValueError('执行初始SOC越界')
    cp=min(charge,b.power_kw);dp=min(discharge,b.power_kw)
    c=min(cp,max(0,(high-energy)/b.charge_efficiency))
    ds=min(dp,max(0,(energy-low)*b.discharge_efficiency));d=min(ds,actual)
    next_energy=energy+b.charge_efficiency*c-d/b.discharge_efficiency
    grid=actual+c-d
    return {'charge_kw':c,'discharge_kw':d,'soc_kwh':next_energy,'grid_kw':grid,
        'clip_kwh':abs(c-charge)+abs(d-discharge),
        'clip_charge_kwh':charge-c,'clip_discharge_kwh':discharge-d,
        'clip_power_kwh':charge-cp+discharge-dp,'clip_soc_kwh':cp-c+dp-ds,
        'clip_no_export_kwh':ds-d,
        'balance_error_kwh':abs(next_energy-energy-b.charge_efficiency*c+d/b.discharge_efficiency),
        'soc_violation_kwh':max(0,low-next_energy,next_energy-high)}
