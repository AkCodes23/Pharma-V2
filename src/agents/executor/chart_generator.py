"""
Pharma Agentic AI — Executor Agent: Chart Generator.

Creates visual artifacts for the executive report:
  - CAGR bar charts (market growth)
  - Patent Timeline Gantt charts
  - Trial Pipeline heatmaps
  - Safety score gauge charts

All charts are generated as base64-encoded PNGs for PDF embedding.
Uses matplotlib for reliable server-side rendering (no GUI needed).
"""

from __future__ import annotations

import base64
import io
import logging
from typing import Any

import matplotlib

matplotlib.use("Agg")  # Non-interactive backend for server-side rendering
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime

logger = logging.getLogger(__name__)

# Premium color palette
COLORS = {
    "primary": "#6366F1",     # Indigo
    "secondary": "#8B5CF6",   # Purple
    "success": "#10B981",     # Emerald
    "warning": "#F59E0B",     # Amber
    "danger": "#EF4444",      # Red
    "info": "#3B82F6",        # Blue
    "bg": "#0F172A",          # Dark slate
    "text": "#F8FAFC",        # Light
    "grid": "#1E293B",        # Grid lines
}


def _fig_to_base64(fig: plt.Figure) -> str:
    """Convert a matplotlib figure to base64 PNG string."""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight", facecolor=COLORS["bg"])
    buf.seek(0)
    b64 = base64.b64encode(buf.read()).decode("utf-8")
    plt.close(fig)
    return b64


def generate_revenue_chart(revenue_data: dict[str, Any]) -> str:
    """
    Generate a revenue trend bar chart.

    Args:
        revenue_data: Dict with 'annual_revenue' list of {year, revenue_usd}.

    Returns:
        Base64-encoded PNG string.
    """
    annual = revenue_data.get("annual_revenue", [])
    if not annual:
        return ""

    years = [str(r["year"]) for r in annual]
    revenues = [r["revenue_usd"] / 1e9 for r in annual]

    fig, ax = plt.subplots(figsize=(10, 5))
    fig.patch.set_facecolor(COLORS["bg"])
    ax.set_facecolor(COLORS["bg"])

    bars = ax.bar(years, revenues, color=COLORS["primary"], width=0.6, edgecolor=COLORS["secondary"], linewidth=1.5)

    # Highlight patent cliff impact
    for i, bar in enumerate(bars):
        if annual[i].get("note"):
            bar.set_color(COLORS["danger"])

    ax.set_xlabel("Year", color=COLORS["text"], fontsize=12)
    ax.set_ylabel("Revenue ($B)", color=COLORS["text"], fontsize=12)
    ax.set_title("Drug Revenue Trend", color=COLORS["text"], fontsize=14, fontweight="bold")
    ax.tick_params(colors=COLORS["text"])
    ax.grid(axis="y", alpha=0.2, color=COLORS["grid"])
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["bottom"].set_color(COLORS["grid"])
    ax.spines["left"].set_color(COLORS["grid"])

    # Value labels on bars
    for bar, rev in zip(bars, revenues):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 0.3,
            f"${rev:.1f}B",
            ha="center",
            color=COLORS["text"],
            fontsize=10,
        )

    return _fig_to_base64(fig)


def generate_patent_timeline(legal_findings: dict[str, Any]) -> str:
    """
    Generate a patent timeline Gantt chart.

    Args:
        legal_findings: Dict with 'blocking_patents' list.

    Returns:
        Base64-encoded PNG string.
    """
    patents = legal_findings.get("blocking_patents", [])
    regional = legal_findings.get("regional_patents", [])
    all_patents = patents + regional

    if not all_patents:
        return ""

    fig, ax = plt.subplots(figsize=(12, 4))
    fig.patch.set_facecolor(COLORS["bg"])
    ax.set_facecolor(COLORS["bg"])

    today = datetime.now()

    for i, patent in enumerate(all_patents):
        expiry_str = patent.get("expiry_date", patent.get("filing_date", "2028-01-01"))
        try:
            expiry = datetime.strptime(expiry_str, "%Y-%m-%d")
        except (ValueError, TypeError):
            expiry = datetime(2028, 1, 1)

        filing_str = patent.get("filing_date", "2008-01-01")
        try:
            filing = datetime.strptime(filing_str, "%Y-%m-%d")
        except (ValueError, TypeError):
            filing = datetime(2008, 1, 1)

        color = COLORS["danger"] if expiry > today else COLORS["success"]
        label = patent.get("patent_number", f"Patent {i + 1}")

        ax.barh(
            i,
            (expiry - filing).days,
            left=mdates.date2num(filing),
            height=0.5,
            color=color,
            alpha=0.8,
            label=label,
        )
        ax.text(
            mdates.date2num(expiry) + 30,
            i,
            f"{label}\n({expiry_str})",
            va="center",
            color=COLORS["text"],
            fontsize=8,
        )

    # Today line
    ax.axvline(x=mdates.date2num(today), color=COLORS["warning"], linestyle="--", label="Today", alpha=0.8)

    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.set_title("Patent Timeline", color=COLORS["text"], fontsize=14, fontweight="bold")
    ax.tick_params(colors=COLORS["text"])
    ax.set_yticks([])
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["bottom"].set_color(COLORS["grid"])
    ax.spines["left"].set_color(COLORS["grid"])

    return _fig_to_base64(fig)


def generate_safety_gauge(safety_data: dict[str, Any]) -> str:
    """
    Generate a safety risk gauge chart.

    Args:
        safety_data: Dict with 'safety_score' containing risk metrics.

    Returns:
        Base64-encoded PNG string.
    """
    score = safety_data.get("safety_score", {})
    if not score:
        return ""

    risk_level = score.get("risk_level", "LOW")
    serious_pct = score.get("serious_pct", 0)

    fig, ax = plt.subplots(figsize=(6, 4))
    fig.patch.set_facecolor(COLORS["bg"])
    ax.set_facecolor(COLORS["bg"])

    # Simple risk visualization
    risk_colors = {
        "LOW": COLORS["success"],
        "MEDIUM": COLORS["warning"],
        "HIGH": COLORS["danger"],
        "CRITICAL": "#DC2626",
    }
    color = risk_colors.get(risk_level, COLORS["info"])

    # Donut chart
    values = [serious_pct, 100 - serious_pct]
    colors = [color, COLORS["grid"]]
    wedges, _ = ax.pie(values, colors=colors, startangle=90, wedgeprops=dict(width=0.3))

    ax.text(0, 0, f"{risk_level}\n{serious_pct:.0f}%", ha="center", va="center",
            color=COLORS["text"], fontsize=16, fontweight="bold")

    ax.set_title("Safety Risk Assessment", color=COLORS["text"], fontsize=14, fontweight="bold", pad=20)

    return _fig_to_base64(fig)
