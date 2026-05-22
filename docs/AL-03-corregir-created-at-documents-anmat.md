# AL-03 — Corregir `created_at` en `tenant_anmat.documents` desde `public.disposicion`

**Versión:** 0.1 (borrador)  
**Fecha:** 2026-05-20  
**Estado:** Issue / especificación técnica  
**Relacionado:** [AL-02](AL-02-cobertura-temporal-alertas.md) (matching por `created_at`), ingesta ANMAT (`rag_lmbd_embeddings`, `s3_rag_key.parse_s3_rag_key`)

---

## 1. Problema

Los PDFs de **ANMAT** cargados en el corpus RAG quedaron en `tenant_anmat.documents` con **`created_at` incorrecto**: la fecha proviene de la **partición/metadata del archivo en S3** (carpeta `YYYYMMDD` en la key o `LastModified` en migraciones), **no** de la **fecha real de confección/publicación** de la disposición.

Eso provoca:

- El batch `alerts_semantic_matches` filtra por `created_at` del día civil (AL-02) y **no encuentra** documentos recientes aunque existan en S3.
- Desalineación entre el dominio de **alertas** (`public.disposicion`) y el de **retrieval** (`tenant_anmat.documents`).

En el esquema de alertas, **`public.disposicion`** sí conserva las fechas de negocio:

| Columna | Uso |
|---------|-----|
| `nombre_pdf` | Nombre de archivo PDF (clave de cruce) |
| `fecha_de_publicacion` | Fecha de publicación (candidata principal para `created_at`) |
| `fecha_de_aparicion` | Fecha de aparición en el sitio |
| `disposicion_id` | Identificador de negocio (no sustituye al nombre de archivo para este fix) |

---

## 2. Objetivo (v1 simplificado)

1. **Paso 1:** Listar nombres de archivo que están solo en `public.disposicion` o solo en `tenant_anmat.documents`.
2. **Paso 2:** En las **coincidencias** (mismo nombre de archivo), comparar `disposicion.fechayhora_revision` con `documents.created_at`; si difieren, actualizar `created_at` con `fechayhora_revision`.

**Clave:** `trim(disposicion.nombre_pdf)` = basename de `documents.document_name` (todo después del último `/`).

**Fuente de fecha:** `public.disposicion.fechayhora_revision` (no `fecha_de_publicacion` ni partición S3).

**Script:** `scripts/sql/al03_repair_anmat_created_at.sql`

**Fuera de alcance (v1):** Boletín (`tenant_boletin`), re-embeddings masivos, cambio de keys S3.

---

## 3. Modelo de datos y clave de cruce

### 3.1 Tablas

```sql
-- Alertas (fuente de verdad de fechas y nombre de PDF)
public.disposicion (
  id serial PRIMARY KEY,
  disposicion_id varchar(255) NOT NULL,
  nombre_pdf varchar(255),
  fecha_de_publicacion timestamp NOT NULL,
  fecha_de_aparicion timestamp NOT NULL,
  eliminado bool NOT NULL,
  ...
);

-- RAG (una fila por chunk; mismo document_name en todos los chunks del PDF)
tenant_anmat.documents (
  id serial PRIMARY KEY,
  agent_id uuid NOT NULL,
  document_id uuid NOT NULL,
  document_name text NOT NULL,  -- puede incluir prefijo: "20231214/Dispo_xxx.pdf"
  chunk_index integer,
  created_at timestamp,
  ...
);
```

### 3.2 Normalización del nombre de archivo

En embeddings, `document_name` puede ser la ruta bajo `documents/` (ej. `20260114/Dispo_8756-24.pdf`). En `disposicion.nombre_pdf` suele ser **solo el basename**.

**Clave de join (v1):**

```sql
-- Basename case-insensitive, sin espacios extremos
lower(trim(regexp_replace(d.document_name, '^.*/', ''))) =
lower(trim(disp.nombre_pdf))
```

**Pregunta abierta (producto):** si `nombre_pdf` a veces difiere del basename en S3 (encoding, sufijos), documentar excepciones en tabla de mapeo manual.

### 3.3 Fecha destino para `created_at`

| Opción | Campo origen | Nota |
|--------|----------------|------|
| **A (recomendada v1)** | `fecha_de_publicacion` | Alineada a “publicación” de la norma |
| B | `fecha_de_aparicion` | Si negocio define “confección” como aparición en ANMAT |
| C | `LEAST(fecha_de_publicacion, fecha_de_aparicion)` | Conservadora |

El script de UPDATE debe parametrizar la columna origen (`:fecha_column`).

**Convención de tiempo:** truncar al **inicio del día en UTC** (naive), igual que `s3_rag_key._utc_naive_midnight_from_date8` y el filtro de `rag_lmbd_query`, salvo que negocio exija conservar hora de `timestamp` de `disposicion`.

```sql
-- Ejemplo: día UTC desde fecha_de_publicacion
(date_trunc('day', disp.fecha_de_publicacion AT TIME ZONE 'UTC'))::timestamp
-- O si las fechas en BD ya son naive “locales”, acordar AT TIME ZONE 'America/Argentina/Buenos_Aires'
```

---

## 4. SQL — Fase 1: identificar discrepancias (misma clave, fechas distintas)

Vista auxiliar recomendada (ejecutar en sesión de mantenimiento):

```sql
CREATE OR REPLACE VIEW tenant_anmat.v_documents_file AS
SELECT DISTINCT
  agent_id,
  document_id,
  document_name,
  lower(trim(regexp_replace(document_name, '^.*/', ''))) AS file_basename,
  min(created_at) AS created_at_min,
  max(created_at) AS created_at_max,
  count(*) AS chunk_rows
FROM tenant_anmat.documents
GROUP BY 1, 2, 3, 4;
```

### 4.1 Disposiciones con PDF que matchean documents pero `created_at` ≠ fecha de disposición

```sql
-- Parámetro: umbral de diferencia (ej. distinto día civil)
WITH disp AS (
  SELECT
    id,
    disposicion_id,
    nombre_pdf,
    lower(trim(nombre_pdf)) AS file_basename,
    fecha_de_publicacion,
    fecha_de_aparicion,
    eliminado
  FROM public.disposicion
  WHERE eliminado = false
    AND nombre_pdf IS NOT NULL
    AND trim(nombre_pdf) <> ''
),
doc AS (
  SELECT * FROM tenant_anmat.v_documents_file
)
SELECT
  disp.disposicion_id,
  disp.nombre_pdf,
  doc.document_name,
  doc.document_id,
  doc.chunk_rows,
  doc.created_at_min AS documents_created_at,
  disp.fecha_de_publicacion AS disposicion_fecha_publicacion,
  disp.fecha_de_aparicion AS disposicion_fecha_aparicion,
  (doc.created_at_min::date IS DISTINCT FROM disp.fecha_de_publicacion::date) AS diff_vs_publicacion,
  (doc.created_at_min::date IS DISTINCT FROM disp.fecha_de_aparicion::date) AS diff_vs_aparicion
FROM disp
INNER JOIN doc ON doc.file_basename = disp.file_basename
WHERE doc.created_at_min::date IS DISTINCT FROM disp.fecha_de_publicacion::date
   OR doc.created_at_min::date IS DISTINCT FROM disp.fecha_de_aparicion::date
ORDER BY disp.fecha_de_publicacion DESC;
```

### 4.2 Resumen de conteos

```sql
SELECT
  count(*) FILTER (WHERE matched AND date_mismatch_pub) AS discrepancias_fecha_publicacion,
  count(*) FILTER (WHERE matched AND date_mismatch_ap) AS discrepancias_fecha_aparicion,
  count(*) FILTER (WHERE NOT matched) AS disposicion_sin_documents,
  count(*) FILTER (WHERE doc_only) AS documents_sin_disposicion
FROM (
  -- implementar subconsulta unificada a partir de 4.1 + 4.3 + 4.4
) s;
```

---

## 5. SQL — Fase 2: identificar diferencias de cobertura (sin match / duplicados)

### 5.1 `disposicion` sin filas en `documents` (PDF nunca embedido o nombre distinto)

