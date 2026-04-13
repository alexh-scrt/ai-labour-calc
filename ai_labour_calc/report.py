"""Report generation module for the AI Labour Impact Calculator.

This module provides functions to convert :class:`~ai_labour_calc.models.FullReport`
data into exportable formats:

* **CSV** — a pandas-backed flat file containing one row per scenario with
  all headline metrics, suitable for spreadsheet analysis.
* **PDF** — a WeasyPrint-rendered PDF built from the ``report_pdf.html``
  Jinja2 template, styled for print and download.

Typical usage::

    from ai_labour_calc.report import generate_csv_bytes, generate_pdf_bytes
    from ai_labour_calc.calculator import calculate_report
    from ai_labour_calc.models import RoleInput

    roles = [RoleInput("Data Entry", 100, 80.0)]
    report = calculate_report(roles, 55_000.0, "Acme Corp")

    csv_bytes = generate_csv_bytes(report)
    pdf_bytes = generate_pdf_bytes(report)

Both functions return raw :class:`bytes` that can be streamed directly as
Flask :class:`~flask.Response` objects.
"""

from __future__ import annotations

import io
import logging
import os
from datetime import datetime, timezone
from typing import List

import pandas as pd
from jinja2 import Environment, FileSystemLoader, select_autoescape
from weasyprint import HTML, CSS
from weasyprint.text.fonts import FontConfiguration

from ai_labour_calc.models import FullReport, ScenarioResult
from ai_labour_calc.assumptions import (
    CURRENCY_SYMBOL,
    CURRENCY_CODE,
    POLICY_FRAMEWORK_NAME,
    POLICY_FRAMEWORK_URL,
    REPORT_DISCLAIMER,
    PERCENTAGE_DECIMAL_PLACES,
    MONEY_DECIMAL_PLACES,
)

logger = logging.getLogger(__name__)

# Path to the templates directory (sibling of this file)
_TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")


# --------------------------------------------------------------------------- #
# CSV export                                                                   #
# --------------------------------------------------------------------------- #


def build_report_dataframe(report: FullReport) -> pd.DataFrame:
    """Convert a :class:`~ai_labour_calc.models.FullReport` into a pandas DataFrame.

    Each row in the returned DataFrame represents one automation scenario
    (optimistic, moderate, aggressive). Columns capture all headline metrics
    produced by the calculation engine.

    Args:
        report: A fully populated :class:`~ai_labour_calc.models.FullReport`
            instance as returned by
            :func:`~ai_labour_calc.calculator.calculate_report`.

    Returns:
        A :class:`pandas.DataFrame` with one row per scenario and the
        following columns:

        * ``organisation`` — organisation name
        * ``scenario`` — scenario display name
        * ``timeline_years`` — planning horizon in years
        * ``timeline_multiplier`` — scalar applied to automation potential
        * ``total_headcount`` — total workers across all roles
        * ``total_displaced`` — projected displaced worker count
        * ``total_remaining`` — projected remaining worker count
        * ``displacement_pct`` — displacement as a percentage (0–100)
        * ``avg_annual_salary_{CURRENCY_CODE}`` — baseline salary
        * ``robot_tax_liability_{CURRENCY_CODE}`` — estimated robot tax owed
        * ``retraining_cost_{CURRENCY_CODE}`` — total retraining programme cost
        * ``ubi_transfer_annual_{CURRENCY_CODE}`` — annual UBI transfer obligation
        * ``unemployment_insurance_cost_{CURRENCY_CODE}`` — total UI cost
        * ``total_safety_net_exposure_{CURRENCY_CODE}`` — combined safety-net
        * ``total_financial_exposure_{CURRENCY_CODE}`` — tax + safety-net combined

    Raises:
        TypeError: If ``report`` is not a :class:`~ai_labour_calc.models.FullReport`.

    Example::

        df = build_report_dataframe(report)
        assert len(df) == 3  # one row per scenario
        assert "scenario" in df.columns
    """
    if not isinstance(report, FullReport):
        raise TypeError(
            f"report must be a FullReport instance, got {type(report).__name__}."
        )

    rows: List[dict] = []
    for scenario in report.all_scenarios:
        rows.append(_scenario_to_row(report, scenario))

    df = pd.DataFrame(rows)
    return df


