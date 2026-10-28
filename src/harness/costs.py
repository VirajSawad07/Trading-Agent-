"""Cost model built from per-symbol specs in config/symbols.yaml."""

from dataclasses import dataclass, replace

import yaml


@dataclass(frozen=True)
class CostModel:
    contract_size: float
    point: float
    min_lot: float
    lot_step: float
    max_lot: float
    spread_points: float
    slippage_points: float
    commission_per_lot: float
    swap_long_points: float
    swap_short_points: float
    triple_swap_weekday: int = 2

    # All costs below are in price units per 1 unit of the instrument (1 oz, 1 EUR),
    # so they can be compared directly with a stop distance.
    @property
    def spread(self) -> float:
        return self.spread_points * self.point

    @property
    def slippage(self) -> float:
        return self.slippage_points * self.point

    @property
    def commission(self) -> float:
        return self.commission_per_lot / self.contract_size

    def swap_per_night(self, direction: int) -> float:
        """Swap credit (+) or charge (-) per unit per night, in price units."""
        pts = self.swap_long_points if direction > 0 else self.swap_short_points
        return pts * self.point

    def scaled(self, factor: float) -> "CostModel":
        """Cost stress test: multiply spread, slippage, commission and swap charges."""
        return replace(
            self,
            spread_points=self.spread_points * factor,
            slippage_points=self.slippage_points * factor,
            commission_per_lot=self.commission_per_lot * factor,
            swap_long_points=self.swap_long_points * (factor if self.swap_long_points < 0 else 1),
            swap_short_points=self.swap_short_points * (factor if self.swap_short_points < 0 else 1),
        )


def load_cost_model(symbol: str, path: str = "config/symbols.yaml") -> CostModel:
    with open(path, "r") as f:
        specs = yaml.safe_load(f)
    if symbol not in specs:
        raise KeyError(f"No cost specs for {symbol} in {path}")
    return CostModel(**specs[symbol])
