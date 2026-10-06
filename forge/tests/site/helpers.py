"""Site test helpers. INIT-032/SPEC-014."""

from __future__ import annotations

from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"


def fixture_dir() -> Path:
    return FIXTURES
