"""Core calculation engine for the AI Labour Impact Calculator.

This module implements the ``calculate_report`` function that drives all
scenario modelling. Given a list of :class:`~ai_labour_calc.models.RoleInput`
objects and an average annual salary, it produces a
:class:`~ai_labour_calc.models.FullReport` containing
:class:`~ai_labour_calc.models.ScenarioResult` instances for each of the
three automation timelines (optimistic, moderate, aggressive).

Calculation pipeline for each scenario
---------------------------------------
1. **Displacement** — Each role's effective displacement rate is computed as
   ``min(automation_potential / 100 * timeline_multiplier, MAX_DISPLACEMENT_RATE)``.
   Displaced worker count is ``floor(headcount * effective_rate)``.
2. **Robot tax liability** — Progressive tax rate (from
   :func:`~ai_labour_calc.assumptions.get_robot_tax_rate`) applied to
   ``total_displaced * average_annual_salary``.
3. **Safety-net exposure** —
   - Retraining cost: ``total_displaced * RETRAINING_COST_PER_WORKER``
   - UBI annual transfer: ``total_displaced * UBI_ANNUAL_TRANSFER``
   - UI cost: ``total_displaced * get_ui_cost_per_worker(average_annual_salary)``
   - Total safety-net = sum of the three items above.

Typical usage::

    from ai_labour_calc.calculator import calculate_report
    from ai_labour_calc.models import RoleInput

    roles = [
        RoleInput("Data Entry", 100, 80.0),
        RoleInput("Analysts",   50, 30.0),
    ]
    report = calculate_report(
        roles=roles,
        average_annual_salary=55_000.0,
        organisation_name="Acme Corp",
    )
    print(report.moderate.total_displaced)
"""

from __future__ import annotations

import math
import logging
from typing import List

from ai_labour_calc.assumptions import (
    SCENARIOS,
    MAX_DISPLACEMENT_RATE,
    RETRAINING_COST_PER_WORKER,
    UBI_ANNUAL_TRANSFER,
    MIN_ANNUAL_SALARY,
    MAX_ANNUAL_SALARY,
    MAX_ROLE_HEADCOUNT,
    MAX_ROLES,
    MIN_ROLES,
    get_robot_tax_rate,
    get_ui_cost_per_worker,
)
from ai_labour_calc.models import (
    RoleInput,
    RoleDisplacement,
    ScenarioResult,
    FullReport,
)

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Public API                                                                   #
# --------------------------------------------------------------------------- #


def calculate_report(
    roles: List[RoleInput],
    average_annual_salary: float,
    organisation_name: str = "Unknown Organisation",
) -> FullReport:
    """Compute a full three-scenario automation impact report.

    Validates all inputs, then runs the calculation pipeline for each of
    the three automation timeline scenarios defined in
    :data:`~ai_labour_calc.assumptions.SCENARIOS`, and assembles the
    results into a :class:`~ai_labour_calc.models.FullReport`.

    Args:
        roles: Non-empty list of :class:`~ai_labour_calc.models.RoleInput`
            objects describing each workforce segment.  Must contain at
            least :data:`~ai_labour_calc.assumptions.MIN_ROLES` entry and
            no more than :data:`~ai_labour_calc.assumptions.MAX_ROLES`
            entries.
        average_annual_salary: Baseline annual salary used for robot tax
            and safety-net calculations.  Must be within
            [:data:`~ai_labour_calc.assumptions.MIN_ANNUAL_SALARY`,
            :data:`~ai_labour_calc.assumptions.MAX_ANNUAL_SALARY`].
        organisation_name: Human-readable name of the submitting
            organisation, embedded in report headers.  Defaults to
            ``"Unknown Organisation"`` if omitted.

    Returns:
        A fully populated :class:`~ai_labour_calc.models.FullReport`
        containing scenario results for ``optimistic``, ``moderate``,
        and ``aggressive`` timelines.

    Raises:
        TypeError: If ``roles`` is not a list or contains non-
            :class:`~ai_labour_calc.models.RoleInput` items.
        ValueError: If input validation fails (wrong list length, salary
            out of range, or per-role headcount exceeding the maximum).

    Example::

        roles = [RoleInput("CS Agents", 200, 70.0)]
        report = calculate_report(roles, 45_000.0, "Globex Inc")
        assert report.aggressive.total_displaced >= report.optimistic.total_displaced
    """
    _validate_inputs(roles, average_annual_salary, organisation_name)

    scenario_results: dict[str, ScenarioResult] = {}
    for scenario_def in SCENARIOS:
        result = _calculate_scenario(
            scenario_def=scenario_def,
            roles=roles,
            average_annual_salary=average_annual_salary,
        )
        scenario_results[scenario_def["key"]] = result
        logger.debug(
            "Scenario '%s': displaced=%d, robot_tax=%.2f, safety_net=%.2f",
            scenario_def["name"],
            result.total_displaced,
            result.robot_tax_liability,
            result.total_safety_net_exposure,
        )

    report = FullReport(
        organisation_name=organisation_name,
        average_annual_salary=average_annual_salary,
        roles=list(roles),
        optimistic=scenario_results["optimistic"],
        moderate=scenario_results["moderate"],
        aggressive=scenario_results["aggressive"],
    )

    logger.info(
        "Report generated for '%s': headcount=%d, max_displaced=%d",
        organisation_name,
        report.total_headcount,
        report.max_displaced,
    )
    return report


