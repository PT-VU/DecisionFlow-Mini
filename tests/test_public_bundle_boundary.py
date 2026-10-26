from pathlib import Path
import pytest


def test_public_bundle_does_not_contain_private_evaluator_or_runtime_db():
    root = Path(__file__).resolve().parents[1]
    if (root / "runtime").exists() or not (root / "data" / "public_v02").exists():
        pytest.skip("boundary test applies to the clean public release checkout")
    assert not (root / "evaluator_private").exists()
    db_files = [
        path
        for path in root.rglob("*.db")
        if not any(part.startswith(".pytest-") for part in path.parts)
    ]
    assert not db_files
    assert not (root / "gold_labels").exists()
