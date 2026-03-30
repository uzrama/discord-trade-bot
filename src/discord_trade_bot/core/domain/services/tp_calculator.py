"""TP quantity calculation utilities."""

import logging
from typing import Any

logger = logging.getLogger(__name__)


def calculate_tp_quantities(
    total_qty: float,
    num_tps: int,
    tp_distributions: dict[int, list[dict[str, Any]]],
) -> list[float]:
    """
    Calculate quantity for each TP level based on configuration.

    Args:
        total_qty: Total position quantity to distribute
        num_tps: Number of TP levels in the signal
        tp_distributions: Dictionary mapping {num_tps: [distribution_config]}
                         where distribution_config contains 'label' and 'close_pct'

    Returns:
        List of quantities for each TP level

    Logic:
        - If exact match found in config → use configured percentages
        - If no match found → fallback to equal distribution
        - Auto-normalizes if percentages don't sum to 100%

    Examples:
        >>> config = {4: [{'label': 'tp1', 'close_pct': 40}, ...]}
        >>> calculate_tp_quantities(100.0, 4, config)
        [40.0, 30.0, 20.0, 10.0]

        >>> calculate_tp_quantities(100.0, 3, {})  # No config
        [33.33, 33.33, 33.33]
    """
    # Check if we have a config for this number of TPs
    if num_tps in tp_distributions:
        config = tp_distributions[num_tps]

        # Validation: check that number of entries matches
        if len(config) != num_tps:
            logger.warning(f"TP config mismatch: expected {num_tps} entries, got {len(config)}. Using equal distribution as fallback.")
            return [total_qty / num_tps] * num_tps

        # Validation: check sum of percentages
        total_pct = sum(tp.get("close_pct", 0) for tp in config)

        if abs(total_pct - 100) > 0.01:  # Allow small rounding errors
            logger.warning(f"TP percentages sum to {total_pct}%, not 100%. Auto-normalizing to 100%.")
            # Normalize percentages to sum to 100%
            normalized_config = [total_qty * (tp.get("close_pct", 0) / total_pct) for tp in config]
            return normalized_config

        # Calculate quantities from percentages
        quantities = [total_qty * (tp.get("close_pct", 0) / 100) for tp in config]

        percentages_str = [f"{tp.get('close_pct', 0)}%" for tp in config]
        logger.debug(f"Using configured TP distribution for {num_tps} TPs: {percentages_str}")

        return quantities

    else:
        # Fallback: equal distribution
        logger.info(f"No TP distribution config found for {num_tps} TPs. Using equal distribution ({100 / num_tps:.2f}% each).")
        return [total_qty / num_tps] * num_tps