# --------------------------------------------------------------------------- #
# Scenario-level calculation                                                   #
# --------------------------------------------------------------------------- #


def _calculate_scenario(
    scenario_def: dict,
    roles: List[RoleInput],
    average_annual_salary: float,
) -> ScenarioResult:
    """Run the full calculation pipeline for a single scenario.

    Args:
        scenario_def: One entry from
            :data:`~ai_labour_calc.assumptions.SCENARIOS`.
        roles: Validated list of :class:`~ai_labour_calc.models.RoleInput`.
        average_annual_salary: Validated average annual salary.

    Returns:
        A populated :class:`~ai_labour_calc.models.ScenarioResult`.
    """
    multiplier: float = scenario_def["multiplier"]
    timeline_years: int = scenario_def["timeline_years"]
    scenario_name: str = scenario_def["name"]

    # ------------------------------------------------------------------ #
    # Step 1 — per-role displacement                                      #
    # ------------------------------------------------------------------ #
    role_breakdowns: List[RoleDisplacement] = [
        _calculate_role_displacement(role, multiplier) for role in roles
    ]

    total_headcount: int = sum(rb.original_headcount for rb in role_breakdowns)
    total_displaced: int = sum(rb.displaced_workers for rb in role_breakdowns)
    total_remaining: int = total_headcount - total_displaced

    displacement_percentage: float = (
        (total_displaced / total_headcount * 100.0) if total_headcount > 0 else 0.0
    )

    # ------------------------------------------------------------------ #
    # Step 2 — robot tax liability                                        #
    # ------------------------------------------------------------------ #
    effective_tax_rate: float = get_robot_tax_rate(total_displaced)
    robot_tax_liability: float = _calculate_robot_tax(
        total_displaced=total_displaced,
        average_annual_salary=average_annual_salary,
        effective_tax_rate=effective_tax_rate,
    )

    # ------------------------------------------------------------------ #
    # Step 3 — social safety-net exposure                                 #
    # ------------------------------------------------------------------ #
    retraining_cost, ubi_transfer_annual, ui_cost = _calculate_safety_net(
        total_displaced=total_displaced,
        average_annual_salary=average_annual_salary,
    )
    total_safety_net_exposure: float = retraining_cost + ubi_transfer_annual + ui_cost

    return ScenarioResult(
        scenario_name=scenario_name,
        timeline_years=timeline_years,
        timeline_multiplier=multiplier,
        total_headcount=total_headcount,
        total_displaced=total_displaced,
        total_remaining=total_remaining,
        displacement_percentage=round(displacement_percentage, 4),
        robot_tax_liability=round(robot_tax_liability, 2),
        retraining_cost=round(retraining_cost, 2),
        ubi_transfer_annual=round(ubi_transfer_annual, 2),
        unemployment_insurance_cost=round(ui_cost, 2),
        total_safety_net_exposure=round(total_safety_net_exposure, 2),
        role_breakdowns=role_breakdowns,
    )


# --------------------------------------------------------------------------- #
# Per-role displacement                                                        #
# --------------------------------------------------------------------------- #


def _calculate_role_displacement(
    role: RoleInput,
    timeline_multiplier: float,
) -> RoleDisplacement:
    """Compute displacement figures for a single role in one scenario.

    The effective displacement rate is:

    .. code-block:: text

        effective_rate = min(automation_potential / 100 * multiplier, 1.0)

    Displaced workers are computed using
    :func:`math.floor` so that partial workers are never counted::

        displaced = floor(headcount * effective_rate)

    Args:
        role: The :class:`~ai_labour_calc.models.RoleInput` to process.
        timeline_multiplier: Scenario multiplier scalar.

    Returns:
        A :class:`~ai_labour_calc.models.RoleDisplacement` record.
    """
    raw_rate: float = (role.automation_potential / 100.0) * timeline_multiplier
    effective_rate: float = min(raw_rate, MAX_DISPLACEMENT_RATE)

    displaced_workers: int = math.floor(role.headcount * effective_rate)
    # Guard against floating-point overshoot after floor (should never happen
    # given the cap, but defensive programming is cheap)
    displaced_workers = min(displaced_workers, role.headcount)
    remaining_workers: int = role.headcount - displaced_workers

    return RoleDisplacement(
        role_name=role.role_name,
        original_headcount=role.headcount,
        displaced_workers=displaced_workers,
        remaining_workers=remaining_workers,
        displacement_rate=round(effective_rate, 6),
    )


# --------------------------------------------------------------------------- #
# Robot tax calculation                                                        #
# --------------------------------------------------------------------------- #


