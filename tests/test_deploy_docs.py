"""Task 10 smoke: deploy config + README Galuxium section presence."""

from pathlib import Path


def test_readme_has_galuxium_section():
    readme = Path("README.md").read_text(encoding="utf-8")
    assert "Galuxium" in readme
    assert "Facility Starter" in readme or "facility_starter" in readme
    assert "Stripe" in readme
    assert "ReadyPup" in readme  # explicit do-not-mix note


def test_deploy_config_exists():
    assert Path("render.yaml").exists() or Path("fly.toml").exists()


def test_saas_dockerfile_bootstraps_schema_before_uvicorn():
    dockerfile = Path("Dockerfile.saas").read_text(encoding="utf-8")
    # Fork uses idempotent create_all in the bootstrap script (no alembic dir).
    assert "bootstrap_saas_demo" in dockerfile
    cmd = [ln for ln in dockerfile.splitlines() if ln.startswith("CMD")]
    assert len(cmd) == 1
    assert "bootstrap_saas_demo" in cmd[0] and "uvicorn" in cmd[0]
    assert cmd[0].index("bootstrap_saas_demo") < cmd[0].index("uvicorn")


def test_env_example_covers_required_secrets():
    env = Path(".env.example").read_text(encoding="utf-8")
    for key in (
        "DATABASE_URL",
        "SESSION_SECRET",
        "CARE_LADDER_ENV",
        "CARE_LADDER_AUTH",
        "STRIPE_PRICE_HOME",
        "STRIPE_PRICE_FACILITY",
        "STRIPE_PRICE_FACILITY_GROWTH",
        "STRIPE_WEBHOOK_SECRET",
        "CARE_LADDER_ALLOW_UNSIGNED_WEBHOOKS",
        "SLACK_WEBHOOK_URL",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
        "TELEGRAM_MODE",
    ):
        assert key in env, f"missing {key} in .env.example"


def test_bootstrap_demo_script_is_idempotent():
    src = Path("scripts/bootstrap_saas_demo.py").read_text(encoding="utf-8")
    assert "merge" in src or "already" in src or "exists" in src


def test_render_yaml_pins_demo_env_and_db():
    cfg = Path("render.yaml").read_text(encoding="utf-8")
    assert "CARE_LADDER_ENV" in cfg and "demo" in cfg
    assert "CARE_LADDER_AUTH" in cfg and "on" in cfg
    assert "fromDatabase" in cfg
    assert "SESSION_SECRET" in cfg
    assert "TELEGRAM_BOT_TOKEN" in cfg
    assert "TELEGRAM_MODE" in cfg
    assert "STRIPE_WEBHOOK_SECRET" in cfg
    assert "required" in cfg.lower()
    # Hosted deploy must not opt into unsigned webhooks.
    for line in cfg.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or "ALLOW_UNSIGNED_WEBHOOKS" not in stripped:
            continue
        assert "1" not in stripped and "true" not in stripped.lower()


def test_pyproject_declares_psycopg_binary_driver():
    """Dockerfile.saas does `pip install -e .`; Render Postgres needs this extra."""
    text = Path("pyproject.toml").read_text(encoding="utf-8")
    assert "psycopg[binary]" in text


def test_render_postgres_url_loads_psycopg_dialect():
    """SQLAlchemy 2.1 maps postgresql:// to dialect postgresql.psycopg."""
    from care_ladder.db.base import create_engine_from_url

    engine = create_engine_from_url("postgresql://u:p@127.0.0.1:5432/care")
    assert engine.dialect.driver == "psycopg"
    import psycopg  # noqa: F401 — the package create_engine imports
