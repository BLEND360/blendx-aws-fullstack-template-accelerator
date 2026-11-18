"""The API depends on nothing in the starter harness project, and the layering rules stay in force."""

import tomllib
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"
PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"

# Files and paths of the starter harness subproject (harness/ at the repository root).
STARTER_HARNESS_REFERENCES = (
    "harness/agentcore",
    "harness/app",
    "agentcore.json",
    "aws-targets.json",
    "harness.json",
    "deploy_harness",
    "harness_files",
    "agentcore/cdk",
)


def app_files():
    return [p for p in APP.rglob("*") if p.is_file() and p.suffix in {".py", ".json", ".toml", ".md"} and "__pycache__" not in p.parts]


def test_nothing_in_the_app_references_the_starter_harness_project():
    offenders = {
        str(path.relative_to(APP)): reference
        for path in app_files()
        for reference in STARTER_HARNESS_REFERENCES
        if reference in path.read_text(encoding="utf-8")
    }
    assert offenders == {}


def test_the_app_does_not_import_the_infra_or_scripts_projects():
    for path in app_files():
        if path.suffix != ".py":
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            assert not stripped.startswith(("import infra", "from infra", "import scripts", "from scripts", "import harness ", "from harness ")), (
                f"{path.relative_to(APP)}: {stripped}"
            )


def test_the_layering_contracts_this_design_relies_on_are_still_declared():
    config = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["tool"]["importlinter"]
    contracts = {c["name"]: c for c in config["contracts"]}
    layers = contracts["Backend layering"]["layers"]
    assert "app.tools" in layers[2], "tools are adapters: they belong in the adapters layer"
    services_rule = contracts["Services use ports, never adapters"]
    assert services_rule["type"] == "forbidden"
    assert set(services_rule["forbidden_modules"]) >= {"app.harness", "app.tools", "app.repositories", "app.clients"}
