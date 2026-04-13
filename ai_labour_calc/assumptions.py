"""Centralised constants and policy parameters for the AI Labour Impact Calculator.

All assumptions, tax rate schedules, timeline multipliers, and safety-net
cost parameters are defined here as module-level constants. Adjusting
values in this module propagates changes throughout the entire application
without touching calculation logic.

Policy framework reference:
    Parameters are grounded in OpenAI's proposed industrial policy
    framework and publicly available estimates from labour economics
    literature. They are illustrative and should be adjusted to match
    the jurisdiction and scenario assumptions of the analyst.

Usage::

    from ai_labour_calc.assumptions import (
        SCENARIOS,
        ROBOT_TAX_RATE,
        RETRAINING_COST_PER_WORKER,
    )
"""

from __future__ import annotations

from typing import Dict, Any


# --------------------------------------------------------------------------- #
# Automation timeline scenarios                                                #
# --------------------------------------------------------------------------- #

#: Definition of the three automation timeline scenarios.
#:
#: Each entry is a dict with:
#:   - ``name`` (str): Display name used in templates and reports.
#:   - ``key`` (str): Short identifier used as a dict/attribute key
#:     (``"optimistic"``, ``"moderate"``, ``"aggressive"``).
#:   - ``multiplier`` (float): Scalar applied to a role's raw automation
#:     potential percentage to derive the effective displacement rate.
#:     A multiplier of 1.0 means the stated automation potential is
#:     realised in full; values < 1.0 reflect slower adoption curves.
#:   - ``timeline_years`` (int): Nominal planning horizon in years over
#:     which the automation is assumed to unfold.
#:   - ``description`` (str): Brief human-readable description for UI display.
SCENARIOS: list[Dict[str, Any]] = [
    {
        "name": "Optimistic",
        "key": "optimistic",
        "multiplier": 0.5,
        "timeline_years": 10,
        "description": (
            "Gradual, human-centred AI adoption over a decade. "
            "Strong regulation, retraining programmes, and augmentation "
            "rather than replacement dominate."
        ),
    },
    {
        "name": "Moderate",
        "key": "moderate",
        "multiplier": 1.0,
        "timeline_years": 7,
        "description": (
            "Mainstream adoption at market pace over seven years. "
            "Automation potential is realised as stated; policy "
            "interventions partially offset displacement."
        ),
    },
    {
        "name": "Aggressive",
        "key": "aggressive",
        "multiplier": 1.5,
        "timeline_years": 4,
        "description": (
            "Rapid, unconstrained automation over four years driven by "
            "competitive pressure and minimal regulatory friction. "
            "Displacement exceeds raw automation potential estimates."
        ),
    },
]

#: Lookup map from scenario key to scenario definition dict.
#: Provides O(1) access when a specific scenario config is needed.
SCENARIO_MAP: Dict[str, Dict[str, Any]] = {s["key"]: s for s in SCENARIOS}


# --------------------------------------------------------------------------- #
# Robot tax parameters                                                         #
# --------------------------------------------------------------------------- #

#: Base robot tax rate applied to the annual salary of each displaced worker.
#:
#: Derived from OpenAI's proposed framework which suggests taxing automation
#: gains at a rate comparable to employer payroll contributions (~10%).
#: Expressed as a decimal fraction (0.10 = 10%).
ROBOT_TAX_RATE: float = 0.10

#: Progressive tax rate tiers based on total displaced headcount.
#:
#: Each entry is a tuple of (displacement_threshold, marginal_rate) where
#: ``displacement_threshold`` is the *minimum* number of displaced workers
#: before that marginal rate applies, and ``marginal_rate`` is the
#: additional fractional rate on top of the base ``ROBOT_TAX_RATE``.
#:
#: Example: displacing 600 workers triggers the 0.03 surcharge on the
#: portion of displaced workers exceeding 500.
#:
#: Tiers (applied additively to ``ROBOT_TAX_RATE``):
#:   - < 50 displaced   : no surcharge (base rate only)
#:   - 50–249 displaced : +1% surcharge
#:   - 250–499 displaced: +2% surcharge
#:   - 500–999 displaced: +3% surcharge
#:   - ≥ 1000 displaced : +5% surcharge
ROBOT_TAX_PROGRESSIVE_TIERS: list[tuple[int, float]] = [
    (0, 0.00),    # 0–49:   no surcharge
    (50, 0.01),   # 50–249: +1%
    (250, 0.02),  # 250–499: +2%
    (500, 0.03),  # 500–999: +3%
    (1000, 0.05), # 1000+:  +5%
]


def get_robot_tax_rate(displaced_count: int) -> float:
    """Return the effective robot tax rate for a given displaced headcount.

    Applies the progressive surcharge tiers on top of the base
    ``ROBOT_TAX_RATE``. The surcharge is determined by which bracket
    the total ``displaced_count`` falls into (highest applicable tier wins).

    Args:
        displaced_count: Total number of displaced workers in the scenario.

    Returns:
        Effective fractional tax rate (e.g. 0.12 for 12%).

    Example::

        rate = get_robot_tax_rate(300)  # returns 0.12 (10% base + 2%)
    """
    surcharge: float = 0.0
    for threshold, rate in ROBOT_TAX_PROGRESSIVE_TIERS:
        if displaced_count >= threshold:
            surcharge = rate
        else:
            break
    return ROBOT_TAX_RATE + surcharge


