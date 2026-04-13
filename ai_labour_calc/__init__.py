"""AI Labour Impact Calculator package.

This package provides a Flask web application for modelling projected
AI-driven workforce changes across three automation timelines (optimistic,
moderate, and aggressive). It exposes a create_app() factory function
following Flask's application factory pattern.

Typical usage::

    from ai_labour_calc import create_app

    app = create_app()
    app.run(debug=True)

Or via the Flask CLI::

    flask --app ai_labour_calc run
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from flask import Flask


logger = logging.getLogger(__name__)


def create_app(test_config: Optional[dict] = None) -> Flask:
    """Create and configure the Flask application.

    This factory function initialises the Flask app, applies configuration,
    and registers all blueprints/routes. It follows the Flask application
    factory pattern to support multiple instances and easier testing.

    Args:
        test_config: Optional dictionary of configuration values that override
            the defaults. Used primarily in unit tests to inject test-specific
            settings such as ``TESTING=True`` or a custom ``SECRET_KEY``.

    Returns:
        A fully configured :class:`flask.Flask` application instance.

    Raises:
        RuntimeError: If a required environment variable is missing and no
            default is available.

    Example::

        app = create_app({"TESTING": True, "SECRET_KEY": "test-secret"})
        with app.test_client() as client:
            response = client.get("/")
            assert response.status_code == 200
    """
    app = Flask(
        __name__,
        instance_relative_config=True,
        template_folder="templates",
        static_folder="static",
    )

    # ------------------------------------------------------------------ #
    # Default configuration                                               #
    # ------------------------------------------------------------------ #
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev-secret-change-in-production"),
        MAX_CONTENT_LENGTH=16 * 1024 * 1024,  # 16 MB upload limit
        PDF_FONT_CONFIG=None,  # WeasyPrint font configuration (None = system default)
    )

    if test_config is not None:
        # Override defaults with test-supplied configuration
        app.config.from_mapping(test_config)
    else:
        # Attempt to load instance/config.py if it exists (ignored silently)
        app.config.from_pyfile("config.py", silent=True)

    # ------------------------------------------------------------------ #
    # Ensure the instance folder exists                                   #
    # ------------------------------------------------------------------ #
    try:
        os.makedirs(app.instance_path, exist_ok=True)
    except OSError as exc:
        logger.warning("Could not create instance folder at %s: %s", app.instance_path, exc)

    # ------------------------------------------------------------------ #
    # Register routes                                                     #
    # ------------------------------------------------------------------ #
    # Routes are imported here (inside the factory) to avoid circular
    # imports — app.py depends on create_app being importable first.
    from ai_labour_calc import app as routes_module  # noqa: F401

    routes_module.register_routes(app)

    logger.info(
        "AI Labour Impact Calculator initialised (debug=%s)",
        app.debug,
    )

    return app
