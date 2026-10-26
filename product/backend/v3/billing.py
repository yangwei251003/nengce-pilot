"""Independent arithmetic for interval energy and whole-calendar-month demand."""
import numpy as np
import pandas as pd


def local_index(index, metadata):
    """UTC-naive sources retain UTC storage; tariffs follow declared local calendar."""
    zone = metadata.get('billing_timezone') or metadata.get('timezone')
    if metadata.get('time_axis') == 'UTC' and zone and zone not in ('unknown', 'source-local-unknown', 'source-local'):
        try:
            return index.tz_localize('UTC').tz_convert(zone) if index.tz is None else index.tz_convert(zone)
        except (ValueError, TypeError, KeyError) as exc:
            raise ValueError('来源时区无法解析，不能静默套用另一计费日历') from exc
    return index


def price_vector(index, tariff, stress='none'):
    if tariff.prices:
        slots = index.hour if len(tariff.prices) == 24 else index.hour * 4 + index.minute // 15
        p = np.asarray(tariff.prices, dtype=float)[slots]
    else:
        p = np.array([tariff.peak if h in tariff.peak_hours else tariff.offpeak if h in tariff.offpeak_hours else tariff.flat for h in index.hour], dtype=float)
    if stress == 'peak_price_up_20':
        p[np.isin(index.hour, tariff.peak_hours)] *= 1.2
    return p


def monthly_bills(index, rows, dt, demand_rate, observed=None, time_basis='source-local-unknown', source_eligible=True):
    """Never annualize a partial month or turn hourly peaks into 15-minute demand.

    A disabled demand rate is a no-demand illustrative contract. If demand is
    requested but the month is incomplete, its total bill is deliberately null.
    """
    observed = np.ones(len(index), dtype=bool) if observed is None else np.asarray(observed, dtype=bool)
    periods = index.strftime('%Y-%m')
    bills = []
    for month in dict.fromkeys(periods):
        mask = periods == month
        positions = np.flatnonzero(mask)
        idx = index[mask]
        first = pd.Timestamp(month + '-01', tz=index.tz)
        end = first + pd.offsets.MonthBegin(1)
        expected = pd.date_range(first, end, freq=pd.Timedelta(hours=dt), inclusive='left')
        complete = len(idx) == len(expected) and idx.equals(expected) and bool(observed[mask].all())
        selected = [rows[i] for i in positions]
        energy = sum(r['energy_cost'] for r in selected)
        degradation = sum(r['degradation_cost'] for r in selected)
        peak = max(r['grid_kw'] for r in selected)
        if demand_rate == 0:
            demand = 0.0
            status = 'disabled_by_contract'
        elif abs(dt - .25) > 1e-9:
            demand = None
            status = 'ineligible_hourly_resolution'
        elif not source_eligible:
            demand = None
            status = 'ineligible_source_boundary'
        elif not complete:
            demand = None
            status = 'ineligible_incomplete_or_imputed_month'
        else:
            demand = peak * demand_rate
            status = 'illustrative_complete_15min_month'
        bills.append({'month': month, 'observed_intervals': len(idx), 'expected_intervals': len(expected),
                      'complete_observed_month': bool(complete), 'peak_grid_kw': float(peak),
                      'energy_cost': float(energy), 'demand_cost': demand,
                      'degradation_cost': float(degradation), 'utility_bill': None if demand is None else float(energy + demand),
                      'total_cost': None if demand is None else float(energy + demand + degradation),
                      'demand_status': status, 'demand_rate_per_kw': demand_rate, 'time_basis': time_basis,
                      'billing_identity': 'illustrative', 'actual_contract_verified': False})
    return bills
