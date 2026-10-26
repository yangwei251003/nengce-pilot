from pydantic import BaseModel, Field, model_validator
from typing import Literal

class Battery(BaseModel):
    capacity_kwh: float = Field(100, gt=0, le=100000)
    power_kw: float = Field(40, gt=0, le=100000)
    min_soc: float = Field(.1, ge=0, lt=1)
    max_soc: float = Field(.9, gt=0, le=1)
    initial_soc: float = Field(.5, ge=0, le=1)
    charge_efficiency: float = Field(.95, gt=0, le=1)
    discharge_efficiency: float = Field(.95, gt=0, le=1)
    degradation_per_kwh: float = Field(.03, ge=0, le=100)
    @model_validator(mode='after')
    def consistency(self):
        if not self.min_soc <= self.initial_soc <= self.max_soc or self.min_soc >= self.max_soc:
            raise ValueError('SOC 必须满足 min_soc ≤ initial_soc ≤ max_soc，且上下界不同')
        return self

class Tariff(BaseModel):
    currency: str = 'CNY'
    offpeak: float = Field(.35, ge=0, le=100)
    flat: float = Field(.7, ge=0, le=100)
    peak: float = Field(1.15, ge=0, le=100)
    peak_hours: list[int] = [10,11,12,13,14,18,19,20]
    offpeak_hours: list[int] = [0,1,2,3,4,5,6,23]
    @model_validator(mode='after')
    def hours(self):
        if any(h not in range(24) for h in self.peak_hours+self.offpeak_hours):
            raise ValueError('电价时段须为0–23小时')
        if set(self.peak_hours)&set(self.offpeak_hours): raise ValueError('峰谷时段不能重叠')
        return self

class Evaluation(BaseModel):
    start: str = '2018-12-01'
    end: str = '2018-12-31'

class RunConfig(BaseModel):
    dataset_id: str = 'uci-steel-hourly'
    battery: Battery = Battery()
    tariff: Tariff = Tariff()
    evaluation: Evaluation = Evaluation()
    stress: Literal['none','load_up_20','peak_price_up_20','forecast_bias_up_20'] = 'none'
    risk_margin_scale: float = Field(1.0, ge=0, le=1)
    idempotency_key: str | None = Field(None,max_length=128)
