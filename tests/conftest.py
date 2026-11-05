"""Shared fixtures: one small end-to-end simulation per test session.

Synthetic data — for demonstration only.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.simulate_small import simulate


@pytest.fixture(scope="session")
def sim(tmp_path_factory) -> dict:
    root = tmp_path_factory.mktemp("sim")
    result = simulate(root)
    result["paths"] = {
        "raw": root / "data" / "raw",
        "gt": root / "data" / "ground_truth",
        "exchange": root / "data" / "exchange",
        "outputs": root / "outputs",
        "examples": root / "examples",
    }
    return result


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent
