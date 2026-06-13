"""
Manufacturing-specific prompt templates for AI analysis.

Provides structured prompts for different analysis types:
  - Worktime analysis interpretation
  - Line balance recommendations
  - Anomaly detection explanation
  - Generic report generation

Each template injects relevant metrics and context data into
the prompt while managing context window size (target < 4K tokens).
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Maximum prompt content length (approximate token limit)
_MAX_CONTEXT_LENGTH = 4000


class PromptTemplate:
    """Base class for manufacturing analysis prompt templates."""

    def build(
        self,
        data: Optional[Dict[str, Any]] = None,
        max_length: int = _MAX_CONTEXT_LENGTH,
    ) -> str:
        """Build the complete prompt with data injection.

        Args:
            data: Context data to inject into the template.
            max_length: Maximum character length for the context section.

        Returns:
            Formatted prompt string ready for AI gateway.
        """
        raise NotImplementedError


class WorktimeAnalysisPrompt(PromptTemplate):
    """Prompt template for worktime analysis interpretation.

    Injects: therblig statistics, bottleneck processes, cycle time data.
    """

    SYSTEM_CONTEXT = (
        "You are a manufacturing worktime analysis expert. Analyze the provided "
        "therblig (motion element) data and provide actionable insights for "
        "improving workstation efficiency. Use MOD (Methods-Time Measurement) "
        "values (1 MOD = 0.129 seconds) when referencing time standards. "
        "Focus on ECRS principles: Eliminate, Combine, Rearrange, Simplify. "
        "请用中文回答。"
    )

    def build(
        self,
        data: Optional[Dict[str, Any]] = None,
        max_length: int = _MAX_CONTEXT_LENGTH,
    ) -> str:
        data = data or {}
        parts = []

        parts.append(f"Station: {data.get('station_id', 'Unknown')}")
        parts.append(f"Period: {data.get('period', 'Unknown')}")

        if "therblig_stats" in data:
            parts.append(f"\nTherblig Statistics:")
            stats = data["therblig_stats"]
            for element, values in stats.items():
                if isinstance(values, (int, float)):
                    parts.append(f"  - {element}: {values:.2f} MOD")
                elif isinstance(values, dict):
                    parts.append(f"  - {element}: count={values.get('count', 0)}, avg_mod={values.get('avg_mod', 0):.2f}")

        if "cycle_times" in data:
            parts.append(f"\nCycle Times:")
            ct = data["cycle_times"]
            if isinstance(ct, dict):
                parts.append(f"  - Average: {ct.get('avg', 0):.2f}s")
                parts.append(f"  - Min: {ct.get('min', 0):.2f}s")
                parts.append(f"  - Max: {ct.get('max', 0):.2f}s")
                parts.append(f"  - Std Dev: {ct.get('std', 0):.2f}s")

        if "bottleneck" in data:
            parts.append(f"\nIdentified Bottleneck: {data['bottleneck']}")

        if "kpi_data" in data:
            kpi_context = json.dumps(data["kpi_data"], ensure_ascii=False, indent=2)
            parts.append(f"\nKPI Data:\n{kpi_context}")

        context_str = "\n".join(parts)
        if len(context_str) > max_length:
            context_str = context_str[:max_length] + "\n[... data truncated ...]"

        return (
            f"{self.SYSTEM_CONTEXT}\n\n"
            f"{context_str}\n\n"
            f"Please analyze the above worktime data and provide:\n"
            f"1. Summary of key findings\n"
            f"2. Bottleneck identification with root cause\n"
            f"3. Therblig optimization suggestions\n"
            f"4. Expected improvement after applying ECRS principles\n"
            f"5. Priority-ranked action items"
        )


class LineBalancePrompt(PromptTemplate):
    """Prompt template for line balance analysis.

    Injects: station workload distribution, balance rate, ECR suggestions.
    """

    SYSTEM_CONTEXT = (
        "You are a production line balance optimization expert. Analyze "
        "workstation load distribution and provide specific recommendations "
        "for improving line balance rate. Target balance rate is above 85%. "
        "Apply ECRS (Eliminate, Combine, Rearrange, Simplify) methodology. "
        "请用中文回答。"
    )

    def build(
        self,
        data: Optional[Dict[str, Any]] = None,
        max_length: int = _MAX_CONTEXT_LENGTH,
    ) -> str:
        data = data or {}
        parts = []

        parts.append(f"Line: {data.get('line_id', 'Unknown')}")

        if "stations" in data:
            parts.append("\nStation Workloads:")
            for station in data["stations"]:
                name = station.get("name", station.get("station_id", "?"))
                load = station.get("load", station.get("workload", 0))
                time_val = station.get("cycle_time", station.get("time", 0))
                parts.append(f"  - {name}: load={load:.1%}, cycle_time={time_val:.2f}s")

        if "balance_rate" in data:
            parts.append(f"\nCurrent Balance Rate: {data['balance_rate']:.1%}")

        if "bottleneck_station" in data:
            parts.append(f"Bottleneck Station: {data['bottleneck_station']}")

        if "ecr_suggestions" in data:
            parts.append("\nExisting ECR Suggestions:")
            for suggestion in data["ecr_suggestions"]:
                parts.append(f"  - [{suggestion.get('type', '?')}] {suggestion.get('description', '')}")

        context_str = "\n".join(parts)
        if len(context_str) > max_length:
            context_str = context_str[:max_length] + "\n[... data truncated ...]"

        return (
            f"{self.SYSTEM_CONTEXT}\n\n"
            f"{context_str}\n\n"
            f"Please analyze the line balance data and provide:\n"
            f"1. Current balance rate assessment\n"
            f"2. Bottleneck identification and root cause\n"
            f"3. Workload redistribution plan\n"
            f"4. New ECRS recommendations\n"
            f"5. Expected balance rate after optimization"
        )


class AnomalyDetectionPrompt(PromptTemplate):
    """Prompt template for anomaly detection explanation.

    Injects: anomaly events, historical comparison, context.
    """

    SYSTEM_CONTEXT = (
        "You are a manufacturing quality and anomaly analysis expert. "
        "Explain detected anomalies in production data, identify potential "
        "root causes, and suggest corrective actions. "
        "请用中文回答。"
    )

    def build(
        self,
        data: Optional[Dict[str, Any]] = None,
        max_length: int = _MAX_CONTEXT_LENGTH,
    ) -> str:
        data = data or {}
        parts = []

        parts.append(f"Station: {data.get('station_id', 'Unknown')}")

        if "anomalies" in data:
            parts.append("\nDetected Anomalies:")
            for anomaly in data["anomalies"]:
                parts.append(
                    f"  - [{anomaly.get('type', '?')}] at {anomaly.get('timestamp', '?')}: "
                    f"{anomaly.get('description', '')}"
                )

        if "historical_comparison" in data:
            hc = data["historical_comparison"]
            parts.append(f"\nHistorical Context:")
            parts.append(f"  - Baseline avg cycle: {hc.get('baseline_avg', 0):.2f}s")
            parts.append(f"  - Current avg cycle: {hc.get('current_avg', 0):.2f}s")
            parts.append(f"  - Deviation: {hc.get('deviation', 0):.1%}")

        context_str = "\n".join(parts)
        if len(context_str) > max_length:
            context_str = context_str[:max_length] + "\n[... data truncated ...]"

        return (
            f"{self.SYSTEM_CONTEXT}\n\n"
            f"{context_str}\n\n"
            f"Please explain the anomalies and provide:\n"
            f"1. Likely root causes\n"
            f"2. Impact assessment\n"
            f"3. Corrective actions\n"
            f"4. Prevention recommendations"
        )


class TherbligOptimizationPrompt(PromptTemplate):
    """Prompt template for therblig (motion element) optimization.

    Uses ECRS (Eliminate, Combine, Rearrange, Simplify) framework
    to generate structured improvement suggestions based on therblig
    analysis data.
    """

    SYSTEM_CONTEXT = (
        "You are an Industrial Engineering (IE) expert specializing in "
        "motion study and work measurement. Analyze the provided therblig "
        "(motion element) data using the ECRS framework:\n"
        "- E (Eliminate): Remove non-value-adding motions entirely\n"
        "- C (Combine): Merge consecutive motions to reduce handoff waste\n"
        "- R (Rearrange): Reorder operations for better workflow\n"
        "- S (Simplify): Reduce complexity of required motions\n\n"
        "Use MOD (Methods-Time Measurement) values: 1 MOD = 0.129 seconds.\n"
        "Provide structured, actionable improvement suggestions with "
        "quantified MOD savings estimates. "
        "请用中文回答。"
    )

    def build(
        self,
        data: Optional[Dict[str, Any]] = None,
        max_length: int = _MAX_CONTEXT_LENGTH,
    ) -> str:
        data = data or {}
        parts = []

        parts.append(f"Station: {data.get('station_id', 'Unknown')}")
        parts.append(f"Period: {data.get('period', 'Unknown')}")

        # Therblig statistics
        if "therblig_stats" in data:
            stats = data["therblig_stats"]
            total_mod = 0.0
            waste_mod = 0.0

            parts.append("\nTherblig Distribution:")
            parts.append("  | Symbol | Name | Count | Total MOD | Waste |")
            parts.append("  |--------|------|-------|-----------|-------|")

            if isinstance(stats, list):
                # 数组格式：[{symbol, name, mod, actual, pct, isWaste}, ...]
                for item in stats:
                    element = item.get("name") or item.get("symbol", "?")
                    symbol = item.get("symbol", "?")
                    mod = float(item.get("mod", 0) or 0)
                    count = int(item.get("actual", 0) or 0)  # use actual as count approximation
                    is_waste = bool(item.get("isWaste", False))
                    waste_flag = "Yes" if is_waste else ""
                    total_mod += mod
                    if is_waste:
                        waste_mod += mod
                    parts.append(
                        f"  | {symbol} | {element} | {count} | {mod:.1f} | {waste_flag} |"
                    )
            else:
                # dict 格式：{name: {symbol, count, total_mod, is_waste}, ...}
                for element, values in stats.items():
                    if isinstance(values, dict):
                        count = values.get("count", 0)
                        mod = values.get("total_mod", 0.0)
                        is_waste = values.get("is_waste", False)
                        waste_flag = "Yes" if is_waste else ""
                        total_mod += mod
                        if is_waste:
                            waste_mod += mod
                        parts.append(
                            f"  | {values.get('symbol', '?')} | {element} | {count} | {mod:.1f} | {waste_flag} |"
                        )

            waste_ratio = waste_mod / total_mod if total_mod > 0 else 0
            parts.append(f"\n  Total MOD: {total_mod:.1f}")
            parts.append(f"  Waste MOD: {waste_mod:.1f} ({waste_ratio:.1%})")
            parts.append(f"  Effective MOD: {total_mod - waste_mod:.1f}")

        # MOD standard vs actual comparison
        if "mod_comparison" in data:
            comp = data["mod_comparison"]
            parts.append(f"\nMOD Standard vs Actual:")
            parts.append(f"  - Standard MOD (current method): {comp.get('actual_mod', 0):.1f}")
            parts.append(f"  - Target MOD (after optimization): {comp.get('target_mod', 0):.1f}")
            parts.append(f"  - Potential savings: {comp.get('savings_mod', 0):.1f} MOD")
            parts.append(f"  - Savings percentage: {comp.get('savings_pct', 0):.1%}")

        # Cycle time data
        if "cycle_times" in data:
            ct = data["cycle_times"]
            if isinstance(ct, dict):
                parts.append(f"\nCycle Time Data:")
                parts.append(f"  - Average: {ct.get('avg', 0):.2f}s")
                parts.append(f"  - Min: {ct.get('min', 0):.2f}s")
                parts.append(f"  - Max: {ct.get('max', 0):.2f}s")
                parts.append(f"  - Std Dev: {ct.get('std', 0):.2f}s")

        # Action classification summary
        if "action_summary" in data:
            parts.append(f"\nAction Classification Summary:")
            for action, info in data["action_summary"].items():
                if isinstance(info, dict):
                    parts.append(
                        f"  - {action}: {info.get('count', 0)} occurrences, "
                        f"avg {info.get('avg_duration_ms', 0):.0f}ms"
                    )

        context_str = "\n".join(parts)
        if len(context_str) > max_length:
            context_str = context_str[:max_length] + "\n[... data truncated ...]"

        return (
            f"{self.SYSTEM_CONTEXT}\n\n"
            f"{context_str}\n\n"
            f"Based on the above data, provide a structured ECRS analysis:\n"
            f"1. Summary of current therblig profile\n"
            f"2. ECRS improvement table with columns: "
            f"[Improvement Item, ECRS Type, Current MOD, Target MOD, "
            f"MOD Savings, Priority (1-3)]\n"
            f"3. Before vs After MOD comparison\n"
            f"4. Expected efficiency improvement percentage\n"
            f"5. Implementation priority ranking with reasoning\n"
            f"6. Risk assessment for each suggestion"
        )


# Template registry
TEMPLATES: Dict[str, PromptTemplate] = {
    "worktime": WorktimeAnalysisPrompt(),
    "line_balance": LineBalancePrompt(),
    "anomaly": AnomalyDetectionPrompt(),
    "therblig_optimization": TherbligOptimizationPrompt(),
}


def get_template(analysis_type: str) -> Optional[PromptTemplate]:
    """Get a prompt template by analysis type.

    Args:
        analysis_type: One of 'worktime', 'line_balance', 'anomaly',
                        'therblig_optimization'.

    Returns:
        PromptTemplate instance, or None if type not found.
    """
    return TEMPLATES.get(analysis_type)


def build_prompt(
    analysis_type: str,
    data: Optional[Dict[str, Any]] = None,
    max_length: int = _MAX_CONTEXT_LENGTH,
) -> Optional[str]:
    """Build a complete prompt using the appropriate template.

    Args:
        analysis_type: Analysis type key.
        data: Context data to inject.
        max_length: Maximum context length.

    Returns:
        Formatted prompt string, or None if template not found.
    """
    template = get_template(analysis_type)
    if template is None:
        return None
    return template.build(data, max_length)
