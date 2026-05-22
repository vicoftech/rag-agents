-- AL-03: Desglose de PDFs en documents SIN fecha en v_disposicion_fecha_por_archivo (~9100)

-- Nombre de archivo en documents (misma regla que el repair)
-- trim(regexp_replace(document_name, '^.*/', ''))

-- -----------------------------------------------------------------------------
-- A) Total sin entrada en la vista (lo que ya corriste)
-- -----------------------------------------------------------------------------
SELECT count(DISTINCT trim(regexp_replace(document_name, '^.*/', ''))) AS sin_vista
FROM tenant_anmat.documents doc
WHERE NOT EXISTS (
    SELECT 1 FROM tenant_anmat.v_disposicion_fecha_por_archivo c
    WHERE c.archivo = trim(regexp_replace(doc.document_name, '^.*/', ''))
);

-- -----------------------------------------------------------------------------
-- B) ¿Existe en disposicion por nombre pero fechayhora_revision es NULL?
--     (el PDF está en alertas pero sin fecha de revisión)
-- -----------------------------------------------------------------------------
SELECT count(DISTINCT trim(regexp_replace(doc.document_name, '^.*/', ''))) AS match_nombre_revision_null
FROM tenant_anmat.documents doc
INNER JOIN public.disposicion d
    ON trim(d.nombre_pdf) = trim(regexp_replace(doc.document_name, '^.*/', ''))
WHERE coalesce(d.eliminado, false) = false
  AND d.nombre_pdf IS NOT NULL
  AND NOT EXISTS (
      SELECT 1 FROM tenant_anmat.v_disposicion_fecha_por_archivo c
      WHERE c.archivo = trim(regexp_replace(doc.document_name, '^.*/', ''))
  );

-- -----------------------------------------------------------------------------
-- C) ¿No existe ninguna fila en disposicion con ese nombre_pdf?
--     (típico: migración masiva S3 / nombres distintos)
-- -----------------------------------------------------------------------------
SELECT count(DISTINCT trim(regexp_replace(doc.document_name, '^.*/', ''))) AS sin_match_nombre
FROM tenant_anmat.documents doc
WHERE NOT EXISTS (
    SELECT 1 FROM public.disposicion d
    WHERE coalesce(d.eliminado, false) = false
      AND trim(d.nombre_pdf) = trim(regexp_replace(doc.document_name, '^.*/', ''))
);

-- -----------------------------------------------------------------------------
-- D) Resumen en una fila (B + C deberían explicar ~9100)
-- -----------------------------------------------------------------------------
SELECT
    (SELECT count(DISTINCT trim(regexp_replace(document_name, '^.*/', '')))
     FROM tenant_anmat.documents doc
     WHERE NOT EXISTS (
         SELECT 1 FROM tenant_anmat.v_disposicion_fecha_por_archivo c
         WHERE c.archivo = trim(regexp_replace(doc.document_name, '^.*/', ''))
     )) AS sin_vista_total,
    (SELECT count(DISTINCT trim(regexp_replace(doc.document_name, '^.*/', '')))
     FROM tenant_anmat.documents doc
     INNER JOIN public.disposicion d
       ON trim(d.nombre_pdf) = trim(regexp_replace(doc.document_name, '^.*/', ''))
     WHERE coalesce(d.eliminado, false) = false
       AND NOT EXISTS (
           SELECT 1 FROM tenant_anmat.v_disposicion_fecha_por_archivo c
           WHERE c.archivo = trim(regexp_replace(doc.document_name, '^.*/', ''))
     )) AS con_disposicion_sin_fecha_revision,
    (SELECT count(DISTINCT trim(regexp_replace(doc.document_name, '^.*/', '')))
     FROM tenant_anmat.documents doc
     WHERE NOT EXISTS (
         SELECT 1 FROM public.disposicion d
         WHERE coalesce(d.eliminado, false) = false
           AND trim(d.nombre_pdf) = trim(regexp_replace(doc.document_name, '^.*/', ''))
     )) AS sin_disposicion_por_nombre;

-- -----------------------------------------------------------------------------
-- E) Muestra 20 archivos sin disposicion (para ver patrón de nombre)
-- -----------------------------------------------------------------------------
SELECT DISTINCT trim(regexp_replace(doc.document_name, '^.*/', '')) AS archivo
FROM tenant_anmat.documents doc
WHERE NOT EXISTS (
    SELECT 1 FROM public.disposicion d
    WHERE coalesce(d.eliminado, false) = false
      AND trim(d.nombre_pdf) = trim(regexp_replace(doc.document_name, '^.*/', ''))
)
LIMIT 20;

-- -----------------------------------------------------------------------------
-- F) Alternativa para B: usar fecha_de_publicacion si revision es NULL
--     (solo preview; no ejecutar UPDATE sin validar con negocio)
-- -----------------------------------------------------------------------------
SELECT count(DISTINCT trim(regexp_replace(doc.document_name, '^.*/', ''))) AS podrian_usar_fecha_publicacion
FROM tenant_anmat.documents doc
INNER JOIN (
    SELECT
        trim(nombre_pdf) AS archivo,
        max(fecha_de_publicacion) FILTER (WHERE fechayhora_revision IS NULL) AS solo_pub,
        max(fechayhora_revision) AS tiene_revision
    FROM public.disposicion
    WHERE coalesce(eliminado, false) = false
      AND nombre_pdf IS NOT NULL AND trim(nombre_pdf) <> ''
    GROUP BY trim(nombre_pdf)
    HAVING max(fechayhora_revision) IS NULL
       AND max(fecha_de_publicacion) IS NOT NULL
) d ON d.archivo = trim(regexp_replace(doc.document_name, '^.*/', ''))
WHERE NOT EXISTS (
    SELECT 1 FROM tenant_anmat.v_disposicion_fecha_por_archivo c
    WHERE c.archivo = trim(regexp_replace(doc.document_name, '^.*/', ''))
);
