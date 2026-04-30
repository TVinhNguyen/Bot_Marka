"""Pydantic models that describe and validate the application config.

The schema is intentionally narrow: only the settings actually consumed by the
dry_run skeleton, baseline forecast, and risk gate are validated here. Sections
described in the design docs but not yet implemented (model adapters, agents,
monitoring side-effects beyond audit) are accepted as opaque dictionaries so
that future slices can deepen them without breaking older configs.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Mode = Literal["dry_run", "demo", "live"]
StorageBackend = Literal["jsonl", "duckdb", "parquet", "postgres"]
Timeframe = Literal["M1", "M5", "M15", "M30", "H1", "H4", "D1"]


class EnvironmentConfig(BaseModel):
    """Top-level environment selection."""

    model_config = ConfigDict(extra="forbid")

    mode: Mode
    timezone: str = "UTC"
    log_level: str = "INFO"

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, value: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = value.upper()
        if upper not in allowed:
            raise ValueError(f"log_level must be one of {sorted(allowed)}, got {value!r}")
        return upper


class SymbolTimeframe(BaseModel):
    """A symbol-timeframe pair the system is allowed to trade."""

    model_config = ConfigDict(extra="forbid")

    symbol: str = Field(min_length=1)
    timeframe: Timeframe
    enabled: bool = True
    spread_max_points: int = Field(default=50, gt=0)


class StorageConfig(BaseModel):
    """Where bars, forecasts, and audit records are persisted."""

    model_config = ConfigDict(extra="forbid")

    backend: StorageBackend = "jsonl"
    bars_path: str = Field(default="data/bars", min_length=1)
    forecasts_path: str = Field(default="data/predictions", min_length=1)
    audit_path: str = Field(default="audit", min_length=1)


class DataQualityConfig(BaseModel):
    """Tunable thresholds for the market-data quality gates (issue #6)."""

    model_config = ConfigDict(extra="forbid")

    gap_tolerance: float = Field(default=0.1, ge=0.0, le=1.0)
    return_outlier_mad_multiple: float = Field(default=8.0, gt=0.0)
    return_outlier_min_samples: int = Field(default=20, ge=2)
    stale_after_bars: float = Field(default=1.0, gt=0.0)
    expired_after_bars: float = Field(default=2.0, gt=0.0)
    block_tick_on_expired: bool = True
    spread_max_points: dict[str, int] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _stale_before_expired(self) -> DataQualityConfig:
        if self.stale_after_bars > self.expired_after_bars:
            raise ValueError("stale_after_bars must be <= expired_after_bars")
        return self


class RiskConfig(BaseModel):
    """Hard risk limits enforced by the Risk Decision gate."""

    model_config = ConfigDict(extra="forbid")

    base_risk_per_trade: float = Field(gt=0.0, le=0.05)
    max_risk_per_trade: float = Field(gt=0.0, le=0.05)
    min_risk_per_trade: float = Field(gt=0.0, le=0.05)
    max_daily_loss: float = Field(gt=0.0, le=0.5)
    max_total_drawdown: float = Field(gt=0.0, le=0.5)
    max_positions_per_symbol: int = Field(ge=1)
    max_total_positions: int = Field(ge=1)
    max_trades_per_day: int = Field(ge=1)
    max_consecutive_losses: int = Field(ge=1)

    sl_atr_min: float = Field(gt=0.0)
    sl_atr_max: float = Field(gt=0.0)
    tp_atr: float = Field(gt=0.0)
    rr_min: float = Field(gt=0.0)
    margin_safety: float = Field(gt=0.0, le=1.0)

    spread_max_points: dict[str, int] = Field(default_factory=dict)
    news_window_minutes: dict[str, list[int]] = Field(default_factory=dict)

    kill_switch_file: str = "/var/run/ai-mt5/STOP"
    kill_switch_enabled: bool = True

    @model_validator(mode="after")
    def _check_relative_limits(self) -> RiskConfig:
        if self.min_risk_per_trade > self.base_risk_per_trade:
            raise ValueError("min_risk_per_trade must be <= base_risk_per_trade")
        if self.base_risk_per_trade > self.max_risk_per_trade:
            raise ValueError("base_risk_per_trade must be <= max_risk_per_trade")
        if self.sl_atr_min > self.sl_atr_max:
            raise ValueError("sl_atr_min must be <= sl_atr_max")
        return self


class ExecutionConfig(BaseModel):
    """Settings for broker request shaping. Live order_send is gated by mode."""

    model_config = ConfigDict(extra="forbid")

    dry_run: bool = True
    deviation_points: int = Field(default=20, ge=0)
    magic: int = Field(gt=0)
    order_comment: str = Field(min_length=1, max_length=31)
    reconcile_on_start: bool = True


class AppConfig(BaseModel):
    """Validated, fully-typed application config."""

    model_config = ConfigDict(extra="forbid")

    environment: EnvironmentConfig
    symbols: list[SymbolTimeframe] = Field(min_length=1)
    storage: StorageConfig
    risk: RiskConfig
    execution: ExecutionConfig
    data_quality: DataQualityConfig = Field(default_factory=lambda: DataQualityConfig())

    @model_validator(mode="after")
    def _at_least_one_enabled_symbol(self) -> AppConfig:
        if not any(s.enabled for s in self.symbols):
            raise ValueError("at least one symbol-timeframe must be enabled")
        return self

    @model_validator(mode="after")
    def _live_mode_requires_explicit_dry_run_off(self) -> AppConfig:
        # Defense in depth: dry_run mode must keep execution.dry_run = True.
        if self.environment.mode == "dry_run" and not self.execution.dry_run:
            raise ValueError("environment.mode=dry_run requires execution.dry_run=true")
        return self

    def primary_symbol(self) -> SymbolTimeframe:
        """Return the first enabled symbol-timeframe."""
        for sym in self.symbols:
            if sym.enabled:
                return sym
        raise ValueError("no enabled symbols (validator should have caught this)")
