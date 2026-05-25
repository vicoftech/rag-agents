#!/usr/bin/env python3
"""
Compara PDFs en S3 bajo un prefijo tenant_* con un export JSON de document_name.

Genera un manifiesto tipo tenant_anmat_s3_not_in_documents_*.json.

Uso:
  python scripts/s3_tenant_diff_documents.py \\
    --bucket rag-documents-prod-913123310997 \\
    --prefix tenant_boletin/ \\
    --reference documents_202605251132.json \\
    --output tenant_boletin_s3_not_in_documents_202605251132.json \\
    --profile asap_main
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote

import boto3

DOCUMENTS_MARKER = "/documents/"


def normalize_document_name(name: str) -> str:
    n = unquote((name or "").strip()).replace("\\", "/")
    while n.startswith("/"):
        n = n[1:]
    return n


def load_reference_names(path: Path) -> set[str]:
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("reference JSON debe ser un objeto")
    names: set[str] = set()
    for value in data.values():
        if not isinstance(value, list):
            continue
        for row in value:
            if isinstance(row, dict):
                dn = row.get("document_name")
            elif isinstance(row, str):
                dn = row
            else:
                continue
            if dn:
                names.add(normalize_document_name(str(dn)))
    if not names:
        raise ValueError("no se encontraron document_name en el reference JSON")
    return names


def document_name_from_s3_key(key: str) -> str | None:
    key = unquote(key)
    idx = key.find(DOCUMENTS_MARKER)
    if idx < 0:
        return None
    rel = key[idx + len(DOCUMENTS_MARKER) :]
    if not rel.lower().endswith(".pdf"):
        return None
    return normalize_document_name(rel)


def list_pdf_objects(s3_client, bucket: str, prefix: str) -> list[dict]:
    paginator = s3_client.get_paginator("list_objects_v2")
    items: list[dict] = []
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents") or []:
            key = obj.get("Key") or ""
            if not key.lower().endswith(".pdf"):
                continue
            dn = document_name_from_s3_key(key)
            if not dn:
                continue
            last_mod = obj.get("LastModified")
            items.append(
                {
                    "document_name": dn,
                    "s3_key": key,
                    "s3_uri": f"s3://{bucket}/{key}",
                    "size_bytes": int(obj.get("Size") or 0),
                    "last_modified": (
                        last_mod.astimezone(timezone.utc).isoformat()
                        if last_mod is not None
                        else None
                    ),
                }
            )
    return items


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--prefix", required=True, help="Prefijo S3, p. ej. tenant_boletin/")
    parser.add_argument("--reference", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--profile", default=None)
    parser.add_argument("--region", default="us-east-1")
    args = parser.parse_args()

    prefix = args.prefix if args.prefix.endswith("/") else args.prefix + "/"
    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    s3 = session.client("s3")

    ref_names = load_reference_names(args.reference)
    print(f"reference document_name count: {len(ref_names)}")

    s3_items = list_pdf_objects(s3, args.bucket, prefix)
    print(f"s3 pdf under {prefix!r}: {len(s3_items)}")

    missing: list[dict] = []
    for item in s3_items:
        if item["document_name"] not in ref_names:
            missing.append(item)

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "bucket": args.bucket,
        "prefix": prefix,
        "reference_json": str(args.reference),
        "reference_document_name_count": len(ref_names),
        "s3_pdf_object_count": len(s3_items),
        "missing_from_reference_count": len(missing),
        "description": (
            f"PDFs en S3 bajo {prefix} cuyo document_name (ruta tras /documents/) "
            "no aparece en el export JSON de tenant_boletin.documents"
        ),
        "items": missing,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(f"wrote {args.output} ({len(missing)} items)")


if __name__ == "__main__":
    main()
