from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def test_alembic_revision_chain_has_single_head() -> None:
    project_root = Path(__file__).resolve().parents[2]
    config = Config(project_root / "alembic.ini")
    config.set_main_option("script_location", str(project_root / "backend" / "migrations"))

    script = ScriptDirectory.from_config(config)

    assert script.get_current_head() == "0010_add_auth_and_run_control"
    assert script.get_revision("0010_add_auth_and_run_control").down_revision == "0009"
