#!/usr/bin/env python3
"""
Probe local/diagnóstico: DNS, TCP:443 y head/get object contra S3.

Uso rápido (usa profile asap_main por defecto):
  python scripts/test_s3.py

Opcional:
  python scripts/test_s3.py --profile asap_main --bucket <bucket> --key <key>
"""

from __future__ import annotations

import argparse
import os
import socket
import sys
import time

import boto3
from botocore.config import Config


def _build_module_style_s3(region: str):
    connect = int(os.getenv("S3_CONNECT_TIMEOUT", "15"))
    read = int(os.getenv("S3_READ_TIMEOUT", "60"))
    attempts = int(os.getenv("S3_MAX_ATTEMPTS", "4"))
    mode = os.getenv("S3_RETRY_MODE", "standard").strip().lower()
    if mode not in ("standard", "adaptive", "legacy"):
        mode = "standard"
    endpoint = os.getenv("S3_ENDPOINT_URL", "").strip() or None
    use_regional = os.getenv("S3_USE_REGIONAL_ENDPOINT", "").strip().lower() in ("1", "true", "yes")

    kwargs = {
        "region_name": region,
        "config": Config(
            connect_timeout=connect,
            read_timeout=read,
            retries={"max_attempts": attempts, "mode": mode},
            tcp_keepalive=True,
            s3={"addressing_style": "virtual"},
        ),
    }
    if endpoint:
        kwargs["endpoint_url"] = endpoint
    elif use_regional:
        kwargs["endpoint_url"] = f"https://s3.{region}.amazonaws.com"

    return boto3.client("s3", **kwargs)


def run_probe(bucket: str, key: str, region: str) -> int:
    print("[PROBE] === start ===", flush=True)

    hosts = [f"s3.{region}.amazonaws.com", f"{bucket}.s3.{region}.amazonaws.com"]

    for host in hosts:
        t0 = time.time()
        try:
            ip = socket.gethostbyname(host)
            print(f"[PROBE] DNS {host} -> {ip} in {time.time() - t0:.2f}s", flush=True)
        except Exception as err:
            print(f"[PROBE] DNS {host} FAIL in {time.time() - t0:.2f}s: {type(err).__name__}: {err}", flush=True)

    for host in hosts:
        t0 = time.time()
        try:
            s = socket.create_connection((host, 443), timeout=8)
            s.close()
            print(f"[PROBE] TCP {host}:443 OK in {time.time() - t0:.2f}s", flush=True)
        except Exception as err:
            print(f"[PROBE] TCP {host}:443 FAIL in {time.time() - t0:.2f}s: {type(err).__name__}: {err}", flush=True)

    s3_fresh = boto3.client(
        "s3",
        region_name=region,
        config=Config(connect_timeout=5, read_timeout=10, retries={"max_attempts": 1, "mode": "standard"}),
    )
    t0 = time.time()
    try:
        resp = s3_fresh.head_object(Bucket=bucket, Key=key)
        print(f"[PROBE] head_object (cliente fresh) OK in {time.time() - t0:.2f}s size={resp.get('ContentLength')}", flush=True)
    except Exception as err:
        print(f"[PROBE] head_object (cliente fresh) FAIL in {time.time() - t0:.2f}s: {type(err).__name__}: {err}", flush=True)

    t0 = time.time()
    try:
        resp = s3_fresh.get_object(Bucket=bucket, Key=key)
        print(f"[PROBE] get_object (cliente fresh) OK in {time.time() - t0:.2f}s size={resp.get('ContentLength')}", flush=True)
        t1 = time.time()
        body = resp["Body"].read()
        print(f"[PROBE] body.read() OK bytes={len(body)} in {time.time() - t1:.2f}s", flush=True)
    except Exception as err:
        print(f"[PROBE] get_object (cliente fresh) FAIL in {time.time() - t0:.2f}s: {type(err).__name__}: {err}", flush=True)

    s3_module = _build_module_style_s3(region)
    t0 = time.time()
    try:
        resp = s3_module.head_object(Bucket=bucket, Key=key)
        print(f"[PROBE] head_object (estilo embeddings) OK in {time.time() - t0:.2f}s size={resp.get('ContentLength')}", flush=True)
    except Exception as err:
        print(f"[PROBE] head_object (estilo embeddings) FAIL in {time.time() - t0:.2f}s: {type(err).__name__}: {err}", flush=True)
        return 1

    print("[PROBE] === end ===", flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnóstico DNS/TCP/S3 head/get object")
    parser.add_argument("--profile", default=os.getenv("AWS_PROFILE", "asap_main"), help="Perfil AWS (default: asap_main)")
    parser.add_argument("--region", default=os.getenv("AWS_REGION", "us-east-1"), help="Región AWS")
    parser.add_argument("--bucket", default=os.getenv("S3_PROBE_BUCKET", "rag-documents-prod-913123310997"), help="Bucket S3")
    parser.add_argument(
        "--key",
        default=os.getenv("S3_PROBE_KEY", "tenant_anmat/51d1efe8-448e-4c58-8e3d-f74df1301e81/documents/upload_1776822055.pdf"),
        help="Key del objeto",
    )
    args = parser.parse_args()

    os.environ["AWS_PROFILE"] = args.profile
    print(f"[PROBE] AWS_PROFILE={args.profile}", flush=True)

    if not args.bucket or not args.key:
        print("Falta bucket/key", file=sys.stderr)
        return 2

    return run_probe(args.bucket, args.key, args.region)


if __name__ == "__main__":
    raise SystemExit(main())