```sql
SELECT
  d.id,
  d.disposicion_id,
  d.nombre_pdf,
  d.fecha_de_publicacion
FROM public.disposicion d
WHERE d.eliminado = false
  AND d.nombre_pdf IS NOT NULL
  AND trim(d.nombre_pdf) <> ''
  AND NOT EXISTS (
    SELECT 1
    FROM tenant_anmat.v_documents_file v
    WHERE v.file_basename = lower(trim(d.nombre_pdf))
  )
ORDER BY d.fecha_de_publicacion DESC;
```

### 5.2 `documents` sin `disposicion` (migración, nombres legacy, boletín mezclado)

```sql
SELECT
  v.document_id,
  v.document_name,
  v.file_basename,
  v.created_at_min,
  v.chunk_rows
FROM tenant_anmat.v_documents_file v
WHERE NOT EXISTS (
  SELECT 1
  FROM public.disposicion d
  WHERE d.eliminado = false
    AND lower(trim(d.nombre_pdf)) = v.file_basename
)
ORDER BY v.created_at_min DESC;
```

### 5.3 Varias `disposicion` con el mismo `nombre_pdf` (colisión de clave)

```sql
SELECT
  lower(trim(nombre_pdf)) AS file_basename,
  count(*) AS disposicion_rows,
  array_agg(id ORDER BY fecha_de_publicacion DESC) AS disposicion_ids
FROM public.disposicion
WHERE eliminado = false
  AND nombre_pdf IS NOT NULL
GROUP BY 1
HAVING count(*) > 1;
```

**Regla v1:** si hay colisión, **no actualizar** automáticamente; exportar CSV y resolver manualmente (elegir `disposicion.id` canónico).

---

## 6. SQL — Fase 3: actualizar `created_at` (dry-run + apply)

### 6.1 Tabla de staging (recomendado)

```sql
CREATE TABLE IF NOT EXISTS tenant_anmat.documents_created_at_repair (
  document_id uuid PRIMARY KEY,
  file_basename text NOT NULL,
  disposicion_id integer NOT NULL,
  old_created_at timestamp NOT NULL,
  new_created_at timestamp NOT NULL,
  repaired_at timestamp NOT NULL DEFAULT now(),
  repair_run_id text NOT NULL
);
```

### 6.2 Poblar staging (dry-run)

```sql
-- repair_run_id: 'al03-20260520-001'
INSERT INTO tenant_anmat.documents_created_at_repair (
  document_id, file_basename, disposicion_id, old_created_at, new_created_at, repair_run_id
)
SELECT
  doc.document_id,
  doc.file_basename,
  disp.id AS disposicion_id,
  doc.created_at_min AS old_created_at,
  date_trunc('day', disp.fecha_de_publicacion)::timestamp AS new_created_at,
  'al03-20260520-001'
FROM tenant_anmat.v_documents_file doc
INNER JOIN (
  SELECT DISTINCT ON (lower(trim(nombre_pdf)))
    id, lower(trim(nombre_pdf)) AS file_basename, fecha_de_publicacion
  FROM public.disposicion
  WHERE eliminado = false AND nombre_pdf IS NOT NULL AND trim(nombre_pdf) <> ''
  ORDER BY lower(trim(nombre_pdf)), fecha_de_publicacion DESC
) disp ON disp.file_basename = doc.file_basename
WHERE doc.created_at_min IS DISTINCT FROM date_trunc('day', disp.fecha_de_publicacion)::timestamp
ON CONFLICT (document_id) DO NOTHING;
```

`DISTINCT ON (basename)` evita colisiones tomando la disposición más reciente; documentar si negocio prefiere otra regla.

### 6.3 UPDATE en `documents` (todos los chunks del mismo `document_id`)

```sql
BEGIN;

UPDATE tenant_anmat.documents d
SET created_at = r.new_created_at
FROM tenant_anmat.documents_created_at_repair r
WHERE d.document_id = r.document_id
  AND r.repair_run_id = 'al03-20260520-001'
  AND d.created_at IS DISTINCT FROM r.new_created_at;

-- Verificar filas afectadas
-- SELECT repair_run_id, count(*) FROM ... GROUP BY 1;

COMMIT;
-- ROLLBACK;  -- si el conteo no coincide con staging
```

