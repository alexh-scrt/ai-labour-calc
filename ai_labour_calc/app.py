"""Flask routes and view functions for the AI Labour Impact Calculator.

This module defines all HTTP endpoints for the web application and provides
the ``register_routes`` function consumed by the application factory in
:mod:`ai_labour_calc.__init__`.

Routes
------
``GET  /``
    Render the input form (``index.html``).

``POST /calculate``
    Parse and validate form data, run the calculation engine, store the
    resulting :class:`~ai_labour_calc.models.FullReport` in the server-side
    session (serialised as JSON), and redirect to the results page.

``GET  /results``
    Render the results dashboard (``results.html``) using the report stored
    in the session.

``GET  /download/csv``
    Stream the CSV export of the current report as a file download.

``GET  /download/pdf``
    Stream the PDF report as a file download.

``GET  /health``
    Simple health-check endpoint returning ``{"status": "ok"}``.

Typical usage (via the Flask CLI)::

    flask --app ai_labour_calc run --debug

Or programmatically::

    from ai_labour_calc import create_app
    app = create_app()
    app.run(debug=True)
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict
from typing import Any, Dict, List, Optional, Tuple

from flask import (
    Flask,
    Response,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from ai_labour_calc.assumptions import (
    CURRENCY_SYMBOL,
    CURRENCY_CODE,
    MAX_ROLES,
    MIN_ROLES,
    MIN_ANNUAL_SALARY,
    MAX_ANNUAL_SALARY,
    MAX_ROLE_HEADCOUNT,
)
from ai_labour_calc.calculator import calculate_report
from ai_labour_calc.models import FullReport, RoleInput, RoleDisplacement, ScenarioResult
from ai_labour_calc.report import generate_csv_bytes, generate_pdf_bytes

logger = logging.getLogger(__name__)

# Session key used to persist report data between the POST /calculate
# redirect and the subsequent GET /results (and download) requests.
_SESSION_KEY = "report_data"

# Maximum byte size for the serialised report stored in the session.
# Flask's default cookie-based session has a 4 KB limit; we use a
# server-side approach by storing JSON in the session dict directly
# (compatible with Flask's signed-cookie session when the payload is
# reasonably small, or with server-side session backends).
_MAX_SESSION_PAYLOAD = 500_000  # 500 KB safety cap


# --------------------------------------------------------------------------- #
# Route registration                                                           #
# --------------------------------------------------------------------------- #


def register_routes(app: Flask) -> None:
    """Register all URL rules and view functions on *app*.

    This function is called once by :func:`~ai_labour_calc.create_app` after
    the Flask application object is configured.  Keeping route registration
    here (rather than using global ``@app.route`` decorators) avoids circular
    imports between the package ``__init__`` and this module.

    Args:
        app: The configured :class:`flask.Flask` application instance.
    """
    app.add_url_rule("/", endpoint="index", view_func=index, methods=["GET"])
    app.add_url_rule(
        "/calculate",
        endpoint="calculate",
        view_func=calculate,
        methods=["POST"],
    )
    app.add_url_rule(
        "/results",
        endpoint="results",
        view_func=results,
        methods=["GET"],
    )
    app.add_url_rule(
        "/download/csv",
        endpoint="download_csv",
        view_func=download_csv,
        methods=["GET"],
    )
    app.add_url_rule(
        "/download/pdf",
        endpoint="download_pdf",
        view_func=download_pdf,
        methods=["GET"],
    )
    app.add_url_rule(
        "/health",
        endpoint="health",
        view_func=health,
        methods=["GET"],
    )

    # Register the custom Jinja2 filter used in results.html
    app.jinja_env.filters["format_int"] = _filter_format_int

    logger.debug("Routes registered on Flask app '%s'", app.name)


# --------------------------------------------------------------------------- #
# View functions                                                               #
# --------------------------------------------------------------------------- #


def index() -> str:
    """Render the home page input form.

    On a fresh visit the form is empty.  If the session contains
    ``form_data`` (populated after a failed validation), the form fields
    are pre-populated so the user does not have to re-enter data.

    Returns:
        Rendered HTML string for ``index.html``.
    """
    # Retrieve any pre-fill data left by a failed POST (validation error)
    form_data: Optional[Dict[str, Any]] = session.pop("form_data", None)
    return render_template("index.html", form_data=form_data)


def calculate() -> Response:
    """Handle form submission, validate inputs, run calculations.

    Parses the multivalue form payload, constructs
    :class:`~ai_labour_calc.models.RoleInput` objects, calls
    :func:`~ai_labour_calc.calculator.calculate_report`, serialises the
    resulting :class:`~ai_labour_calc.models.FullReport` into the session,
    and redirects to ``/results``.

    On validation failure, flash messages are added and the user is
    redirected back to ``/`` with form data preserved in the session.

    Returns:
        A :class:`flask.Response` redirect to either ``/results`` (success)
        or ``/`` (validation failure).
    """
    # ------------------------------------------------------------------ #
    # 1. Extract raw form values                                          #
    # ------------------------------------------------------------------ #
    organisation_name: str = request.form.get("organisation_name", "").strip()
    salary_raw: str = request.form.get("average_annual_salary", "").strip()

    role_names: List[str] = request.form.getlist("role_name[]")
    headcounts: List[str] = request.form.getlist("headcount[]")
    automation_potentials: List[str] = request.form.getlist("automation_potential[]")

    # ------------------------------------------------------------------ #
    # 2. Validate top-level fields                                        #
    # ------------------------------------------------------------------ #
    errors: List[str] = []

    if not organisation_name:
        errors.append("Organisation name is required.")
    elif len(organisation_name) > 200:
        errors.append("Organisation name must be 200 characters or fewer.")

    average_annual_salary: float = 0.0
    if not salary_raw:
        errors.append("Average annual salary is required.")
    else:
        try:
            average_annual_salary = float(salary_raw)
            if average_annual_salary < MIN_ANNUAL_SALARY:
                errors.append(
                    f"Average annual salary must be at least "
                    f"{CURRENCY_SYMBOL}{MIN_ANNUAL_SALARY:,.0f}."
                )
            elif average_annual_salary > MAX_ANNUAL_SALARY:
                errors.append(
                    f"Average annual salary must not exceed "
                    f"{CURRENCY_SYMBOL}{MAX_ANNUAL_SALARY:,.0f}."
                )
        except ValueError:
            errors.append("Average annual salary must be a valid number.")

    # ------------------------------------------------------------------ #
    # 3. Validate role rows                                               #
    # ------------------------------------------------------------------ #
    # Zip the three parallel lists; guard against mismatched lengths
    n_rows = len(role_names)
    if n_rows == 0:
        errors.append("At least one role category is required.")
    elif n_rows > MAX_ROLES:
        errors.append(f"A maximum of {MAX_ROLES} role categories is supported.")

    # Pad shorter lists to avoid index errors (shouldn't happen with correct
    # form HTML but defensive coding is cheap)
    headcounts = _pad_list(headcounts, n_rows, "")
    automation_potentials = _pad_list(automation_potentials, n_rows, "")

    role_inputs: List[RoleInput] = []
    role_errors: List[str] = []

    for idx, (rname, hc_raw, ap_raw) in enumerate(
        zip(role_names, headcounts, automation_potentials), start=1
    ):
        rname = rname.strip()
        hc_raw = hc_raw.strip()
        ap_raw = ap_raw.strip()

        row_errors: List[str] = []

        if not rname:
            row_errors.append(f"Row {idx}: Role name is required.")
        elif len(rname) > 120:
            row_errors.append(f"Row {idx}: Role name must be 120 characters or fewer.")

        headcount: int = 0
        if not hc_raw:
            row_errors.append(f"Row {idx}: Headcount is required.")
        else:
            try:
                headcount = int(float(hc_raw))
                if headcount < 0:
                    row_errors.append(f"Row {idx}: Headcount must be zero or greater.")
                elif headcount > MAX_ROLE_HEADCOUNT:
                    row_errors.append(
                        f"Row {idx}: Headcount must not exceed {MAX_ROLE_HEADCOUNT:,}."
                    )
            except ValueError:
                row_errors.append(f"Row {idx}: Headcount must be a whole number.")

        automation_potential: float = 0.0
        if not ap_raw:
            row_errors.append(f"Row {idx}: Automation potential is required.")
        else:
            try:
                automation_potential = float(ap_raw)
                if not (0.0 <= automation_potential <= 100.0):
                    row_errors.append(
                        f"Row {idx}: Automation potential must be between 0 and 100."
                    )
            except ValueError:
                row_errors.append(
                    f"Row {idx}: Automation potential must be a valid number."
                )

        if row_errors:
            role_errors.extend(row_errors)
        else:
            try:
                role_inputs.append(
                    RoleInput(
                        role_name=rname,
                        headcount=headcount,
                        automation_potential=automation_potential,
                    )
                )
            except (ValueError, TypeError) as exc:
                role_errors.append(f"Row {idx}: {exc}")

    errors.extend(role_errors)

    # ------------------------------------------------------------------ #
    # 4. Handle validation failure — redirect back to form               #
    # ------------------------------------------------------------------ #
    if errors:
        for msg in errors:
            flash(msg, "error")
        # Preserve form values so the user does not have to re-enter data
        session["form_data"] = _build_form_data_dict(
            organisation_name=organisation_name,
            average_annual_salary=salary_raw,
            role_names=role_names,
            headcounts=headcounts,
            automation_potentials=automation_potentials,
        )
        logger.warning(
            "Form validation failed with %d error(s): %s",
            len(errors),
            "; ".join(errors),
        )
        return redirect(url_for("index"))

    # ------------------------------------------------------------------ #
    # 5. Run the calculation engine                                       #
    # ------------------------------------------------------------------ #
    try:
        report: FullReport = calculate_report(
            roles=role_inputs,
            average_annual_salary=average_annual_salary,
            organisation_name=organisation_name,
        )
    except (ValueError, TypeError) as exc:
        flash(f"Calculation error: {exc}", "error")
        logger.error("Calculation engine error: %s", exc, exc_info=True)
        session["form_data"] = _build_form_data_dict(
            organisation_name=organisation_name,
            average_annual_salary=salary_raw,
            role_names=role_names,
            headcounts=headcounts,
            automation_potentials=automation_potentials,
        )
        return redirect(url_for("index"))
    except Exception as exc:  # noqa: BLE001
        flash(
            "An unexpected error occurred while generating your report. "
            "Please check your inputs and try again.",
            "error",
        )
        logger.error("Unexpected error in calculate(): %s", exc, exc_info=True)
        return redirect(url_for("index"))

    # ------------------------------------------------------------------ #
    # 6. Serialise report to session                                      #
    # ------------------------------------------------------------------ #
    try:
        report_json: str = _serialise_report(report)
        if len(report_json) > _MAX_SESSION_PAYLOAD:
            # This should not happen with normal inputs but guard defensively
            flash(
                "The report data is too large to store in the session. "
                "Please reduce the number of roles and try again.",
                "error",
            )
            logger.warning(
                "Report JSON payload too large: %d bytes", len(report_json)
            )
            return redirect(url_for("index"))
        session[_SESSION_KEY] = report_json
    except Exception as exc:  # noqa: BLE001
        flash("Failed to save report data. Please try again.", "error")
        logger.error("Session serialisation error: %s", exc, exc_info=True)
        return redirect(url_for("index"))

    logger.info(
        "Report calculated and stored in session for '%s' (%d roles, %d total workers)",
        organisation_name,
        len(role_inputs),
        report.total_headcount,
    )
    return redirect(url_for("results"))


def results() -> Response:
    """Render the results dashboard.

    Retrieves the :class:`~ai_labour_calc.models.FullReport` from the
    session (stored by :func:`calculate`) and renders ``results.html``.
    If no report is found in the session the user is redirected back to
    the input form with an informational flash message.

    Returns:
        Rendered HTML string for ``results.html``, or a redirect to ``/``
        if no report data is present.
    """
    report_json: Optional[str] = session.get(_SESSION_KEY)
    if not report_json:
        flash(
            "No report found. Please fill in the form and click "
            "\u2018Generate Scenario Report\u2019.",
            "info",
        )
        return redirect(url_for("index"))

    try:
        report: FullReport = _deserialise_report(report_json)
    except Exception as exc:  # noqa: BLE001
        flash(
            "Could not load your report data. Please re-submit the form.",
            "error",
        )
        logger.error("Session deserialisation error: %s", exc, exc_info=True)
        session.pop(_SESSION_KEY, None)
        return redirect(url_for("index"))

    return render_template(
        "results.html",
        report=report,
        currency_symbol=CURRENCY_SYMBOL,
        currency_code=CURRENCY_CODE,
    )


def download_csv() -> Response:
    """Stream the CSV report for the current session's report.

    Generates the CSV bytes via
    :func:`~ai_labour_calc.report.generate_csv_bytes` and returns them as
    an ``attachment`` with MIME type ``text/csv``.

    Returns:
        A :class:`flask.Response` with ``Content-Disposition: attachment``
        and body containing UTF-8 encoded CSV data, or a redirect to ``/``
        if no report is present.
    """
    report_json: Optional[str] = session.get(_SESSION_KEY)
    if not report_json:
        flash("No report found. Please generate a report first.", "info")
        return redirect(url_for("index"))

    try:
        report: FullReport = _deserialise_report(report_json)
    except Exception as exc:  # noqa: BLE001
        flash("Could not load report data. Please re-submit the form.", "error")
        logger.error("CSV download deserialisation error: %s", exc, exc_info=True)
        return redirect(url_for("index"))

    try:
        csv_bytes: bytes = generate_csv_bytes(report, include_role_breakdown=True)
    except Exception as exc:  # noqa: BLE001
        flash("Failed to generate the CSV file. Please try again.", "error")
        logger.error("CSV generation error: %s", exc, exc_info=True)
        return redirect(url_for("results"))

    safe_name = _safe_filename(report.organisation_name)
    filename = f"ai_labour_report_{safe_name}.csv"

    return Response(
        csv_bytes,
        status=200,
        mimetype="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(csv_bytes)),
            "Cache-Control": "no-store",
        },
    )


def download_pdf() -> Response:
    """Stream the PDF report for the current session's report.

    Generates the PDF bytes via
    :func:`~ai_labour_calc.report.generate_pdf_bytes` and returns them as
    an ``attachment`` with MIME type ``application/pdf``.

    Returns:
        A :class:`flask.Response` with ``Content-Disposition: attachment``
        and body containing raw PDF bytes, or a redirect to ``/`` if no
        report is present.
    """
    report_json: Optional[str] = session.get(_SESSION_KEY)
    if not report_json:
        flash("No report found. Please generate a report first.", "info")
        return redirect(url_for("index"))

    try:
        report: FullReport = _deserialise_report(report_json)
    except Exception as exc:  # noqa: BLE001
        flash("Could not load report data. Please re-submit the form.", "error")
        logger.error("PDF download deserialisation error: %s", exc, exc_info=True)
        return redirect(url_for("index"))

    try:
        pdf_bytes: bytes = generate_pdf_bytes(report)
    except Exception as exc:  # noqa: BLE001
        flash(
            "Failed to generate the PDF file. "
            "Please ensure WeasyPrint system dependencies are installed and try again.",
            "error",
        )
        logger.error("PDF generation error: %s", exc, exc_info=True)
        return redirect(url_for("results"))

    safe_name = _safe_filename(report.organisation_name)
    filename = f"ai_labour_report_{safe_name}.pdf"

    return Response(
        pdf_bytes,
        status=200,
        mimetype="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(pdf_bytes)),
            "Cache-Control": "no-store",
        },
    )


def health() -> Tuple[Response, int]:
    """Return a simple JSON health-check response.

    Useful for container health probes and uptime monitoring.

    Returns:
        A 2-tuple of ``(Response, 200)`` where the response body is
        ``{"status": "ok"}``.
    """
    return Response(
        response=json.dumps({"status": "ok"}),
        status=200,
        mimetype="application/json",
    ), 200


# --------------------------------------------------------------------------- #
# CLI entry-point                                                              #
# --------------------------------------------------------------------------- #


def main() -> None:
    """Entry-point used by the ``ai-labour-calc`` console script.

    Creates the application via the factory and starts the development
    server.  For production deployments use a WSGI server such as
    Gunicorn or uWSGI instead.
    """
    from ai_labour_calc import create_app  # local import to avoid circular

    app = create_app()
    app.run(debug=True, host="0.0.0.0", port=5000)


# --------------------------------------------------------------------------- #
# Serialisation helpers                                                        #
# --------------------------------------------------------------------------- #


def _serialise_report(report: FullReport) -> str:
    """Serialise a :class:`~ai_labour_calc.models.FullReport` to a JSON string.

    Converts the dataclass hierarchy to a plain dict using
    :func:`dataclasses.asdict` and then serialises to JSON.

    Args:
        report: A fully populated :class:`~ai_labour_calc.models.FullReport`.

    Returns:
        A JSON string representing the report.

    Raises:
        TypeError: If the report cannot be serialised.
    """
    data = asdict(report)
    return json.dumps(data, ensure_ascii=False)


def _deserialise_report(report_json: str) -> FullReport:
    """Reconstruct a :class:`~ai_labour_calc.models.FullReport` from a JSON string.

    Parses the JSON produced by :func:`_serialise_report` and rebuilds
    the full dataclass hierarchy.

    Args:
        report_json: JSON string as produced by :func:`_serialise_report`.

    Returns:
        A fully populated :class:`~ai_labour_calc.models.FullReport`.

    Raises:
        ValueError: If the JSON is malformed or missing required keys.
        KeyError: If a required field is absent from the JSON payload.
    """
    data: dict = json.loads(report_json)

    roles = [
        RoleInput(
            role_name=r["role_name"],
            headcount=int(r["headcount"]),
            automation_potential=float(r["automation_potential"]),
        )
        for r in data["roles"]
    ]

    def _build_scenario(sd: dict) -> ScenarioResult:
        role_breakdowns = [
            RoleDisplacement(
                role_name=rb["role_name"],
                original_headcount=int(rb["original_headcount"]),
                displaced_workers=int(rb["displaced_workers"]),
                remaining_workers=int(rb["remaining_workers"]),
                displacement_rate=float(rb["displacement_rate"]),
            )
            for rb in sd.get("role_breakdowns", [])
        ]
        return ScenarioResult(
            scenario_name=sd["scenario_name"],
            timeline_years=int(sd["timeline_years"]),
            timeline_multiplier=float(sd["timeline_multiplier"]),
            total_headcount=int(sd["total_headcount"]),
            total_displaced=int(sd["total_displaced"]),
            total_remaining=int(sd["total_remaining"]),
            displacement_percentage=float(sd["displacement_percentage"]),
            robot_tax_liability=float(sd["robot_tax_liability"]),
            retraining_cost=float(sd["retraining_cost"]),
            ubi_transfer_annual=float(sd["ubi_transfer_annual"]),
            unemployment_insurance_cost=float(sd["unemployment_insurance_cost"]),
            total_safety_net_exposure=float(sd["total_safety_net_exposure"]),
            role_breakdowns=role_breakdowns,
        )

    return FullReport(
        organisation_name=data["organisation_name"],
        average_annual_salary=float(data["average_annual_salary"]),
        roles=roles,
        optimistic=_build_scenario(data["optimistic"]),
        moderate=_build_scenario(data["moderate"]),
        aggressive=_build_scenario(data["aggressive"]),
    )


# --------------------------------------------------------------------------- #
# Form data helpers                                                            #
# --------------------------------------------------------------------------- #


def _build_form_data_dict(
    organisation_name: str,
    average_annual_salary: str,
    role_names: List[str],
    headcounts: List[str],
    automation_potentials: List[str],
) -> Dict[str, Any]:
    """Build a plain dict representing the submitted form values.

    Used to preserve user input across a POST → redirect → GET cycle when
    validation fails.

    Args:
        organisation_name: Raw organisation name string from the form.
        average_annual_salary: Raw salary string from the form.
        role_names: List of raw role name strings.
        headcounts: List of raw headcount strings.
        automation_potentials: List of raw automation potential strings.

    Returns:
        A dict suitable for storage in the Flask session and passing as
        ``form_data`` to the ``index.html`` template context.
    """
    roles_data = []
    for rname, hc, ap in zip(
        role_names,
        _pad_list(headcounts, len(role_names), ""),
        _pad_list(automation_potentials, len(role_names), ""),
    ):
        roles_data.append(
            {
                "role_name": rname,
                "headcount": hc,
                "automation_potential": ap,
            }
        )
    return {
        "organisation_name": organisation_name,
        "average_annual_salary": average_annual_salary,
        "roles": roles_data,
    }


def _pad_list(lst: List[str], target_length: int, fill: str) -> List[str]:
    """Return *lst* extended with *fill* values to reach *target_length*.

    If *lst* is already at least *target_length* items long it is returned
    unchanged.  This guards against mismatched parallel lists caused by
    client-side form manipulation.

    Args:
        lst: The list to pad.
        target_length: Desired minimum length.
        fill: Value to append when padding is needed.

    Returns:
        The (possibly extended) list.
    """
    if len(lst) >= target_length:
        return lst
    return lst + [fill] * (target_length - len(lst))


# --------------------------------------------------------------------------- #
# Filename sanitisation                                                        #
# --------------------------------------------------------------------------- #


def _safe_filename(name: str) -> str:
    """Convert an arbitrary string into a safe ASCII filename component.

    Replaces any character that is not alphanumeric, a hyphen, or an
    underscore with an underscore, then collapses consecutive underscores
    and trims to 64 characters.

    Args:
        name: The raw string (e.g. an organisation name).

    Returns:
        A sanitised, lowercase ASCII filename component (never empty —
        falls back to ``"report"`` if the result would otherwise be blank).

    Example::

        _safe_filename("Acme Corp (Global)")  # returns "acme_corp__global_"
    """
    safe = re.sub(r"[^\w\-]", "_", name, flags=re.ASCII)
    safe = re.sub(r"_+", "_", safe).strip("_").lower()
    safe = safe[:64]
    return safe if safe else "report"


# --------------------------------------------------------------------------- #
# Jinja2 custom filters                                                        #
# --------------------------------------------------------------------------- #


def _filter_format_int(value: Any) -> str:
    """Jinja2 filter: format a number as a thousands-separated integer string.

    Args:
        value: Numeric value to format.

    Returns:
        Formatted string such as ``"1,234,567"``.
    """
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return str(value)
