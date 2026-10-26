"""Public V3 configuration; no hidden pricing or physics defaults."""
from typing import Literal

import math
from pydantic import Field, model_validator

from ..config import Battery, Evaluation, RunConfig as V2RunConfig, Tariff as V2Tariff


class Tariff(V2Tariff):
    currency: Literal['CNY'] = 'CNY'
    prices: list[float] | None = None
    demand_per_kw: float = Field(0, ge=0, le=10000)
    billing_identity: Literal['illustrative'] = 'illustrative'

    @model_validator(mode='after')
    def interval_prices(self):
        if self.prices is not None:
            if len(self.prices) not in (24, 96):
                raise ValueError('自定义电价必须包含24个小时或96个15分钟价格')
            if any(not math.isfinite(p) or p < 0 or p > 100 for p in self.prices):
                raise ValueError('电价必须为0–100的有限非负数')
        return self


class RunConfig(V2RunConfig):
    dataset_id: str = 'uci-steel-15min'
    tariff: Tariff = Field(default_factory=Tariff)
    evaluation: Evaluation = Field(default_factory=lambda: Evaluation(start='2018-12-01', end='2018-12-01'))
    stress: Literal['none', 'load_up_20', 'peak_price_up_20', 'forecast_bias_up_20', 'pv_drop_30'] = 'none'
    protocol_id: str | None = Field(None, max_length=160)


Config = RunConfig
