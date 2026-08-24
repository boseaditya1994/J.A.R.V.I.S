"""The ToolSpec shape shared by every tool module.

Lives in its own module (not registry.py) so that filesystem.py, shell.py,
and registry.py can all depend on it without a circular import — registry.py
aggregates tool instances defined in the other modules.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from jarvis.core.permissions import Risk


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict
    risk: Risk
    handler: Callable[[dict], str] | None
    # Optional hard-boundary check (e.g. shell_execute's allowlist), run
    # BEFORE confirmation is ever requested — a call that fails validation
    # is rejected outright, not just declined, so the human is never asked
    # to approve something that was never going to run. Raises ValueError.
    validate: Callable[[dict], None] | None = None
