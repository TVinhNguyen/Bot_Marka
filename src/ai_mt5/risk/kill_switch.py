"""Manual kill switch.

Two implementations are provided:

* :class:`FileKillSwitch` -- engages whenever a sentinel file exists on disk
  (matches ``risk.kill_switch.manual_file`` in the design doc).
* :class:`InMemoryKillSwitch` -- for tests.

The kill switch is read at the start of every Risk evaluation. Once engaged,
every new Risk Decision is rejected until the operator explicitly clears it.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol


class KillSwitch(Protocol):
    def is_engaged(self) -> bool: ...


class FileKillSwitch:
    """Kill switch backed by the existence of a sentinel file."""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self._path = Path(path)

    def is_engaged(self) -> bool:
        return self._path.exists()

    def engage(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.touch()

    def clear(self) -> None:
        if self._path.exists():
            self._path.unlink()


class InMemoryKillSwitch:
    """Process-local kill switch (testing convenience)."""

    def __init__(self, *, engaged: bool = False) -> None:
        self._engaged = engaged

    def is_engaged(self) -> bool:
        return self._engaged

    def engage(self) -> None:
        self._engaged = True

    def clear(self) -> None:
        self._engaged = False