# --------------------------------------------------------------------------- #
# Social safety-net cost parameters                                            #
# --------------------------------------------------------------------------- #

#: One-time retraining programme cost per displaced worker (USD).
#:
#: Based on estimates from the U.S. Trade Adjustment Assistance programme
#: and similar OECD retraining schemes. Covers course fees, materials,
#: and lost-income support during training.
RETRAINING_COST_PER_WORKER: float = 15_000.0

#: Monthly UBI-style transfer payment per displaced worker (USD/month).
#:
#: Reflects the OpenAI-aligned policy proposal of a ~$1,000/month
#: universal basic income supplement for workers displaced by automation.
UBI_MONTHLY_TRANSFER: float = 1_000.0

#: Annual UBI transfer per displaced worker, derived from monthly figure.
UBI_ANNUAL_TRANSFER: float = UBI_MONTHLY_TRANSFER * 12  # 12_000.0

#: Average unemployment insurance (UI) duration in months.
#:
#: U.S. federal maximum regular UI is 26 weeks; extended benefits can
#: reach 52 weeks. 6 months is the conventional planning assumption.
UI_DURATION_MONTHS: float = 6.0

#: Fraction of monthly salary paid as unemployment insurance benefit.
#:
#: Most U.S. state UI programmes replace 40–60% of prior wages;
#: 0.50 (50%) is the conventional midpoint assumption.
UI_REPLACEMENT_RATE: float = 0.50


def get_ui_cost_per_worker(annual_salary: float) -> float:
    """Calculate total unemployment insurance cost for a single displaced worker.

    Computes the expected UI payout as::

        monthly_salary * UI_REPLACEMENT_RATE * UI_DURATION_MONTHS

    Args:
        annual_salary: Annual salary of the worker in the analyst's
            chosen currency.

    Returns:
        Estimated total UI cost for one displaced worker.

    Example::

        cost = get_ui_cost_per_worker(60_000)  # returns 15_000.0
    """
    monthly_salary = annual_salary / 12.0
    return monthly_salary * UI_REPLACEMENT_RATE * UI_DURATION_MONTHS


# --------------------------------------------------------------------------- #
# Displacement rate ceiling                                                    #
# --------------------------------------------------------------------------- #

#: Maximum effective displacement rate for any single role (capped at 100%).
#:
#: Even in the aggressive scenario a role's displacement rate cannot
#: logically exceed 1.0 (all workers displaced). The calculation engine
#: uses this constant to cap the product of
#: ``automation_potential * timeline_multiplier``.
MAX_DISPLACEMENT_RATE: float = 1.0


# --------------------------------------------------------------------------- #
# Input validation boundaries                                                  #
# --------------------------------------------------------------------------- #

#: Minimum allowed value for average annual salary (USD).
#: Prevents division-by-zero and nonsensical calculations.
MIN_ANNUAL_SALARY: float = 1_000.0

#: Maximum allowed value for average annual salary (USD).
#: Acts as a soft upper sanity-check in form validation.
MAX_ANNUAL_SALARY: float = 10_000_000.0

#: Maximum headcount per role.
#: Prevents absurdly large inputs that could cause performance issues.
MAX_ROLE_HEADCOUNT: int = 1_000_000

#: Maximum number of role categories a user may submit in one report.
MAX_ROLES: int = 50

#: Minimum number of role categories required to generate a report.
MIN_ROLES: int = 1


# --------------------------------------------------------------------------- #
# Report / display formatting                                                  #
# --------------------------------------------------------------------------- #

#: Currency symbol used throughout templates and PDF reports.
CURRENCY_SYMBOL: str = "$"

#: Currency code used in report metadata.
CURRENCY_CODE: str = "USD"

#: Number of decimal places shown for percentage values in reports.
PERCENTAGE_DECIMAL_PLACES: int = 1

#: Number of decimal places shown for monetary values in reports.
MONEY_DECIMAL_PLACES: int = 2


# --------------------------------------------------------------------------- #
# Policy framework attribution                                                 #
# --------------------------------------------------------------------------- #

#: Short attribution string for the policy framework underlying the model.
POLICY_FRAMEWORK_NAME: str = "OpenAI Industrial Policy Framework (2024)"

#: URL reference for the policy framework documentation.
POLICY_FRAMEWORK_URL: str = (
    "https://openai.com/global-affairs/economic-blueprint"
)

#: Brief disclaimer appended to all generated reports.
REPORT_DISCLAIMER: str = (
    "This report is generated for illustrative and planning purposes only. "
    "All figures are estimates based on configurable assumptions and should "
    "not be construed as legal, financial, or regulatory advice. "
    "Assumptions can be adjusted in ai_labour_calc/assumptions.py."
)
