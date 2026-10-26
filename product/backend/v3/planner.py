"""Audited interval MILP and realized-load execution protection.

The solver receives forecast vectors only; it cannot access source observations.
PV is behind the meter, export is zero and unused PV is explicitly curtailed.
"""
import time

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import lil_matrix


def solve_plan(load, pv, prices, battery, dt=1., initial_kwh=None, target_kwh=None,
               peak_so_far=0., demand_rate=0., discharge_limit=None, soft_margin=False,
               time_limit=5.):
    load, pv, prices = (np.asarray(v, dtype=float) for v in (load, pv, prices))
    if load.ndim != 1 or not len(load) or pv.shape != load.shape or prices.shape != load.shape:
        raise ValueError('负荷、光伏和价格必须是等长非空一维数组')
    if not all(np.isfinite(v).all() and (v >= 0).all() for v in (load, pv, prices)):
        raise ValueError('规划数组必须为有限非负值')
    b = battery
    low, high = b.capacity_kwh * b.min_soc, b.capacity_kwh * b.max_soc
    initial = b.capacity_kwh * b.initial_soc if initial_kwh is None else initial_kwh
    target = b.capacity_kwh * b.initial_soc if target_kwh is None else target_kwh
    if not np.isfinite([dt, initial, target, peak_so_far, demand_rate, time_limit]).all() or dt <= 0 or time_limit <= 0 or min(peak_so_far, demand_rate) < 0:
        raise ValueError('时间间隔、初末状态及计费参数无效')
    if not low - 1e-7 <= initial <= high + 1e-7 or not low - 1e-7 <= target <= high + 1e-7:
        raise ValueError('初末SOC必须在物理边界内')
    n = len(load)
    net = np.maximum(0, load - pv)
    limits = net if discharge_limit is None else np.asarray(discharge_limit, dtype=float)
    if limits.shape != net.shape or not np.isfinite(limits).all() or (limits < 0).any() or (limits > net + 1e-7).any():
        raise ValueError('余量放电上界必须位于0和预测净负荷之间')
    # c, d, E, binary charging mode, curtailment, grid, released margin, monthly peak
    size = 7 * n + 1
    obj = np.zeros(size)
    obj[:2*n] = dt * b.degradation_per_kwh
    obj[5*n:6*n] = dt * prices
    obj[-1] = demand_rate
    lower = np.zeros(size)
    upper = np.full(size, np.inf)
    upper[:2*n] = b.power_kw
    upper[n:2*n] = np.minimum(net, b.power_kw)
    lower[2*n:3*n], upper[2*n:3*n] = low, high
    lower[3*n-1] = upper[3*n-1] = target
    upper[3*n:4*n] = 1
    upper[4*n:5*n] = pv
    upper[5*n:6*n] = load + b.power_kw
    upper[6*n:7*n] = net - limits if soft_margin else 0
    lower[-1] = peak_so_far
    # Energy, binary mode, AC balance, monthly peak, discharge safety limit.
    A = lil_matrix((6*n, size)); lo = np.full(6*n, -np.inf); hi = np.zeros(6*n)
    for t in range(n):
        A[t, t] = -dt * b.charge_efficiency
        A[t, n+t] = dt / b.discharge_efficiency
        A[t, 2*n+t] = 1
        if t:
            A[t, 2*n+t-1] = -1
            lo[t] = hi[t] = 0
        else:
            lo[t] = hi[t] = initial
        A[n+t, t], A[n+t, 3*n+t] = 1, -b.power_kw
        A[2*n+t, n+t], A[2*n+t, 3*n+t] = 1, b.power_kw
        hi[2*n+t] = b.power_kw
        A[3*n+t, 5*n+t], A[3*n+t, t], A[3*n+t, n+t], A[3*n+t, 4*n+t] = 1, -1, 1, -1
        lo[3*n+t] = hi[3*n+t] = load[t] - pv[t]
        A[4*n+t, 5*n+t], A[4*n+t, -1] = 1, -1
        A[5*n+t, n+t], A[5*n+t, 6*n+t] = 1, -1
        hi[5*n+t] = limits[t]
    integrality = np.zeros(size); integrality[3*n:4*n] = 1
    before = time.perf_counter()
    matrix = A.tocsc()
    constraints = [LinearConstraint(matrix, lo, hi)]
    options = {'time_limit': time_limit, 'mip_rel_gap': 1e-7}
    # R2 uses lexicographic feasibility: release only the minimum AC margin needed
    # for the common terminal target, then optimize money at that same budget.
    minimum_relaxation = 0.
    if soft_margin:
        slack_obj = np.zeros(size); slack_obj[6*n:7*n] = dt
        preliminary = milp(slack_obj, integrality=integrality, bounds=Bounds(lower, upper), constraints=constraints, options=options)
        if preliminary.status != 0 or preliminary.x is None:
            return {'status': 'failed_margin_budget', 'feasible': False, 'optimal': False,
                    'elapsed_seconds': time.perf_counter()-before, 'mip_gap': None,
                    'message': '无法证明最小终端可达余量预算：' + str(preliminary.message)}
        minimum_relaxation = max(0., float(slack_obj @ preliminary.x))
        constraints.append(LinearConstraint(slack_obj[None, :], -np.inf, minimum_relaxation + 1e-7))
    result = milp(obj, integrality=integrality, bounds=Bounds(lower, upper), constraints=constraints, options=options)
    valid = False
    max_residual = None
    if result.x is not None:
        x = result.x; lhs = matrix @ x
        violations = np.r_[np.maximum(lo-lhs, 0), np.maximum(lhs-hi, 0), np.maximum(lower-x, 0), np.maximum(x-upper, 0), np.abs(x[3*n:4*n]-np.round(x[3*n:4*n]))]
        max_residual = float(violations.max())
        valid = max_residual <= 1e-5
        if soft_margin:
            valid = valid and float(np.sum(x[6*n:7*n]) * dt) <= minimum_relaxation + 1e-5
    status = {0:'optimal', 1:'feasible_time_limit', 2:'infeasible', 3:'unbounded', 4:'error'}.get(result.status, 'error')
    if not valid:
        status = 'infeasible' if result.status == 2 else 'failed_no_valid_incumbent'
    out = {'status': status, 'feasible': bool(valid), 'optimal': bool(valid and result.status == 0),
           'elapsed_seconds': time.perf_counter()-before, 'message': str(result.message),
           'mip_gap': float(result.mip_gap) if getattr(result, 'mip_gap', None) is not None else None,
           'independent_max_residual': max_residual, 'minimum_margin_relaxation_kwh': minimum_relaxation}
    if valid:
        c, d = np.maximum(x[:n], 0), np.maximum(x[n:2*n], 0)
        grid = np.maximum(x[5*n:6*n], 0)
        out.update(charge_kw=c, discharge_kw=d, soc_kwh=x[2*n:3*n], grid_kw=grid,
                   curtailment_kw=np.maximum(x[4*n:5*n], 0), margin_relaxation_kw=np.maximum(x[6*n:7*n], 0),
                   forecast_energy_cost=float(grid @ prices * dt),
                   forecast_demand_increment=float((x[-1]-peak_so_far) * demand_rate),
                   forecast_plan_cost=float(obj @ x - peak_so_far * demand_rate))
    return out


