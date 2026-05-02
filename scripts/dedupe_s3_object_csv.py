#!/usr/bin/env python3
"""
Deduplica filas de CSV de inventario S3: una fila por objeto (bucket + key canónica).

Criterio: (bucket, key) extraído de s3_uri; si no hay URI, solo key normalizada.
Se conserva la primera fila encontrada. Sin cambios al disco si nada se elimina.
"""

from __future__ import annotations

import argparse
import csv
import sys
import urllib.parse
from pathlib import Path


def _canonical_id(row: dict[str, str]) -> tuple[str, str] | None:
    u = (row.get("s3_uri") or "").strip()
    if u.startswith("s3://"):
        rest = u[5:].split("/", 1)
        if len(rest) == 2:
            b, k = rest[0], urllib.parse.unquote_plus(rest[1])
            return b, k
    k = (row.get("key") or "").strip()
    if not k:
        return None
    return ("", urllib.parse.unquote_plus(k.lstrip("/")))


def dedupe(path: Path) -> tuple[int, int, bool]:
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        if not fieldnames:
            raise SystemExit("CSV vacío o sin cabecera")
        rows = list(reader)
    seen: set[tuple[str, str]] = set()
    out: list[dict[str, str]] = []
    for row in rows:
        cid = _canonical_id(row)
        if not cid or not cid[1]:
            continue
        if cid in seen:
            continue
        seen.add(cid)
        out.append(row)
    changed = len(out) != len(rows)
    if changed:
        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            w.writeheader()
            w.writerows(out)
    return len(rows), len(out), changed


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("csv", nargs="+", type=Path, help="Ficheros CSV a deduplicar")
    args = p.parse_args()
    for path in args.csv:
        if not path.is_file():
            print(f"ERROR: no existe {path}", file=sys.stderr)
            sys.exit(1)
        before, after, changed = dedupe(path)
        tag = "escrito" if changed else "sin cambios"
        print(f"{path.name}: {before} filas -> {after} unicas ({tag})")


if __name__ == "__main__":
    main()
