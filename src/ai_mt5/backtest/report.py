"""Reproducibility manifest and JSON report for a walk-forward run.

The acceptance criteria for issue #10 require every report to record the
exact provenance of the inputs and the run environment so a second run can
prove deterministic equivalence:

* commit SHA (or ``"unknown"`` when run outside git),
* config hash (sha256 of the loaded config dict, sorted keys),
* data snapshot hash (sha256 of the raw bar series, ISO + OHLCV),
* package lock hash (sha256 of ``uv.lock`` when present, else
  ``pyproject.toml``),
* deterministic seed (defaulting to 0),
* run timestamp.

The report itself stays a plain dict-of-dicts so it serialises with the
stdlib :mod:`json` module without extra glue.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from ..domain.bar import Bar
from ..utils.time_utils import to_iso, utcnow
from .engine import TradeRecord
from .metrics import BacktestMetrics


@dataclass(frozen=True)
class ReportManifest:
    """Everything needed to re-run a backtest deterministically."""

    commit: str
    config_hash: str
    data_snapshot_hash: str
    package_lock_hash: str
    seed: int
    run_timestamp: str
    n_bars: int
    symbol: str
    timeframe: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class WindowReport:
    """One window's worth of metrics + per-pipeline summary."""

    window_index: int
    train_start: int
    train_end: int
    validation_end: int
    oos_end: int
    pipelines: dict[str, dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BacktestReport:
    """Top-level report serialised to disk."""

    manifest: ReportManifest
    windows: list[WindowReport]
    aggregate: dict[str, dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "manifest": self.manifest.to_dict(),
            "windows": [w.to_dict() for w in self.windows],
            "aggregate": self.aggregate,
        }

    def write_json(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.to_dict(), sort_keys=True, indent=2, default=_json_fallback),
            encoding="utf-8",
        )


def build_manifest(
    *,
    config: dict[str, Any],
    bars: list[Bar],
    seed: int,
    repo_root: Path | None = None,
    now: datetime | None = None,
) -> ReportManifest:
    """Compute the manifest hashes for ``bars`` + ``config``.

    ``repo_root`` defaults to the working directory; the function tolerates
    a missing ``.git`` directory by returning ``commit='unknown'``.
    """
    if not bars:
        raise ValueError("manifest requires a non-empty bar list")
    root = repo_root or Path.cwd()
    config_hash = _sha256_json(config)
    data_hash = _hash_bars(bars)
    lock_hash = _hash_lock(root)
    commit = _resolve_commit(root)
    ts = to_iso(now or utcnow())
    return ReportManifest(
        commit=commit,
        config_hash=config_hash,
        data_snapshot_hash=data_hash,
        package_lock_hash=lock_hash,
        seed=seed,
        run_timestamp=ts,
        n_bars=len(bars),
        symbol=bars[0].symbol,
        timeframe=bars[0].timeframe,
    )


def summarise_pipeline(
    *,
    metrics: BacktestMetrics,
    trades: list[TradeRecord],
    decisions: int,
    rejections: int,
    veto_count: int,
    final_equity: float,
    initial_equity: float,
) -> dict[str, Any]:
    """Reduce per-pipeline state to a JSON-friendly dict."""
    return {
        "n_decisions": decisions,
        "n_rejections": rejections,
        "n_vetoes": veto_count,
        "final_equity": final_equity,
        "initial_equity": initial_equity,
        "metrics": {
            "n_trades": metrics.n_trades,
            "n_wins": metrics.n_wins,
            "n_losses": metrics.n_losses,
            "win_rate": metrics.win_rate,
            "gross_pnl": metrics.gross_pnl,
            "profit_factor": _safe_float(metrics.profit_factor),
            "max_drawdown": metrics.max_drawdown,
            "max_drawdown_pct": metrics.max_drawdown_pct,
            "sharpe": metrics.sharpe,
            "calmar": metrics.calmar,
            "avg_trade": metrics.avg_trade,
            "bars_per_year": metrics.bars_per_year,
        },
        "trades": [_trade_to_dict(t) for t in trades],
    }


def _trade_to_dict(t: TradeRecord) -> dict[str, Any]:
    fill = t.fill
    return {
        "side": fill.side,
        "volume": fill.volume,
        "entry_price": fill.entry_price,
        "exit_price": fill.exit_price,
        "sl": fill.sl,
        "tp": fill.tp,
        "open_time": fill.open_time,
        "close_time": fill.close_time,
        "open_idx": fill.open_idx,
        "close_idx": fill.close_idx,
        "bars_held": fill.bars_held,
        "nights_held": fill.nights_held,
        "exit_reason": fill.exit_reason,
        "gross_price_pnl": t.gross_price_pnl,
        "cost": t.cost,
        "net_pnl": t.net_pnl,
        "decision_idx": t.decision_idx,
        "decision_time": t.decision_time,
        "confidence": t.confidence,
        "agreement": t.agreement,
        "final_score": t.final_score,
    }


def _safe_float(value: float) -> float | str:
    """Convert ``inf`` to a string so the JSON stays RFC-8259 compliant."""
    import math

    if math.isinf(value):
        return "inf" if value > 0 else "-inf"
    if math.isnan(value):
        return "nan"
    return value


def _json_fallback(o: Any) -> Any:
    if isinstance(o, datetime):
        return to_iso(o)
    raise TypeError(f"Object of type {type(o).__name__} is not JSON serializable")


def _sha256_json(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, default=_json_fallback).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _hash_bars(bars: list[Bar]) -> str:
    h = hashlib.sha256()
    for b in bars:
        # ISO + OHLCV is enough to detect any meaningful change to the
        # input series. ``spread_points`` is folded in for completeness.
        line = (
            f"{b.symbol}|{b.timeframe}|{b.open_time.isoformat()}|"
            f"{b.open}|{b.high}|{b.low}|{b.close}|{b.volume}|{b.spread_points}"
        )
        h.update(line.encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()


def _hash_lock(repo_root: Path) -> str:
    for name in ("uv.lock", "pyproject.toml"):
        path = repo_root / name
        if path.exists():
            return hashlib.sha256(path.read_bytes()).hexdigest()
    return "unknown"


def _resolve_commit(repo_root: Path) -> str:
    if not (repo_root / ".git").exists():
        return "unknown"
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (subprocess.SubprocessError, FileNotFoundError):
        return "unknown"
    return out.stdout.strip() or "unknown"
