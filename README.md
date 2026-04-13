# AI Labour Impact Calculator

A web tool for businesses and policy researchers to model projected AI-driven workforce changes across **three automation timelines** — optimistic, moderate, and aggressive — grounded in OpenAI's proposed industrial policy framework.

## Features

- **Three-scenario modelling** — Compare optimistic, moderate, and aggressive AI automation timelines side-by-side
- **Role-level automation potential** — Input your organisation's headcount and per-role automation potential percentages
- **Robot tax liability estimation** — Calculate projected robot tax obligations based on displaced worker count, average salary, and proposed tax rate schedules
- **Social safety-net cost exposure** — Model retraining costs, UBI-style transfers, and unemployment insurance projections
- **Interactive charts** — Chart.js visualisations comparing workforce displacement and financial exposure across all three scenarios
- **Downloadable reports** — Export results as styled PDF or raw CSV for further analysis

## Requirements

- Python 3.11 or later
- pip / [uv](https://github.com/astral-sh/uv) package manager
- WeasyPrint system libraries (see below)

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/your-org/ai_labour_calc.git
cd ai_labour_calc
```

### 2. Create and activate a virtual environment

```bash
python -m venv .venv
source .venv/bin/activate   # Linux / macOS
.venv\Scripts\activate      # Windows
```

### 3. Install system dependencies for WeasyPrint

WeasyPrint requires native libraries for font rendering and PDF generation.

**macOS (Homebrew):**
```bash
brew install pango cairo gdk-pixbuf libffi
```

**Ubuntu / Debian:**
```bash
sudo apt-get update
sudo apt-get install -y \
  libpango-1.0-0 \
  libpangoft2-1.0-0 \
  libgdk-pixbuf2.0-0 \
  libcairo2 \
  libffi-dev
```

**Fedora / RHEL:**
```bash
sudo dnf install pango cairo gdk-pixbuf2 libffi-devel
```

**Windows:**
See the [WeasyPrint Windows installation guide](https://doc.courtbouillon.org/weasyprint/stable/first_steps.html#windows).

### 4. Install Python dependencies

```bash
# Standard install
pip install -e .

# With development/test extras
pip install -e ".[dev]"
```

## Running the Application

### Development server

```bash
flask --app ai_labour_calc run --debug
```

### Using the installed script

```bash
ai-labour-calc
```

### Using uv

```bash
uv run flask --app ai_labour_calc run --debug
```

The application will be available at [http://localhost:5000](http://localhost:5000).

## Usage Guide

### Step 1 — Enter Organisation Details

On the home page, provide:
- **Organisation name** — used in report headers and file names
- **Average annual salary (USD)** — baseline for robot tax and safety-net calculations

### Step 2 — Add Role Categories

Add one or more role types with:
- **Role name** — descriptive label (e.g. "Data Entry Clerks")
- **Headcount** — number of workers currently in that role (0–1,000,000)
- **Automation potential** — estimated percentage of work automatable (0–100%)

Use the built-in guide for automation potential benchmarks:

| Range | Example Roles |
|-------|---------------|
| 0–20% | Surgeons, therapists, senior executives |
| 20–60% | Analysts, project managers, sales |
| 60–100% | Data entry, call centre, bookkeeping |

### Step 3 — View Results

The results page shows a side-by-side comparison of all three scenarios:

- Projected job displacement (headcount and percentage)
- Estimated annual robot tax liability
- Social safety-net cost exposure (retraining + UBI transfers + unemployment insurance)
- Interactive Chart.js bar and line charts
- Per-role displacement breakdown with impact level indicators

### Step 4 — Download Reports

- **Download CSV** — Raw scenario data and role breakdowns as a spreadsheet-ready CSV
- **Download PDF** — Formatted report with scenario tables, CSS-based charts, and full policy assumptions documentation

## Running Tests

```bash
# Run all tests
pytest

# With verbose output
pytest -v

# With coverage report
pytest --cov=ai_labour_calc --cov-report=term-missing

# Run a specific test module
pytest tests/test_calculator.py -v
pytest tests/test_report.py -v
```

### Test Coverage

The test suite covers:
- `test_calculator.py` — Scenario calculation correctness, edge cases, progressive tax tiers, input validation, and FullReport aggregation properties
- `test_report.py` — CSV/PDF generation structure and content, DataFrame column validation, formatting helpers, and data integrity

## Project Structure

```
ai_labour_calc/
├── __init__.py          # Flask app factory (create_app)
├── app.py               # Routes: /, /calculate, /results, /download/csv, /download/pdf
├── calculator.py        # Core scenario calculation engine
├── models.py            # Dataclasses: RoleInput, ScenarioResult, FullReport
├── report.py            # CSV and PDF report generation
├── assumptions.py       # Tax rates, timelines, policy parameters
├── static/
│   └── style.css        # Responsive stylesheet (CSS custom properties + media queries)
└── templates/
    ├── index.html       # Input form with dynamic JS role rows and client-side validation
    ├── results.html     # Results dashboard with Chart.js visualisations and tab panels
    └── report_pdf.html  # Print-optimised PDF template for WeasyPrint
tests/
├── __init__.py
├── test_calculator.py   # Calculator unit tests (~40 test cases)
└── test_report.py       # Report generation tests (~50 test cases)
pyproject.toml
README.md
```

## Assumptions and Policy Framework

All calculations are based on parameters in `ai_labour_calc/assumptions.py`. Key defaults:

| Parameter | Default | Description |
|-----------|---------|-------------|
| Robot tax rate (base) | 10% | Percentage of displaced worker annual salary |
| Progressive surcharge | +1% to +5% | Applied at 50 / 250 / 500 / 1,000 displaced thresholds |
| Optimistic multiplier | 0.5× / 10 years | Gradual, human-centred adoption |
| Moderate multiplier | 1.0× / 7 years | Market-pace automation |
| Aggressive multiplier | 1.5× / 4 years | Rapid, unconstrained automation |
| Retraining cost per worker | $15,000 | One-time retraining programme cost |
| UBI monthly transfer | $1,000/month | Annual per-displaced-worker transfer |
| UI replacement rate | 50% salary | Over 6-month average UI duration |

All parameters can be modified in `ai_labour_calc/assumptions.py` to reflect your jurisdiction and policy environment.

> **Policy reference:** [OpenAI Industrial Policy Framework (2024)](https://openai.com/global-affairs/economic-blueprint)

## Calculation Methodology

For each of the three scenarios, the engine:

1. **Computes displacement** per role: `effective_rate = min(automation_potential / 100 × multiplier, 1.0)`, then `displaced = floor(headcount × effective_rate)`
2. **Calculates robot tax**: `total_displaced × average_salary × effective_tax_rate` (with progressive surcharge)
3. **Calculates safety-net exposure**:
   - Retraining: `total_displaced × $15,000`
   - UBI: `total_displaced × $12,000/year`
   - Unemployment insurance: `total_displaced × (monthly_salary × 50% × 6 months)`

## Configuration

The application uses Flask's application factory pattern. Configuration can be overridden via:

- Environment variables: `SECRET_KEY`
- Instance config file: `instance/config.py` (auto-loaded if present)
- Test config dict passed to `create_app(test_config={...})`

## Deployment

For production deployments, use a WSGI server:

```bash
# Gunicorn
gunicorn "ai_labour_calc:create_app()" --workers 4 --bind 0.0.0.0:8000

# uWSGI
uwsgi --http 0.0.0.0:8000 --module "ai_labour_calc:create_app()"
```

**Important:** Set a strong `SECRET_KEY` in production:

```bash
export SECRET_KEY="your-secure-random-key-here"
```

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/your-feature`)
3. Commit your changes (`git commit -m 'Add your feature'`)
4. Push to the branch (`git push origin feature/your-feature`)
5. Open a Pull Request

Please ensure all tests pass and coverage remains above 80% before submitting.

## License

MIT License — see [LICENSE](LICENSE) for details.

## Disclaimer

This tool is for illustrative and planning purposes only. All figures are estimates based on configurable assumptions and should not be construed as legal, financial, or regulatory advice.
