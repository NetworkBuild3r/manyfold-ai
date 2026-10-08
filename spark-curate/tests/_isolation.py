"""Module-level network isolation for merge tests (INIT-001/SPEC-007).

Use as ``from _isolation import setUpModule, tearDownModule`` in any test module
that can reach TypeSafe. Blanks TYPESAFE_API_KEY so a key exported in the shell
or container never turns a unit test into a live API call, and makes any real
``urllib.request.urlopen`` call fail the test.
"""
from __future__ import annotations

import os
from unittest.mock import patch


class NetworkCallInTest(BaseException):
    """BaseException so production ``except Exception`` blocks cannot swallow it."""


def _refuse_network(*args: object, **kwargs: object) -> None:
    raise NetworkCallInTest(f"unexpected network call in tests: {args[:1]!r}")


_patches = [
    patch.dict(os.environ, {"TYPESAFE_API_KEY": ""}),
    patch("urllib.request.urlopen", side_effect=_refuse_network),
]


def setUpModule() -> None:  # noqa: N802 — unittest hook name
    for p in _patches:
        p.start()


def tearDownModule() -> None:  # noqa: N802 — unittest hook name
    for p in reversed(_patches):
        p.stop()
