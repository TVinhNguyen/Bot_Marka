"""Issue #11 — promotion checklist.

Before promoting a build to ``demo`` / ``staging`` / ``small_live``,
every gate in :func:`run_promotion_checks` MUST pass. The checks are
deliberately *small and explicit* so each one can be diagnosed in
isolation when a promotion is blocked:

1. ``config_valid`` — :class:`AppConfig` parses and validates.
2. ``mode_allowed`` — the configured mode matches the requested target.
3. ``small_live_constraints`` — when the target is ``small_live``,
   exactly one symbol-timeframe is enabled and the risk caps are
   inside the documented small-live envelope.
4. ``secrets_present`` — every required secret env var is set
   (non-empty). The list defaults to MT5 bridge variables and is
   user-extensible.
5. ``kill_switch_path`` — the kill-switch directory is writable so the
   operator can engage the switch without ``sudo`` on the live host.
6. ``audit_path_writable`` — the audit directory exists and is
   writable; we never want a live tick to fail because the audit JSONL
   could not be opened.
7. ``backtest_report_recent`` — there is a backtest report on disk
   no older than ``backtest_max_age_days`` (default 7).
8. ``commit_known`` — :func:`runtime_snapshot` resolved a real commit
   SHA; promoting an "unknown" build is an explicit gate failure.

Each check returns :class:`PromotionCheckOutcome` with a concrete
``detail`` string so the operator immediately sees why a gate failed.
The aggregate :class:`PromotionReport` is JSON-serialisable for CI.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from ai_mt5.config.models import AppConfig

from .modes import RuntimeMode, parse_mode
from .snapshot import RuntimeSnapshot, runtime_snapshot

# Documented envelope for small_live (issue #11): "Small Live defaults
# enforce one symbol-timeframe and reduced risk limits."
SMALL_LIVE_MAX_BASE_RISK_PCT = 0.005
SMALL_LIVE_MAX_DAILY_LOSS_PCT = 0.02
SMALL_LIVE_MAX_TOTAL_DRAWDOWN_PCT = 0.05
SMALL_LIVE_MAX_TRADES_PER_DAY = 5

DEFAULT_REQUIRED_SECRETS: tuple[str, ...] = (
    "MT5_BRIDGE_HOST",
    "MT5_BRIDGE_PORT",
    "MT5_DEMO_LOGIN",
    "MT5_DEMO_PASSWORD",
    "MT5_DEMO_SERVER",
)


@dataclass(frozen=True)
class PromotionCheckOutcome:
    """Result of a single named gate."""

    name: str
    passed: bool
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "passed": self.passed, "detail": self.detail}


@dataclass(frozen=True)
class PromotionReport:
    """Aggregate result of a promotion run."""

    target: RuntimeMode
    snapshot: RuntimeSnapshot
    checks: tuple[PromotionCheckOutcome, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return all(c.passed for c in self.checks)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "target": self.target.value,
            "snapshot": self.snapshot.to_dict(),
            "checks": [c.to_dict() for c in self.checks],
        }

    def failures(self) -> list[PromotionCheckOutcome]:
        return [c for c in self.checks if not c.passed]


def run_promotion_checks(
    *,
    config: AppConfig,
    target: RuntimeMode | str,
    required_secrets: tuple[str, ...] = DEFAULT_REQUIRED_SECRETS,
    backtest_reports_dir: Path | None = None,
    backtest_max_age_days: int = 7,
    now: datetime | None = None,
    env: dict[str, str] | None = None,
    repo_root: Path | None = None,
) -> PromotionReport:
    """Run the full promotion checklist for ``target``.

    Parameters
    ----------
    config:
        Validated AppConfig already loaded by the caller.
    target:
        The mode the operator wants to promote to.
    required_secrets:
        Env-var names that must be set (non-empty) on the live host.
    backtest_reports_dir:
        Directory holding ``*.json`` backtest manifests. Defaults to
        ``reports/`` under cwd; if missing, the gate fails.
    backtest_max_age_days:
        Reject promotion when the freshest backtest is older.
    now:
        Override for "now" in tests.
    env:
        Override for ``os.environ`` in tests.
    repo_root:
        Forwarded to :func:`runtime_snapshot`.
    """
    target_mode = parse_mode(target)
    snapshot = runtime_snapshot(config=config, repo_root=repo_root)
    env_map = dict(env) if env is not None else dict(os.environ)
    now_dt = now or datetime.now(tz=UTC)
    reports_dir = backtest_reports_dir or Path("reports")

    checks: list[PromotionCheckOutcome] = [
        _check_config_valid(config),
        _check_mode_allowed(config, target_mode),
        _check_small_live_constraints(config, target_mode),
        _check_secrets_present(env_map, required_secrets),
        _check_kill_switch_path(config),
        _check_audit_path_writable(config),
        _check_backtest_report_recent(reports_dir, now_dt, backtest_max_age_days),
        _check_commit_known(snapshot),
    ]
    return PromotionReport(target=target_mode, snapshot=snapshot, checks=tuple(checks))


# -- individual gates -----------------------------------------------------


def _check_config_valid(config: AppConfig) -> PromotionCheckOutcome:
    # The fact we got an AppConfig is itself proof Pydantic validated
    # it. We re-run model_validate to surface late-binding mistakes
    # (e.g. an in-place mutation by the caller).
    try:
        AppConfig.model_validate(config.model_dump())
    except Exception as exc:  # pragma: no cover — defensive.
        return PromotionCheckOutcome(
            name="config_valid", passed=False, detail=f"config rejected: {exc}"
        )
    return PromotionCheckOutcome(
        name="config_valid", passed=True, detail="AppConfig passes Pydantic validation"
    )


def _check_mode_allowed(config: AppConfig, target: RuntimeMode) -> PromotionCheckOutcome:
    cfg_mode = config.environment.mode
    if cfg_mode != target.value:
        return PromotionCheckOutcome(
            name="mode_allowed",
            passed=False,
            detail=(
                f"target={target.value} but environment.mode={cfg_mode!r}; "
                "promote with the matching config"
            ),
        )
    return PromotionCheckOutcome(
        name="mode_allowed",
        passed=True,
        detail=f"environment.mode={cfg_mode}",
    )


def _check_small_live_constraints(config: AppConfig, target: RuntimeMode) -> PromotionCheckOutcome:
    if target is not RuntimeMode.SMALL_LIVE:
        return PromotionCheckOutcome(
            name="small_live_constraints",
            passed=True,
            detail="not small_live target — skipped",
        )
    enabled = [s for s in config.symbols if s.enabled]
    if len(enabled) != 1:
        return PromotionCheckOutcome(
            name="small_live_constraints",
            passed=False,
            detail=(
                f"small_live requires exactly one enabled symbol, got {len(enabled)}: "
                f"{[s.symbol + '/' + s.timeframe for s in enabled]}"
            ),
        )
    risk = config.risk
    violations: list[str] = []
    if risk.base_risk_per_trade > SMALL_LIVE_MAX_BASE_RISK_PCT:
        violations.append(
            f"base_risk_per_trade={risk.base_risk_per_trade} > {SMALL_LIVE_MAX_BASE_RISK_PCT}"
        )
    if risk.max_daily_loss > SMALL_LIVE_MAX_DAILY_LOSS_PCT:
        violations.append(f"max_daily_loss={risk.max_daily_loss} > {SMALL_LIVE_MAX_DAILY_LOSS_PCT}")
    if risk.max_total_drawdown > SMALL_LIVE_MAX_TOTAL_DRAWDOWN_PCT:
        violations.append(
            f"max_total_drawdown={risk.max_total_drawdown} > {SMALL_LIVE_MAX_TOTAL_DRAWDOWN_PCT}"
        )
    if risk.max_trades_per_day > SMALL_LIVE_MAX_TRADES_PER_DAY:
        violations.append(
            f"max_trades_per_day={risk.max_trades_per_day} > {SMALL_LIVE_MAX_TRADES_PER_DAY}"
        )
    if violations:
        return PromotionCheckOutcome(
            name="small_live_constraints",
            passed=False,
            detail="; ".join(violations),
        )
    return PromotionCheckOutcome(
        name="small_live_constraints",
        passed=True,
        detail=(
            f"one enabled symbol ({enabled[0].symbol}/{enabled[0].timeframe}); "
            f"risk caps within small-live envelope"
        ),
    )


def _check_secrets_present(
    env_map: dict[str, str], required: tuple[str, ...]
) -> PromotionCheckOutcome:
    missing = [name for name in required if not env_map.get(name)]
    if missing:
        return PromotionCheckOutcome(
            name="secrets_present",
            passed=False,
            detail=f"missing or empty: {missing}",
        )
    return PromotionCheckOutcome(
        name="secrets_present",
        passed=True,
        detail=f"all {len(required)} required secrets are set",
    )


def _check_kill_switch_path(config: AppConfig) -> PromotionCheckOutcome:
    parent = Path(config.risk.kill_switch_file).parent
    if not parent.exists():
        return PromotionCheckOutcome(
            name="kill_switch_path",
            passed=False,
            detail=f"kill switch parent dir missing: {parent}",
        )
    if not os.access(parent, os.W_OK):
        return PromotionCheckOutcome(
            name="kill_switch_path",
            passed=False,
            detail=f"kill switch parent dir not writable: {parent}",
        )
    return PromotionCheckOutcome(
        name="kill_switch_path",
        passed=True,
        detail=f"{parent} is writable",
    )


def _check_audit_path_writable(config: AppConfig) -> PromotionCheckOutcome:
    audit_dir = Path(config.storage.audit_path)
    try:
        audit_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return PromotionCheckOutcome(
            name="audit_path_writable",
            passed=False,
            detail=f"cannot create {audit_dir}: {exc}",
        )
    if not os.access(audit_dir, os.W_OK):
        return PromotionCheckOutcome(
            name="audit_path_writable",
            passed=False,
            detail=f"{audit_dir} not writable",
        )
    return PromotionCheckOutcome(
        name="audit_path_writable",
        passed=True,
        detail=f"{audit_dir} is writable",
    )


def _check_backtest_report_recent(
    reports_dir: Path, now: datetime, max_age_days: int
) -> PromotionCheckOutcome:
    if not reports_dir.exists():
        return PromotionCheckOutcome(
            name="backtest_report_recent",
            passed=False,
            detail=f"backtest reports dir missing: {reports_dir}",
        )
    candidates = sorted(reports_dir.rglob("*.json"))
    if not candidates:
        return PromotionCheckOutcome(
            name="backtest_report_recent",
            passed=False,
            detail=f"no *.json reports under {reports_dir}",
        )
    freshest = max(candidates, key=lambda p: p.stat().st_mtime)
    age = now - datetime.fromtimestamp(freshest.stat().st_mtime, tz=UTC)
    if age > timedelta(days=max_age_days):
        return PromotionCheckOutcome(
            name="backtest_report_recent",
            passed=False,
            detail=(
                f"freshest backtest {freshest.name} is {age.days}d old (>{max_age_days}d limit)"
            ),
        )
    return PromotionCheckOutcome(
        name="backtest_report_recent",
        passed=True,
        detail=f"freshest report: {freshest.name} ({age.days}d old)",
    )


def _check_commit_known(snapshot: RuntimeSnapshot) -> PromotionCheckOutcome:
    if snapshot.commit == "unknown":
        return PromotionCheckOutcome(
            name="commit_known",
            passed=False,
            detail="git commit could not be resolved; refusing to promote",
        )
    return PromotionCheckOutcome(
        name="commit_known",
        passed=True,
        detail=f"commit={snapshot.commit[:12]}",
    )


__all__ = [
    "DEFAULT_REQUIRED_SECRETS",
    "SMALL_LIVE_MAX_BASE_RISK_PCT",
    "SMALL_LIVE_MAX_DAILY_LOSS_PCT",
    "SMALL_LIVE_MAX_TOTAL_DRAWDOWN_PCT",
    "SMALL_LIVE_MAX_TRADES_PER_DAY",
    "PromotionCheckOutcome",
    "PromotionReport",
    "run_promotion_checks",
]
