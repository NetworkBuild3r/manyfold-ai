"""GR-001 defense in depth: only canonical names may reach the 7zz include list."""

import pytest

from forge.engine.refuse import check_name
from forge.materialize.extract import include_path_is_canonical


@pytest.mark.parametrize("raw", ["a.stl", "dir/sub/a.stl", "Ünï/ç.3mf"])
def test_canonical_names_pass(raw):
    assert include_path_is_canonical(raw, check_name(raw)[0])


@pytest.mark.parametrize(
    "raw",
    ["../x", "a/../../x", "/etc/x", "a\\..\\x", "a\nb", "./a", "a//b", "@list", "!x", "-x", "a/./b"],
)
def test_hostile_or_noncanonical_names_refused(raw):
    assert not include_path_is_canonical(raw, check_name(raw)[0])
