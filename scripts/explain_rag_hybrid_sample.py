#!/usr/bin/env python3
"""
EXPLAIN (ANALYZE, BUFFERS) de las dos patas del híbrido (vector + FTS) sobre tenant_*.

Uso (desde máquina con ruta a RDS y credenciales):
  pip install psycopg2-binary boto3  # si hace falta
  python scripts/explain_rag_hybrid_sample.py \\
    --profile asap_main --region us-east-1 \\
    --secret-id 'arn:aws:secretsmanager:us-east-1:ACCOUNT:secret:...' \\
    --host postgres-aurora-prod.cluster-xxxxx.region.rds.amazonaws.com \\
    --db alert_db \\
    --schema tenant_anmat \\
    --agent-id '51d1efe8-448e-4c58-8e3d-f74df1301e81' \\
    --query-text 'clonazepam disposición' \\
    --k 15

Recomendación: usar el endpoint del **writer** para EXPLAIN si la réplica está caliente.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import boto3


def _pg_conn(args):
    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    sm = session.client("secretsmanager")
    raw = sm.get_secret_value(SecretId=args.secret_id)
    sec = json.loads(raw["SecretString"])
    user = sec.get("username") or sec.get("user")
    password = sec.get("password")
    if not user or password is None:
        raise SystemExit("El secreto debe incluir username y password")

    import psycopg2

    return psycopg2.connect(
        host=args.host,
        port=args.port,
        dbname=args.db,
        user=user,
        password=password,
        connect_timeout=30,
    )


def main() -> int:
    p = argparse.ArgumentParser(description="EXPLAIN vector + lexical branches for RAG hybrid")
    p.add_argument("--profile", default=os.environ.get("AWS_PROFILE", "asap_main"))
    p.add_argument("--region", default=os.environ.get("AWS_REGION", "us-east-1"))
    p.add_argument("--secret-id", required=True, help="Secrets Manager ARN o nombre del secreto Postgres")
    p.add_argument("--host", required=True)
    p.add_argument("--port", type=int, default=5432)
    p.add_argument("--db", required=True)
    p.add_argument("--schema", default="tenant_anmat")
    p.add_argument("--agent-id", required=True)
    p.add_argument("--query-text", default="medicamento disposición")
    p.add_argument("--k", type=int, default=15)
    args = p.parse_args()

    conn = _pg_conn(args)
    conn.autocommit = True
    cur = conn.cursor()

    print("--- Tomando un embedding existente como vector de consulta (mismo dim que la tabla) ---")
    cur.execute(
        f"""
        SELECT embedding::text
        FROM {args.schema}.documents
        WHERE agent_id = %s AND embedding IS NOT NULL
        LIMIT 1
        """,
        (args.agent_id,),
    )
    row = cur.fetchone()
    if not row:
        print("No hay filas con embedding para ese agent_id.", file=sys.stderr)
        return 1
    qvec_literal = row[0]

    print("\n========== VECTOR (ORDER BY embedding <=> query LIMIT k) ==========\n")
    cur.execute(
        f"""
        EXPLAIN (ANALYZE, BUFFERS, VERBOSE)
        SELECT ctid, chunk_text,
               embedding <=> %s::vector AS dist
        FROM {args.schema}.documents AS d
        WHERE d.agent_id = %s
        ORDER BY embedding <=> %s::vector ASC
        LIMIT %s
        """,
        (qvec_literal, args.agent_id, qvec_literal, args.k),
    )
    for r in cur.fetchall():
        print(r[0])

    print("\n========== LEXICAL (ts_rank_cd + tsquery español, LIMIT k) ==========\n")
    cur.execute(
        f"""
        EXPLAIN (ANALYZE, BUFFERS, VERBOSE)
        SELECT d.ctid, d.chunk_text,
               ts_rank_cd(d.fts_vector, plainto_tsquery('spanish', %s), 32) AS lex_score
        FROM {args.schema}.documents AS d
        WHERE d.agent_id = %s
        ORDER BY ts_rank_cd(d.fts_vector, plainto_tsquery('spanish', %s), 32) DESC
        LIMIT %s
        """,
        (args.query_text, args.agent_id, args.query_text, args.k),
    )
    for r in cur.fetchall():
        print(r[0])

    cur.close()
    conn.close()
    print("\n--- Listo. Buscá Seq Scan vs Index en cada plan. ---")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