def _scenario_to_row(report: FullReport, scenario: ScenarioResult) -> dict:
    """Convert a single :class:`~ai_labour_calc.models.ScenarioResult` to a dict row.

    Args:
        report: Parent :class:`~ai_labour_calc.models.FullReport` for
            org name and salary metadata.
        scenario: The scenario to serialise.

    Returns:
        A flat dictionary suitable for inclusion in a pandas DataFrame row.
    """
    cc = CURRENCY_CODE
    return {
        "organisation": report.organisation_name,
        "scenario": scenario.scenario_name,
        "timeline_years": scenario.timeline_years,
        "timeline_multiplier": scenario.timeline_multiplier,
        "total_headcount": scenario.total_headcount,
        "total_displaced": scenario.total_displaced,
        "total_remaining": scenario.total_remaining,
        f"displacement_pct": round(scenario.displacement_percentage, PERCENTAGE_DECIMAL_PLACES),
        f"avg_annual_salary_{cc}": round(report.average_annual_salary, MONEY_DECIMAL_PLACES),
        f"robot_tax_liability_{cc}": round(scenario.robot_tax_liability, MONEY_DECIMAL_PLACES),
        f"retraining_cost_{cc}": round(scenario.retraining_cost, MONEY_DECIMAL_PLACES),
        f"ubi_transfer_annual_{cc}": round(scenario.ubi_transfer_annual, MONEY_DECIMAL_PLACES),
        f"unemployment_insurance_cost_{cc}": round(
            scenario.unemployment_insurance_cost, MONEY_DECIMAL_PLACES
        ),
        f"total_safety_net_exposure_{cc}": round(
            scenario.total_safety_net_exposure, MONEY_DECIMAL_PLACES
        ),
        f"total_financial_exposure_{cc}": round(
            scenario.total_financial_exposure, MONEY_DECIMAL_PLACES
        ),
    }


def build_role_breakdown_dataframe(report: FullReport) -> pd.DataFrame:
    """Build a detailed per-role, per-scenario displacement DataFrame.

    Each row represents one role's displacement figures within one scenario,
    giving a granular breakdown suitable for detailed analysis.

    Args:
        report: A fully populated :class:`~ai_labour_calc.models.FullReport`.

    Returns:
        A :class:`pandas.DataFrame` with columns:

        * ``organisation``
        * ``scenario``
        * ``role_name``
        * ``original_headcount``
        * ``displaced_workers``
        * ``remaining_workers``
        * ``displacement_rate`` — fractional rate (0.0–1.0)
        * ``displacement_pct`` — rate expressed as percentage

    Raises:
        TypeError: If ``report`` is not a :class:`~ai_labour_calc.models.FullReport`.
    """
    if not isinstance(report, FullReport):
        raise TypeError(
            f"report must be a FullReport instance, got {type(report).__name__}."
        )

    rows: List[dict] = []
    for scenario in report.all_scenarios:
        for rb in scenario.role_breakdowns:
            rows.append({
                "organisation": report.organisation_name,
                "scenario": scenario.scenario_name,
                "role_name": rb.role_name,
                "original_headcount": rb.original_headcount,
                "displaced_workers": rb.displaced_workers,
                "remaining_workers": rb.remaining_workers,
                "displacement_rate": round(rb.displacement_rate, 6),
                "displacement_pct": round(rb.displacement_rate * 100, PERCENTAGE_DECIMAL_PLACES),
            })

    return pd.DataFrame(rows)


def generate_csv_bytes(report: FullReport, include_role_breakdown: bool = True) -> bytes:
    """Serialise a :class:`~ai_labour_calc.models.FullReport` to CSV bytes.

    Produces a UTF-8 encoded CSV containing two sections separated by a
    blank line:

    1. **Scenario summary** — one row per scenario with all headline metrics.
    2. **Role breakdown** (optional) — per-role displacement detail rows
       across all three scenarios (included when
       ``include_role_breakdown=True``).

    Args:
        report: A fully populated :class:`~ai_labour_calc.models.FullReport`.
        include_role_breakdown: If ``True`` (default), append the per-role
            breakdown table after the scenario summary.

    Returns:
        UTF-8 encoded :class:`bytes` ready for streaming as a file download.

    Raises:
        TypeError: If ``report`` is not a :class:`~ai_labour_calc.models.FullReport`.

    Example::

        csv_bytes = generate_csv_bytes(report)
        with open("report.csv", "wb") as fh:
            fh.write(csv_bytes)
    """
    if not isinstance(report, FullReport):
        raise TypeError(
            f"report must be a FullReport instance, got {type(report).__name__}."
        )

    buf = io.StringIO()

    # -- Section 1: scenario summary ---------------------------------------- #
    summary_df = build_report_dataframe(report)
    buf.write("# AI Labour Impact Calculator — Scenario Summary\n")
    buf.write(f"# Organisation: {report.organisation_name}\n")
    buf.write(f"# Generated: {_utc_timestamp()}\n")
    buf.write(f"# Policy framework: {POLICY_FRAMEWORK_NAME}\n")
    buf.write(f"# {REPORT_DISCLAIMER}\n")
    buf.write("#\n")
    summary_df.to_csv(buf, index=False)

    if include_role_breakdown:
        role_df = build_role_breakdown_dataframe(report)
        if not role_df.empty:
            buf.write("\n")
            buf.write("# Role Breakdown\n")
            role_df.to_csv(buf, index=False)

    raw = buf.getvalue()
    logger.info(
        "CSV generated for '%s': %d bytes",
        report.organisation_name,
        len(raw),
    )
    return raw.encode("utf-8")


