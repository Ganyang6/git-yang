"""
Therblig (motion element) mapper.

Maps classified action labels to standard Therblig symbols and MOD time
values.  The mapping is deterministic for the rule-based classifier and
can be refined when the ONNX model is introduced.

MOD (Modular Arrangement of Predetermined Time Standard) assigns a
time value to each motion element:
  - 1 MOD = 0.129 seconds
  - Finger movement: M1 (1 MOD)
  - Wrist movement: M2 (2 MOD)
  - Forearm movement: M3 (3 MOD)
  - Upper arm movement: M4 (4 MOD)
  - Shoulder movement: M5 (5 MOD)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from app.models.schemas import ActionLabel, TherbligSymbol


@dataclass
class TherbligMapping:
    """Maps an action to its Therblig symbol, name, and MOD value."""
    symbol: TherbligSymbol
    name: str
    mod_value: float  # in MOD units
    is_waste: bool = False  # non-value-adding element


# ── Action -> Therblig mapping table ─────────────────────────────────────

ACTION_TO_THERBLIG: Dict[ActionLabel, TherbligMapping] = {
    ActionLabel.REACH: TherbligMapping(
        symbol=TherbligSymbol.REACH,
        name="reach",
        mod_value=3.0,  # M3 forearm movement typical
        is_waste=False,
    ),
    ActionLabel.GRASP: TherbligMapping(
        symbol=TherbligSymbol.GRASP,
        name="grasp",
        mod_value=1.0,  # simple touch/grasp
        is_waste=False,
    ),
    ActionLabel.MOVE: TherbligMapping(
        symbol=TherbligSymbol.MOVE,
        name="move",
        mod_value=4.0,  # M4 upper arm typical for carrying
        is_waste=False,
    ),
    ActionLabel.ASSEMBLE: TherbligMapping(
        symbol=TherbligSymbol.ASSEMBLE,
        name="assemble",
        mod_value=5.0,  # complex positioning + insertion
        is_waste=False,
    ),
    ActionLabel.RELEASE: TherbligMapping(
        symbol=TherbligSymbol.RELEASE,
        name="release",
        mod_value=1.0,  # simple release
        is_waste=False,
    ),
    ActionLabel.INSPECT: TherbligMapping(
        symbol=TherbligSymbol.INSPECT,
        name="inspect",
        mod_value=3.0,  # visual inspection
        is_waste=False,
    ),
    ActionLabel.WAIT: TherbligMapping(
        symbol=TherbligSymbol.UNAVOIDABLE_DELAY,
        name="unavoidable_delay",
        mod_value=0.0,  # no predetermined time, measured actual
        is_waste=True,
    ),
    ActionLabel.IDLE: TherbligMapping(
        symbol=TherbligSymbol.AVOIDABLE_DELAY,
        name="avoidable_delay",
        mod_value=0.0,
        is_waste=True,
    ),
}


def map_action_to_therblig(action: ActionLabel) -> TherbligMapping:
    """
    Map a classified action to its Therblig equivalent.

    Args:
        action: Classified action label.

    Returns:
        TherbligMapping with symbol, name, MOD value, and waste flag.
    """
    return ACTION_TO_THERBLIG.get(
        action,
        TherbligMapping(
            symbol=TherbligSymbol.AVOIDABLE_DELAY,
            name="other",
            mod_value=0.0,
            is_waste=True,
        ),
    )


# One MOD unit in seconds (MOD = Modular Arrangement of Predetermined Time Standard)
MOD_TO_SECONDS: float = 0.129


def compute_standard_time(mappings: list) -> float:
    """
    Compute standard time in seconds from a list of Therblig mappings.

    Args:
        mappings: List of TherbligMapping objects.

    Returns:
        Standard time in seconds (MOD * 0.129).
    """
    total_mod = sum(m.mod_value for m in mappings)
    return total_mod * MOD_TO_SECONDS
