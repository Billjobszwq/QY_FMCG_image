from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

REQUIRED_DOMAINS = {
    "platform-kernel",
    "graph-loop",
    "training-control",
    "dataset-factory",
    "fmcg-recognition",
    "labeling-review",
    "model-runtime",
    "web-workbench",
}
REQUIRED_LOCAL_ZONES = {"training-data", "recognition-models", "runtime"}
REQUIRED_TEST_SUITES = {"contract", "platform", "promotion", "unit",
                        "cognition", "governance", "research", "models"}
REQUIRED_COMPATIBILITY_LINKS = {
    ".models",
    ".sam_checkpoints",
    ".datasets",
    ".datasets_nextgen",
    ".training_data",
    ".batch3_clean",
    ".kb",
    ".micro_gold_v1",
    ".micro_gold_v2",
    ".data_protocol",
    ".eval",
    ".platform",
    ".label-studio",
}


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_developer_readme_documents_all_entry_points_and_domains() -> None:
    readme = _read("README.md")

    for command in (
        "python3 -m venv .venv",
        "pip install -e '.[dev]'",
        "npm --prefix web ci",
        "python3 scripts/bootstrap_local_assets.py",
        "pytest",
        "npm --prefix web run build",
    ):
        assert command in readme

    for domain in REQUIRED_DOMAINS:
        assert domain in readme

    assert "敏感" in readme
    assert "不提交" in readme


def test_structure_document_matches_current_source_and_test_inventory() -> None:
    structure = _read("docs/PROJECT-STRUCTURE.md")
    python_packages = sorted(
        path.name
        for path in (ROOT / "src").iterdir()
        if path.is_dir() and path.name != "__pycache__"
    )
    web_pages = sorted(path.stem for path in (ROOT / "web/src/pages").glob("*.tsx"))
    test_suites = sorted(
        path.name
        for path in (ROOT / "tests").iterdir()
        if path.is_dir() and path.name not in ("__pycache__", "fixtures")
    )

    assert len(python_packages) == 20
    assert len(web_pages) == 30
    assert set(test_suites) == REQUIRED_TEST_SUITES

    for package in python_packages:
        assert f"`src/{package}/`" in structure
    for page in web_pages:
        assert f"`{page}`" in structure
    for suite in test_suites:
        assert f"`tests/{suite}/`" in structure
    for domain in REQUIRED_DOMAINS:
        assert domain in structure


def test_local_asset_guide_is_complete_and_machine_neutral() -> None:
    guide = _read("docs/LOCAL-ASSETS.md")

    for zone in REQUIRED_LOCAL_ZONES:
        assert zone in guide
    for compatibility_link in REQUIRED_COMPATIBILITY_LINKS:
        assert f"`{compatibility_link}`" in guide

    assert "python3 scripts/bootstrap_local_assets.py" in guide
    assert "--dry-run" in guide
    assert "不进入 Git" in guide
    assert not re.search(r"/(?:Users|home)/[^\s`]+", guide)
    assert not re.search(r"[A-Za-z]:\\\\[^\s`]+", guide)


def test_environment_example_contains_placeholders_not_user_data() -> None:
    env_text = _read(".env.example")
    assignments = {
        key: value
        for key, value in re.findall(r"^([A-Z][A-Z0-9_]*)=(.*)$", env_text, re.MULTILINE)
    }

    for key in (
        "OMLX_API_KEY",
        "POSTGRES_PASSWORD",
        "MINIO_ROOT_PASSWORD",
        "LABEL_STUDIO_PASSWORD",
        "RECOGNIZE_ADMIN_TOKEN",
        "LABEL_STUDIO_WEBHOOK_SECRET",
        "LABEL_STUDIO_API_KEY",
    ):
        assert assignments[key] in {"", "<placeholder>"}

    assert assignments["KB_REFERENCE_DIR"] == "<path-to-reference-data>"
    assert assignments["FIELD_XLSX"] == "<path-to-field-metadata>"
    assert not re.search(r"/(?:Users|home)/[^\s]+", env_text)
    assert not re.search(r"[A-Za-z]:\\\\[^\s]+", env_text)
