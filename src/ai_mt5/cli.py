"""Command-line entrypoint.

Currently exposes:

* ``ai-mt5 dry-run-tick`` -- run one dry_run tick. Either reads bars from a
  CSV fixture (smoke-test path) or replays from the local BarStore
  (``--from-store``); when both are supplied, the CSV is ingested into the
  store first (idempotent) and replay then reads from the store.
* ``ai-mt5 store-health`` -- print a JSON snapshot of the local BarStore
  for one symbol-timeframe (bar count, earliest/latest open_time,
  last_modified, freshness state).

Both commands share the same logging configuration as the runtime tick.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import click

from .audit.trail import JsonlAuditTrail
from .backtest import (
    BacktestConfig,
    BacktestRunSpec,
    CostModel,
    run_backtest,
)
from .config import ConfigError, load_config
from .data import BarStore, load_closed_bars_csv
from .observability import build_health, build_period_report
from .risk.kill_switch import FileKillSwitch
from .tick import TickRunner
from .utils.logging_setup import configure_logging


@click.group()
def cli() -> None:
    """AI MT5 multi-model trading system CLI."""


@cli.command("dry-run-tick")
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=True, path_type=Path),
    default=Path("config/config.yaml"),
    show_default=True,
    help="Path to the YAML config.",
)
@click.option(
    "--bars",
    "bars_path",
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="Path to a Closed Bar CSV fixture. Required unless --from-store is set.",
)
@click.option(
    "--from-store",
    "from_store",
    is_flag=True,
    default=False,
    help=(
        "Replay from the local BarStore instead of the CSV fixture. "
        "If --bars is also supplied, ingest the CSV into the store first."
    ),
)
def dry_run_tick(config_path: Path, bars_path: Path | None, from_store: bool) -> None:
    """Run a single dry_run tick against fixture data or store replay."""
    if not from_store and bars_path is None:
        click.echo("error: --bars is required unless --from-store is set", err=True)
        sys.exit(2)

    try:
        cfg = load_config(config_path)
    except ConfigError as exc:
        click.echo(f"config error: {exc}", err=True)
        sys.exit(2)

    configure_logging(cfg.environment.log_level)

    runner = TickRunner(cfg)
    result = runner.run(bar_fixture_path=bars_path, from_store=from_store)

    summary = {
        "trace_id": result.trace_id,
        "status": result.status,
        "source": "store" if from_store else "fixture",
        "symbol": result.symbol,
        "timeframe": result.timeframe,
        "decision_time": result.decision_time,
        "forecast_direction": result.forecast.direction if result.forecast else None,
        "risk_approved": (result.risk_decision.approved if result.risk_decision else None),
        "rejected_by": (list(result.risk_decision.rejected_by) if result.risk_decision else []),
        "error": result.error,
    }
    click.echo(json.dumps(summary, sort_keys=True))
    if result.status == "failure":
        sys.exit(1)


@cli.command("store-health")
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=True, path_type=Path),
    default=Path("config/config.yaml"),
    show_default=True,
    help="Path to the YAML config.",
)
@click.option("--symbol", "symbol", default=None, help="Symbol; defaults to config primary.")
@click.option(
    "--timeframe", "timeframe", default=None, help="Timeframe; defaults to config primary."
)
def store_health(config_path: Path, symbol: str | None, timeframe: str | None) -> None:
    """Emit a JSON health snapshot of the local BarStore."""
    try:
        cfg = load_config(config_path)
    except ConfigError as exc:
        click.echo(f"config error: {exc}", err=True)
        sys.exit(2)

    configure_logging(cfg.environment.log_level)

    primary = cfg.primary_symbol()
    sym = symbol or primary.symbol
    tf = timeframe or primary.timeframe

    store = BarStore(cfg.storage.bars_path)
    health = store.health(
        symbol=sym,
        timeframe=tf,
        now=datetime.now(UTC),
        stale_after_bars=cfg.data_quality.stale_after_bars,
        expired_after_bars=cfg.data_quality.expired_after_bars,
    )
    click.echo(json.dumps(health.to_dict(), sort_keys=True))


@cli.command("backtest")
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=True, path_type=Path),
    default=Path("config/config.yaml"),
    show_default=True,
    help="Path to the YAML config.",
)
@click.option(
    "--bars",
    "bars_path",
    type=click.Path(exists=True, path_type=Path),
    required=True,
    help="Path to a Closed Bar CSV fixture used as the bar series.",
)
@click.option("--train", type=int, default=200, show_default=True, help="Bars per train range.")
@click.option(
    "--validation",
    type=int,
    default=100,
    show_default=True,
    help="Bars per validation range.",
)
@click.option("--oos", type=int, default=100, show_default=True, help="Bars per OOS range.")
@click.option(
    "--step",
    type=int,
    default=None,
    help="Bars between window starts (defaults to --oos: non-overlapping OOS).",
)
@click.option(
    "--initial-equity",
    type=float,
    default=10_000.0,
    show_default=True,
    help="Starting equity in deposit currency.",
)
@click.option("--seed", type=int, default=0, show_default=True, help="Reproducibility seed.")
@click.option("--spread-points", type=float, default=0.5, show_default=True)
@click.option("--commission-per-lot", type=float, default=0.0, show_default=True)
@click.option("--slippage-buffer-points", type=float, default=0.5, show_default=True)
@click.option(
    "--out",
    "out_path",
    type=click.Path(path_type=Path),
    default=Path("reports/backtest.json"),
    show_default=True,
    help="Where to write the JSON report.",
)
def backtest(
    config_path: Path,
    bars_path: Path,
    train: int,
    validation: int,
    oos: int,
    step: int | None,
    initial_equity: float,
    seed: int,
    spread_points: float,
    commission_per_lot: float,
    slippage_buffer_points: float,
    out_path: Path,
) -> None:
    """Run a walk-forward backtest and write a JSON report."""
    try:
        cfg = load_config(config_path)
    except ConfigError as exc:
        click.echo(f"config error: {exc}", err=True)
        sys.exit(2)

    configure_logging(cfg.environment.log_level)
    primary = cfg.primary_symbol()
    bars = load_closed_bars_csv(bars_path, symbol=primary.symbol, timeframe=primary.timeframe)
    if not bars:
        click.echo("error: bar fixture is empty", err=True)
        sys.exit(2)

    cost_model = CostModel(
        spread_points=spread_points,
        commission_per_lot=commission_per_lot,
        slippage_buffer_points=slippage_buffer_points,
    )
    bt_config = BacktestConfig(
        symbol=primary.symbol,
        timeframe=primary.timeframe,
        initial_equity=initial_equity,
        risk=cfg.risk,
        cost_model=cost_model,
        magic=cfg.execution.magic,
        order_comment=cfg.execution.order_comment,
    )
    spec = BacktestRunSpec(
        config=bt_config,
        train=train,
        validation=validation,
        oos=oos,
        step=step,
        seed=seed,
    )
    report = run_backtest(
        bars,
        spec=spec,
        config_for_manifest=cfg.model_dump(),
    )
    report.write_json(out_path)
    click.echo(
        json.dumps(
            {
                "out": str(out_path),
                "n_windows": len(report.windows),
                "manifest": report.manifest.to_dict(),
                "comparison": report.aggregate.get("comparison", {}),
            },
            sort_keys=True,
        )
    )


@cli.command("health")
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=True, path_type=Path),
    default=Path("config/config.yaml"),
    show_default=True,
    help="Path to the YAML config.",
)
def health(config_path: Path) -> None:
    """Emit a JSON health snapshot covering data freshness, kill switch, MT5 stub, and models."""
    try:
        cfg = load_config(config_path)
    except ConfigError as exc:
        click.echo(f"config error: {exc}", err=True)
        sys.exit(2)
    configure_logging(cfg.environment.log_level)

    bar_store = BarStore(cfg.storage.bars_path)
    audit = JsonlAuditTrail(Path(cfg.storage.audit_path) / "audit.jsonl")
    kill_switch = FileKillSwitch(cfg.risk.kill_switch_file)
    snapshot = build_health(
        config=cfg,
        bar_store=bar_store,
        audit=audit,
        kill_switch=kill_switch,
        now=datetime.now(UTC),
    )
    click.echo(json.dumps(snapshot.to_dict(), sort_keys=True))
    if snapshot.status.value == "unhealthy":
        sys.exit(1)


@cli.command("report")
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=True, path_type=Path),
    default=Path("config/config.yaml"),
    show_default=True,
    help="Path to the YAML config.",
)
@click.option(
    "--days",
    type=int,
    default=1,
    show_default=True,
    help="Window size in days, ending at 'now' (1 = daily, 7 = weekly).",
)
@click.option(
    "--format",
    "report_format",
    type=click.Choice(["json", "markdown"]),
    default="json",
    show_default=True,
)
@click.option(
    "--out",
    "out_path",
    type=click.Path(path_type=Path),
    default=None,
    help="Optional file to write the report to (otherwise stdout).",
)
def report(config_path: Path, days: int, report_format: str, out_path: Path | None) -> None:
    """Generate a daily/weekly operations report from the persisted audit trail."""
    try:
        cfg = load_config(config_path)
    except ConfigError as exc:
        click.echo(f"config error: {exc}", err=True)
        sys.exit(2)
    configure_logging(cfg.environment.log_level)

    audit = JsonlAuditTrail(Path(cfg.storage.audit_path) / "audit.jsonl")
    records = audit.read_all()
    now = datetime.now(UTC)
    window_start = now - timedelta(days=days)
    period_report = build_period_report(records, window_start=window_start, window_end=now)
    payload = (
        period_report.to_markdown()
        if report_format == "markdown"
        else json.dumps(period_report.to_dict(), sort_keys=True)
    )
    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(payload, encoding="utf-8")
        click.echo(json.dumps({"out": str(out_path), "format": report_format}, sort_keys=True))
    else:
        click.echo(payload)


@cli.command("mt5-preflight")
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=True, path_type=Path),
    default=Path("config/config.yaml"),
    show_default=True,
    help="Path to the YAML config.",
)
@click.option(
    "--bar-count",
    type=int,
    default=200,
    show_default=True,
    help="Number of closed bars to fetch from the broker for the quality check.",
)
@click.option(
    "--volume",
    "test_volume",
    type=float,
    default=0.01,
    show_default=True,
    help="Volume passed to order_check (NEVER to order_send). Use the smallest accepted lot.",
)
def mt5_preflight(config_path: Path, bar_count: int, test_volume: float) -> None:
    """Issue #3 — verify the live MT5 demo terminal can serve Closed Bars
    and accept a synthetic order_check."""
    try:
        cfg = load_config(config_path)
    except ConfigError as exc:
        click.echo(f"config error: {exc}", err=True)
        sys.exit(2)
    configure_logging(cfg.environment.log_level)
    from .mt5 import MT5BridgeConfig, MT5Client, MT5ConnectionError
    from .mt5.preflight import run_preflight

    bridge_cfg = MT5BridgeConfig.from_env()
    client = MT5Client(bridge_cfg)
    try:
        client.connect()
    except MT5ConnectionError as exc:
        click.echo(json.dumps({"ok": False, "failures": [f"bridge_error:{exc}"]}, sort_keys=True))
        sys.exit(1)
    try:
        report = run_preflight(
            client=client,
            config=cfg,
            now=datetime.now(UTC),
            bar_count=bar_count,
            test_volume=test_volume,
        )
    finally:
        client.disconnect()
    click.echo(json.dumps(report.to_dict(), sort_keys=True))
    if not report.ok:
        sys.exit(1)


def main() -> None:  # pragma: no cover -- thin wrapper
    cli()


if __name__ == "__main__":  # pragma: no cover
    main()
