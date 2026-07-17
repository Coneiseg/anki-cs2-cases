#!/usr/bin/env python3
"""Package the add-on into dist/cs2_cases.ankiaddon (a zip with files at the root).

Bundles everything needed to run — including the real CS2 sounds and the bundled font —
and excludes only per-user runtime files (saved state, the downloaded full catalog, and
the locally cached skin images), which each install generates for itself.
"""
import os
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "cs2_cases")
DIST = os.path.join(ROOT, "dist")
OUT = os.path.join(DIST, "cs2_cases.ankiaddon")

# Per-user runtime files — never shipped (Anki/each install regenerates them).
EXCLUDE_FILES = {
    os.path.join("user_files", "state.json"),
    os.path.join("user_files", "catalog.json"),
}
EXCLUDE_DIR_PREFIXES = (
    "__pycache__",
    os.path.join("user_files", "assets", "images"),
)
EXCLUDE_SUFFIXES = (".pyc", ".corrupt", ".part", ".tmp")


def _skip(rel: str) -> bool:
    if rel in EXCLUDE_FILES:
        return True
    if rel.endswith(EXCLUDE_SUFFIXES):
        return True
    parts = rel.split(os.sep)
    for prefix in EXCLUDE_DIR_PREFIXES:
        pp = prefix.split(os.sep)
        if parts[: len(pp)] == pp:
            return True
    return False


def build() -> str:
    os.makedirs(DIST, exist_ok=True)
    if os.path.exists(OUT):
        os.remove(OUT)
    count = 0
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
        for base, _dirs, files in os.walk(SRC):
            for name in files:
                full = os.path.join(base, name)
                rel = os.path.relpath(full, SRC)  # path inside the addon (root-level)
                if _skip(rel):
                    continue
                z.write(full, rel)
                count += 1
    return "%s (%d files, %.0f KB)" % (OUT, count, os.path.getsize(OUT) / 1024)


if __name__ == "__main__":
    print("Built", build())
