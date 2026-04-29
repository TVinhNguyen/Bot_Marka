"""Command-line entrypoint.

Currently exposes a single command: ``ai-mt5 dry-run-tick`` which loads a
validated config, runs one dry_run tick against fixture bars, and prints a
machine-readable JSON summary to stdout while writing structured logs and
audit records to disk.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from .config import ConfigError, load_config
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
    required=True,
    help="Path to a Closed Bar CSV fixture.",
)
def dry_run_tick(config_path: Path, bars_path: Path) -> None:
    """Run a single dry_run tick against fixture data."""
    try:
        cfg = load_config(config_path)
    except ConfigError as exc:
        click.echo(f"config error: {exc}", err=True)
        sys.exit(2)

    configure_logging(cfg.environment.log_level)

    runner = TickRunner(cfg)
    result = runner.run(bar_fixture_path=bars_path)

    summary = {
        "trace_id": result.trace_id,
        "status": result.status,
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


def main() -> None:  # pragma: no cover -- thin wrapper
    cli()


if __name__ == "__main__":  # pragma: no cover
    main()