def solve_risk_plan(load, pv, prices, battery, limits, mode='R1', **kwargs):
    restricted = solve_plan(load, pv, prices, battery, discharge_limit=limits, **kwargs)
    if restricted['feasible']:
        restricted.update(margin_plan_failed=False, fallback_used=False, margin_plan_status=restricted['status'])
        return restricted
    fallback = solve_plan(load, pv, prices, battery,
                          discharge_limit=limits if mode == 'R2' else None,
                          soft_margin=mode == 'R2', **kwargs)
    fallback.update(margin_plan_failed=True, margin_plan_status=restricted['status'],
                    fallback_used=bool(fallback['feasible']), margin_failure_message=restricted['message'],
                    margin_attempt_elapsed_seconds=restricted['elapsed_seconds'],
                    fallback_kind='minimum_terminal_margin_release' if mode == 'R2' else 'unrestricted_original_physics')
    return fallback


def execute_step(actual, pv, charge, discharge, energy, battery, dt=1.):
    """Only this step sees the current realized interval; it never sees the future."""
    if not np.isfinite([actual, pv, charge, discharge, energy, dt]).all() or min(actual, pv, charge, discharge) < -1e-7 or dt <= 0:
        raise ValueError('执行输入必须有限且功率非负，间隔为正')
    if charge > 1e-7 and discharge > 1e-7:
        raise ValueError('同时充放电动作被拒绝')
    b = battery; low, high = b.capacity_kwh*b.min_soc, b.capacity_kwh*b.max_soc
    if not low-1e-6 <= energy <= high+1e-6:
        raise ValueError('执行初始SOC越界')
    charge, discharge = max(0., charge), max(0., discharge)
    cp, dp = min(charge, b.power_kw), min(discharge, b.power_kw)
    c = min(cp, max(0., (high-energy)/(b.charge_efficiency*dt)))
    ds = min(dp, max(0., (energy-low)*b.discharge_efficiency/dt))
    d = min(ds, max(0., actual-pv))
    next_energy = energy + (b.charge_efficiency*c-d/b.discharge_efficiency)*dt
    curtailment = max(0., pv + d - actual - c)
    grid = max(0., actual + c - d - pv + curtailment)
    return {'charge_kw': float(c), 'discharge_kw': float(d), 'soc_kwh': float(next_energy), 'grid_kw': float(grid),
            'curtailment_kw': float(curtailment), 'pv_self_consumed_kw': float(pv-curtailment),
            'clip_kwh': float((charge-c+discharge-d)*dt), 'clip_charge_kwh': float((charge-c)*dt),
            'clip_discharge_kwh': float((discharge-d)*dt), 'clip_power_kwh': float((charge-cp+discharge-dp)*dt),
            'clip_soc_kwh': float((cp-c+dp-ds)*dt), 'clip_no_export_kwh': float((ds-d)*dt),
            'balance_error_kwh': float(abs(next_energy-energy-(b.charge_efficiency*c-d/b.discharge_efficiency)*dt)),
            'ac_balance_error_kwh': float(abs(grid+pv+d-actual-c-curtailment)*dt),
            'soc_violation_kwh': float(max(0., low-next_energy, next_energy-high))}


def terminal_action(actual, pv, energy, target, battery, dt):
    """Common last-interval repair; inability to export is never relaxed."""
    if energy < target:
        return min(battery.power_kw, (target-energy)/(battery.charge_efficiency*dt)), 0.
    return 0., min(battery.power_kw, max(0., actual-pv), (energy-target)*battery.discharge_efficiency/dt)
