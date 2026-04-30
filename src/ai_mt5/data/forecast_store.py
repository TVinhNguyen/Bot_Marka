"""Append-only Forecast persistence (JSONL).

Used by the Baseline (and future model adapters) to save predictions that
later slices (Ensemble, Meta-Signal, Backtest) can re-read deterministically.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path

from ..domain.forecast import Forecast


class JsonlForecastStore:
    """One forecast per line, JSON-encoded."""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.exists():
            self._path.touch()

    @property
    def path(self) -> Path:
        return self._path

    def append(self, forecast: Forecast) -> None:
        payload = asdict(forecast)
        payload["timestamp"] = forecast.timestamp.isoformat()
        with self._path.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(payload, sort_keys=True, default=str) + "\n")
            fp.flush()
            os.fsync(fp.fileno())

    def query(
        self,
        *,
        symbol: str | None = None,
        timeframe: str | None = None,
        model_name: str | None = None,
    ) -> list[dict[str, object]]:
        """Return raw dict records matching the filters."""
        out: list[dict[str, object]] = []
        with self._path.open("r", encoding="utf-8") as fp:
            for raw in fp:
                raw = raw.strip()
                if not raw:
                    continue
                rec = json.loads(raw)
                if symbol and rec.get("symbol") != symbol:
                    continue
                if timeframe and rec.get("timeframe") != timeframe:
                    continue
                if model_name and rec.get("model_name") != model_name:
                    continue
                out.append(rec)
        return out
