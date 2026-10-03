"""``forge report site --in DIR --out DIR``. INIT-032/SPEC-014."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from forge.site.render import SiteError, render_site


def main_site(args: argparse.Namespace) -> int:
    in_dir = Path(args.in_dir)
    out_dir = Path(args.out_dir)
    try:
        written = render_site(in_dir, out_dir)
    except SiteError as exc:
        print(f"forge report site: {exc}", file=sys.stderr)
        return 2
    for path in written:
        print(path)
    return 0
