"""
Test de regresión para validar que hybrid search encuentra keywords exactas
que la búsqueda puramente vectorial perdía.
"""
from __future__ import annotations

import os
import sys

_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(_root, "apps", "rag_lmbd_query"))

from index import semantic_search  # noqa: E402

TEST_TENANT_ID = os.environ["TEST_TENANT_ID"]
TEST_AGENT_ID = os.environ["TEST_AGENT_ID"]

# Casos que DEBEN encontrarse (keywords que fallaban antes)
MUST_FIND = [
    "SWIFT",
    "ISO 20022",
    "pain.001",
    "COPP",
    # Citas normativas (dígitos/barra): FTS español puede fallar; la pata literal substring debe cubrir.
    "Decreto 930/2012",
]

# Casos semánticos que deben seguir funcionando
SEMANTIC_CASES = [
    "transferencias internacionales",
    "procesamiento de pagos en lote",
]


def test_keyword(keyword):
    chunks, docs = semantic_search(
        query=keyword,
        tenant_id=TEST_TENANT_ID,
        agent_id=TEST_AGENT_ID,
        k=20,
    )
    found = any(keyword.lower() in c.lower() for c in chunks)
    status = "✅ PASS" if found else "❌ FAIL"
    print(f"{status} | keyword='{keyword}' | chunks_returned={len(chunks)} | docs={docs}")
    return found


if __name__ == "__main__":
    print("\n=== Keywords exactas (críticas) ===")
    kw_results = [test_keyword(kw) for kw in MUST_FIND]

    print("\n=== Queries semánticas (regresión) ===")
    sem_results = [test_keyword(q) for q in SEMANTIC_CASES]

    total = len(kw_results) + len(sem_results)
    passed = sum(kw_results) + sum(sem_results)
    print(f"\nResultado: {passed}/{total} tests pasaron")

    if not all(kw_results):
        print("⚠️  Alguna keyword crítica no fue encontrada — revisar pesos o migración SQL")
        sys.exit(1)