# --------------------------------------------------------------------------- #
# PDF export                                                                   #
# --------------------------------------------------------------------------- #


def render_pdf_html(report: FullReport) -> str:
    """Render the PDF report HTML string using the Jinja2 template engine.

    Loads ``report_pdf.html`` from the package ``templates/`` directory
    and renders it with the provided report data plus formatting helpers.

    Args:
        report: A fully populated :class:`~ai_labour_calc.models.FullReport`.

    Returns:
        A fully rendered HTML string ready to be passed to WeasyPrint.

    Raises:
        TypeError: If ``report`` is not a :class:`~ai_labour_calc.models.FullReport`.
        jinja2.TemplateNotFound: If ``report_pdf.html`` cannot be located.
    """
    if not isinstance(report, FullReport):
        raise TypeError(
            f"report must be a FullReport instance, got {type(report).__name__}."
        )

    env = Environment(
        loader=FileSystemLoader(_TEMPLATES_DIR),
        autoescape=select_autoescape(["html", "xml"]),
    )

    # Register formatting filters
    env.filters["money"] = _fmt_money
    env.filters["pct"] = _fmt_pct
    env.filters["intcomma"] = _fmt_intcomma

    template = env.get_template("report_pdf.html")

    context = {
        "report": report,
        "generated_at": _utc_timestamp(),
        "currency_symbol": CURRENCY_SYMBOL,
        "currency_code": CURRENCY_CODE,
        "policy_framework_name": POLICY_FRAMEWORK_NAME,
        "policy_framework_url": POLICY_FRAMEWORK_URL,
        "disclaimer": REPORT_DISCLAIMER,
        "scenarios": report.all_scenarios,
    }

    rendered = template.render(**context)
    logger.debug(
        "PDF HTML rendered for '%s': %d chars",
        report.organisation_name,
        len(rendered),
    )
    return rendered


def generate_pdf_bytes(report: FullReport) -> bytes:
    """Generate a styled PDF report as raw bytes.

    Renders the ``report_pdf.html`` Jinja2 template and passes the
    resulting HTML to WeasyPrint to produce a print-quality PDF document.

    Args:
        report: A fully populated :class:`~ai_labour_calc.models.FullReport`.

    Returns:
        Raw :class:`bytes` of the PDF document, ready for streaming as a
        file download with MIME type ``application/pdf``.

    Raises:
        TypeError: If ``report`` is not a :class:`~ai_labour_calc.models.FullReport`.
        OSError: If WeasyPrint cannot access required system fonts or
            libraries.

    Example::

        pdf_bytes = generate_pdf_bytes(report)
        with open("report.pdf", "wb") as fh:
            fh.write(pdf_bytes)
    """
    if not isinstance(report, FullReport):
        raise TypeError(
            f"report must be a FullReport instance, got {type(report).__name__}."
        )

    html_string = render_pdf_html(report)

    font_config = FontConfiguration()
    html_obj = HTML(string=html_string, base_url=_TEMPLATES_DIR)
    pdf_bytes: bytes = html_obj.write_pdf(font_config=font_config)

    logger.info(
        "PDF generated for '%s': %d bytes",
        report.organisation_name,
        len(pdf_bytes),
    )
    return pdf_bytes


# --------------------------------------------------------------------------- #
# Formatting helpers                                                           #
# --------------------------------------------------------------------------- #


def _fmt_money(value: float, symbol: str = CURRENCY_SYMBOL) -> str:
    """Format a numeric value as a currency string.

    Args:
        value: Numeric monetary value.
        symbol: Currency symbol prefix (defaults to
            :data:`~ai_labour_calc.assumptions.CURRENCY_SYMBOL`).

    Returns:
        Formatted string such as ``"$1,234,567.89"``.
    """
    try:
        return f"{symbol}{value:,.{MONEY_DECIMAL_PLACES}f}"
    except (TypeError, ValueError):
        return str(value)


def _fmt_pct(value: float) -> str:
    """Format a numeric value as a percentage string.

    Args:
        value: Percentage value (e.g. ``45.3`` for 45.3%).

    Returns:
        Formatted string such as ``"45.3%"``.
    """
    try:
        return f"{value:.{PERCENTAGE_DECIMAL_PLACES}f}%"
    except (TypeError, ValueError):
        return str(value)


def _fmt_intcomma(value: int) -> str:
    """Format an integer with thousands-separator commas.

    Args:
        value: Integer value to format.

    Returns:
        Formatted string such as ``"1,234,567"``.
    """
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return str(value)


def _utc_timestamp() -> str:
    """Return the current UTC time as an ISO-8601 formatted string.

    Returns:
        String in the format ``"2024-01-15 14:30:00 UTC"``.
    """
    now = datetime.now(tz=timezone.utc)
    return now.strftime("%Y-%m-%d %H:%M:%S UTC")
