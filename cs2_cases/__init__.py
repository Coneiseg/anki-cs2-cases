"""CS2 Cases — an Anki gamification add-on.

Reviewing cards earns virtual in-app dollars, spent on CS2-style case openings.
All currency is virtual; no real money is involved.

The package is import-safe outside Anki: the aqt/anki wiring only runs when those
modules are available, so the pure-logic submodules (economy, unboxing, store) can
be imported and unit-tested standalone.
"""

try:
    import aqt  # noqa: F401
    _IN_ANKI = True
except ImportError:  # running under plain Python (tests, tooling)
    _IN_ANKI = False

if _IN_ANKI:
    from . import entry
    entry.setup()
