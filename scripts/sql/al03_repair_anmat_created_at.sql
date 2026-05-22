-- =============================================================================
-- AL-03 (simplificado): created_at en tenant_anmat.documents
-- Clave: trim(nombre_pdf) = basename(document_name)  [después del último "/"]
-- Fecha: max(disposicion.fechayhora_revision) por archivo → documents.created_at
-- =============================================================================

-- -----------------------------------------------------------------------------
-- Utilidad: misma extracción de nombre en todo el script
-- -----------------------------------------------------------------------------
-- documents: trim(regexp_replace(document_name, '^.*/', ''))
-- disposicion: trim(nombre_pdf)

-- -----------------------------------------------------------------------------
-- PASO 1a — Solo en disposicion
-- -----------------------------------------------------------------------------
SELECT trim(d.nombre_pdf) AS archivo, d.id, d.disposicion_id, d.fechayhora_revision
FROM public.disposicion d
WHERE coalesce(d.eliminado, false) = false
  AND d.nombre_pdf IS NOT NULL AND trim(d.nombre_pdf) <> ''
  AND NOT EXISTS (
      SELECT 1 FROM tenant_anmat.documents doc
      WHERE trim(regexp_replace(doc.document_name, '^.*/', '')) = trim(d.nombre_pdf)
  )
ORDER BY d.fechayhora_revision DESC NULLS LAST;

-- -----------------------------------------------------------------------------
-- PASO 1b — Solo en documents
-- -----------------------------------------------------------------------------
SELECT DISTINCT
    trim(regexp_replace(doc.document_name, '^.*/', '')) AS archivo,
    doc.document_id,
    min(doc.created_at) AS created_at_min
FROM tenant_anmat.documents doc
WHERE NOT EXISTS (
    SELECT 1 FROM public.disposicion d
    WHERE coalesce(d.eliminado, false) = false
      AND trim(d.nombre_pdf) = trim(regexp_replace(doc.document_name, '^.*/', ''))
)
GROUP BY 1, 2
ORDER BY created_at_min DESC NULLS LAST;

-- -----------------------------------------------------------------------------
-- PASO 2 — Fecha canónica por archivo (igual que el UPDATE)
-- -----------------------------------------------------------------------------
-- Una fila por PDF: la revisión más reciente en disposicion
CREATE OR REPLACE VIEW tenant_anmat.v_disposicion_fecha_por_archivo AS
SELECT
    trim(nombre_pdf) AS archivo,
    max(fechayhora_revision) AS fechayhora_revision,
    count(*) AS filas_disposicion
FROM public.disposicion
WHERE coalesce(eliminado, false) = false
  AND nombre_pdf IS NOT NULL
  AND trim(nombre_pdf) <> ''
  AND fechayhora_revision IS NOT NULL
GROUP BY trim(nombre_pdf);

-- -----------------------------------------------------------------------------
-- PASO 2a — VERIFICACIÓN CORRECTA (usar esta, no el join 1:N viejo)
-- Documentos que AÚN no tienen created_at = fecha canónica del PDF
-- -----------------------------------------------------------------------------
SELECT
    c.archivo,
    c.fechayhora_revision AS fecha_canonica,
    c.filas_disposicion,
    df.document_id,
    df.created_at_min,
    df.created_at_max,
    df.chunk_rows
FROM tenant_anmat.v_disposicion_fecha_por_archivo c
INNER JOIN (
    SELECT
        trim(regexp_replace(document_name, '^.*/', '')) AS archivo,
        document_id,
        min(created_at) AS created_at_min,
        max(created_at) AS created_at_max,
        count(*) AS chunk_rows
    FROM tenant_anmat.documents
    GROUP BY 1, 2
) df ON df.archivo = c.archivo
WHERE df.created_at_min IS DISTINCT FROM c.fechayhora_revision
   OR df.created_at_max IS DISTINCT FROM c.fechayhora_revision
ORDER BY c.fechayhora_revision DESC NULLS LAST;

-- -----------------------------------------------------------------------------
-- PASO 2b — Conteo real pendiente (debería → 0 tras UPDATE bien hecho)
-- -----------------------------------------------------------------------------
SELECT
    count(DISTINCT df.document_id) AS documentos_pendientes,
    sum(df.chunk_rows) AS chunks_pendientes
FROM tenant_anmat.v_disposicion_fecha_por_archivo c
INNER JOIN (
    SELECT
        trim(regexp_replace(document_name, '^.*/', '')) AS archivo,
        document_id,
        count(*) AS chunk_rows,
        min(created_at) AS created_at_min,
        max(created_at) AS created_at_max
    FROM tenant_anmat.documents
    GROUP BY 1, 2
) df ON df.archivo = c.archivo
WHERE df.created_at_min IS DISTINCT FROM c.fechayhora_revision
   OR df.created_at_max IS DISTINCT FROM c.fechayhora_revision;

-- -----------------------------------------------------------------------------
-- PASO 2c — ¿Por qué el query viejo muestra ~926 aunque el UPDATE corrió?
-- Filas “fantasma”: mismo PDF, otra fila disposicion con otra fechayhora_revision
-- -----------------------------------------------------------------------------
SELECT count(*) AS filas_fantasma_query_viejo
FROM public.disposicion d
INNER JOIN tenant_anmat.documents doc
    ON trim(regexp_replace(doc.document_name, '^.*/', '')) = trim(d.nombre_pdf)
INNER JOIN tenant_anmat.v_disposicion_fecha_por_archivo c
    ON c.archivo = trim(d.nombre_pdf)
WHERE coalesce(d.eliminado, false) = false
  AND d.fechayhora_revision IS NOT NULL
  AND doc.created_at IS NOT DISTINCT FROM c.fechayhora_revision   -- chunks YA bien
  AND d.fechayhora_revision IS DISTINCT FROM c.fechayhora_revision; -- esta fila disp es otra fecha

-- -----------------------------------------------------------------------------
-- PASO 2d — Otras causas si 2b sigue > 0
-- -----------------------------------------------------------------------------
-- d1) PDF en documents sin fechayhora_revision en disposicion (solo NULL)
SELECT count(DISTINCT trim(regexp_replace(document_name, '^.*/', ''))) AS archivos_sin_fecha_revision
FROM tenant_anmat.documents doc
WHERE NOT EXISTS (
    SELECT 1 FROM tenant_anmat.v_disposicion_fecha_por_archivo c
    WHERE c.archivo = trim(regexp_replace(doc.document_name, '^.*/', ''))
);

-- d2) Chunks del mismo document_id con created_at distinto entre sí
SELECT count(*) AS document_ids_con_chunks_inconsistentes
FROM (
    SELECT document_id
    FROM tenant_anmat.documents
    GROUP BY document_id
    HAVING count(DISTINCT created_at) > 1
) x;

-- -----------------------------------------------------------------------------
-- PASO 3 — UPDATE (forzar todos los chunks del PDF a la fecha canónica)
-- -----------------------------------------------------------------------------
BEGIN;

UPDATE tenant_anmat.documents doc
SET created_at = c.fechayhora_revision
FROM tenant_anmat.v_disposicion_fecha_por_archivo c
WHERE trim(regexp_replace(doc.document_name, '^.*/', '')) = c.archivo;

-- Sin filtro IS DISTINCT FROM: idempotente y corrige chunks desparejos
-- Ver: SELECT count(*) FROM paso 2b; luego COMMIT o ROLLBACK

COMMIT;

-- -----------------------------------------------------------------------------
-- PASO 4 — Post-check: solo PASO 2b (no el 2a viejo con join a cada disposicion)
-- -----------------------------------------------------------------------------
