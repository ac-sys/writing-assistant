"""Slow test with the real local model. Run with: RUN_MODEL_TESTS=1 WA_NO_MODEL=0 pytest tests/test_model.py"""
import os

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("RUN_MODEL_TESTS") != "1", reason="set RUN_MODEL_TESTS=1")


def test_local_model_rewrite(sample, monkeypatch):
    monkeypatch.setenv("WA_NO_MODEL", "0")
    from app.rewrite import rewrite
    r = rewrite(sample, tone="academic", strength="full", british=True, seed=7)
    out = r["text"]
    assert "local" in r["backends"]
    assert "(Moyo, 2023)" in out and "Banda et al. (2021)" in out
    assert '"connectivity remains the single biggest barrier to equitable access."' in out
    for n in ("2022", "1,200", "68%"):
        assert n in out
    assert out != sample


def test_local_model_rewrite_is_not_harder_to_read(sample, monkeypatch):
    monkeypatch.setenv("WA_NO_MODEL", "0")
    from app.rewrite import rewrite
    r = rewrite(sample, tone="academic", strength="full", british=True, seed=7)
    rb = r["readability"]
    assert rb["after"]["flesch_reading_ease"] >= rb["before"]["flesch_reading_ease"] - 3
