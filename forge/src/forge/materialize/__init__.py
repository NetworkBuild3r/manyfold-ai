"""Library Forge v2 materializer (INIT-032/SPEC-012).

The only forge component that writes files, and it writes only under the v2 root (plus local
scratch). All writes go through :mod:`forge.materialize.guard`; see ``forge/docs/materialize.md``.

Modules: ``guard`` (write guard + startup checks), ``paths`` (layout + sanitization), ``plan``
(DB-only plan), ``store`` (blob store), ``extract`` (member extraction), ``apply`` (claim loop),
``verify`` (verify / audit-source / gc-plan), ``cli`` (argparse wiring).
"""
