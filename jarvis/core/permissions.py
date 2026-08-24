"""Tool risk levels and the confirmation gate.

The model's output alone never authorizes a risky operation (project brief,
Section 20) — this module is the single source of truth for which risk
levels require a human to confirm before a tool handler runs.
"""

from __future__ import annotations

from typing import Literal

Risk = Literal["low", "high", "critical"]


def needs_confirmation(risk: Risk) -> bool:
    return risk != "low"
