import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("WA_NO_MODEL", "1")


@pytest.fixture(autouse=True)
def tmp_data(tmp_path, monkeypatch):
    monkeypatch.setenv("WA_DATA", str(tmp_path))
    monkeypatch.setenv("WA_RULES_FILE", str(tmp_path / "style_rules.json"))
    from app import config
    monkeypatch.setattr(config, "DATA", tmp_path)
    yield tmp_path


@pytest.fixture
def sample():
    return (Path(__file__).resolve().parent.parent / "samples" / "ai_sample.txt").read_text(encoding="utf-8")