def _calculate_robot_tax(
    total_displaced: int,
    average_annual_salary: float,
    effective_tax_rate: float,
) -> float:
    """Calculate annual robot tax liability for an organisation.

    The liability is computed as::

        robot_tax = total_displaced * average_annual_salary * effective_tax_rate

    Args:
        total_displaced: Number of displaced workers in this scenario.
        average_annual_salary: Baseline annual salary per worker.
        effective_tax_rate: Progressive tax rate returned by
            :func:`~ai_labour_calc.assumptions.get_robot_tax_rate`.

    Returns:
        Robot tax liability as a float (same currency as salary input).
    """
    if total_displaced <= 0:
        return 0.0
    return total_displaced * average_annual_salary * effective_tax_rate


# --------------------------------------------------------------------------- #
# Safety-net calculation                                                       #
# --------------------------------------------------------------------------- #


def _calculate_safety_net(
    total_displaced: int,
    average_annual_salary: float,
) -> tuple[float, float, float]:
    """Calculate all three social safety-net cost components.

    Components:

    * **Retraining cost** — one-time programme cost per displaced worker
      (:data:`~ai_labour_calc.assumptions.RETRAINING_COST_PER_WORKER`).
    * **UBI annual transfer** — annual per-worker UBI-style payment
      (:data:`~ai_labour_calc.assumptions.UBI_ANNUAL_TRANSFER`).
    * **Unemployment insurance cost** — calculated via
      :func:`~ai_labour_calc.assumptions.get_ui_cost_per_worker`.

    Args:
        total_displaced: Number of displaced workers in this scenario.
        average_annual_salary: Baseline annual salary per worker used
            in the UI cost calculation.

    Returns:
        A 3-tuple of ``(retraining_cost, ubi_transfer_annual, ui_cost)``
        each as a float.
    """
    if total_displaced <= 0:
        return 0.0, 0.0, 0.0

    retraining_cost: float = total_displaced * RETRAINING_COST_PER_WORKER
    ubi_transfer_annual: float = total_displaced * UBI_ANNUAL_TRANSFER
    ui_cost_per_worker: float = get_ui_cost_per_worker(average_annual_salary)
    ui_cost: float = total_displaced * ui_cost_per_worker

    return retraining_cost, ubi_transfer_annual, ui_cost


# --------------------------------------------------------------------------- #
# Input validation                                                             #
# --------------------------------------------------------------------------- #


def _validate_inputs(
    roles: List[RoleInput],
    average_annual_salary: float,
    organisation_name: str,
) -> None:
    """Validate all inputs before running the calculation pipeline.

    Performs type checking and boundary validation on all supplied
    parameters.  Raises descriptive exceptions on the first violation
    found.

    Args:
        roles: Candidate list of :class:`~ai_labour_calc.models.RoleInput`.
        average_annual_salary: Candidate annual salary value.
        organisation_name: Candidate organisation name string.

    Raises:
        TypeError: If ``roles`` is not a list, or any element is not a
            :class:`~ai_labour_calc.models.RoleInput` instance.
        ValueError: If the role list length, salary, or any per-role
            headcount is outside permitted bounds.
    """
    # --- organisation name ------------------------------------------------- #
    if not isinstance(organisation_name, str):
        raise TypeError(
            f"organisation_name must be a string, got {type(organisation_name).__name__}."
        )

    # --- roles list type --------------------------------------------------- #
    if not isinstance(roles, list):
        raise TypeError(
            f"roles must be a list, got {type(roles).__name__}."
        )

    # --- roles list length ------------------------------------------------- #
    if len(roles) < MIN_ROLES:
        raise ValueError(
            f"At least {MIN_ROLES} role(s) required; received {len(roles)}."
        )
    if len(roles) > MAX_ROLES:
        raise ValueError(
            f"A maximum of {MAX_ROLES} roles is supported; received {len(roles)}."
        )

    # --- individual role types --------------------------------------------- #
    for idx, role in enumerate(roles):
        if not isinstance(role, RoleInput):
            raise TypeError(
                f"roles[{idx}] must be a RoleInput instance, "
                f"got {type(role).__name__}."
            )
        if role.headcount > MAX_ROLE_HEADCOUNT:
            raise ValueError(
                f"roles[{idx}] ('{role.role_name}') headcount {role.headcount} "
                f"exceeds the maximum of {MAX_ROLE_HEADCOUNT}."
            )

    # --- salary ------------------------------------------------------------ #
    if not isinstance(average_annual_salary, (int, float)):
        raise TypeError(
            f"average_annual_salary must be numeric, "
            f"got {type(average_annual_salary).__name__}."
        )
    if math.isnan(average_annual_salary) or math.isinf(average_annual_salary):
        raise ValueError(
            "average_annual_salary must be a finite number; "
            f"got {average_annual_salary}."
        )
    if average_annual_salary < MIN_ANNUAL_SALARY:
        raise ValueError(
            f"average_annual_salary must be at least {MIN_ANNUAL_SALARY:,.2f}; "
            f"got {average_annual_salary:,.2f}."
        )
    if average_annual_salary > MAX_ANNUAL_SALARY:
        raise ValueError(
            f"average_annual_salary must not exceed {MAX_ANNUAL_SALARY:,.2f}; "
            f"got {average_annual_salary:,.2f}."
        )