### 6.4 Rollback por run

```sql
UPDATE tenant_anmat.documents d
SET created_at = r.old_created_at
FROM tenant_anmat.documents_created_at_repair r
WHERE d.document_id = r.document_id
  AND r.repair_run_id = 'al03-20260520-001';
```

---

## 7. Criterios de aceptación

| ID | Criterio |
|----|----------|
| CA-01 | Informe de **discrepancias** (4.1) generado en prod/QA antes del UPDATE. |
| CA-02 | Informe de **huérfanos** (5.1, 5.2) revisado; colisiones (5.3) = 0 o listadas. |
| CA-03 | Tras el repair, para cada par `(nombre_pdf, document_id)` emparejado: `documents.created_at::date = disposicion.fecha_de_publicacion::date` (o columna acordada). |
| CA-04 | Todos los chunks de un mismo `document_id` comparten el mismo `created_at` post-fix. |
| CA-05 | Batch ANMAT con `--created-at-start/end` del día de una disposición reciente devuelve `chunks_count > 0` cuando corresponda. |
| CA-06 | Tabla `documents_created_at_repair` permite rollback del run. |

---

## 8. Procedimiento operativo sugerido

1. **Backup** snapshot Aurora o export `SELECT` de filas afectadas.
2. Ejecutar **4.x** y **5.x** en QA; validar muestra manual (10 PDFs).
3. Poblar **staging** en prod con `repair_run_id` único.
4. Revisar `count(*)` staging vs expectativa (~filas únicas por `document_id`, no por chunk).
5. `BEGIN` → UPDATE → verificar → `COMMIT`.
6. Re-ejecutar batch ANMAT de prueba para un día con disposiciones conocidas.
7. (Opcional F2) Corregir ingesta para que futuros inserts usen fecha de `disposicion` o API ANMAT, no solo partición S3.

---

## 9. Prevención (issue follow-up)

| ID | Entregable |
|----|------------|
| **AL-03-F1** | Script SQL versionado en `scripts/sql/al03_repair_anmat_created_at.sql` (parametrizado). |
| **AL-03-F2** | En `rag_lmbd_embeddings` / migración S3: opción de setear `created_at` desde metadata de negocio si existe. |
| **AL-03-F3** | SFN ANMAT → pasar `fecha_de_publicacion` en metadata S3 al escribir el objeto. |

---

## 10. Riesgos

| Riesgo | Mitigación |
|--------|------------|
| Colisión mismo `nombre_pdf` | `DISTINCT ON` + lista manual; no UPDATE ciego |
| `document_name` sin basename igual a `nombre_pdf` | Informe 5.2; mapeo manual |
| TZ incorrecta al truncar día | Acordar UTC vs ART; probar con 2–3 casos conocidos |
| Índice `created_at` | UPDATE masivo fuera de horario pico; `VACUUM ANALYZE` si aplica |
| Múltiples `document_id` por mismo PDF (re-ingesta) | Agrupar por `file_basename`; posible dedupe BU-01 aparte |

---

## 11. Preguntas abiertas

1. ¿`created_at` debe tomar **`fecha_de_publicacion`** o **`fecha_de_aparicion`**?  
2. ¿Truncar a **medianoche UTC** o conservar **hora** del timestamp de disposición?  
3. ¿Actualizar también documentos cuya partición S3 (`YYYYMMDD`) deba cambiar en re-migración?  
4. ¿Alcance: solo ANMAT o también corpus ya migrados desde `alert-backend-prod` con otro patrón de nombre?

---

## 12. Referencias

| Área | Ubicación |
|------|-----------|
| Esquema `disposicion` | `feature/rag_lmbd_alert_creation-[env].md` |
| Parseo S3 → `created_at` | `apps/rag_lmbd_embeddings/s3_rag_key.py` |
| Filtro query por fecha | `apps/rag_lmbd_query/index.py` (`resolve_created_at_bounds`) |
| Matching batch | `scripts/alerts_semantic_matches.py`, `docs/AL-02-cobertura-temporal-alertas.md` |
