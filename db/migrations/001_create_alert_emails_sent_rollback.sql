-- Rollback Migration: AL-02 - Tabla de idempotencia
-- Fecha: 2026-05-13
-- Descripción: Revierte la creación de la tabla alert_emails_sent

-- Eliminar índices (por si acaso no se eliminan con DROP TABLE CASCADE)
DROP INDEX IF EXISTS idx_alert_emails_sent_lookup;
DROP INDEX IF EXISTS idx_alert_emails_sent_cleanup;

-- Eliminar tabla
DROP TABLE IF EXISTS alert_emails_sent CASCADE;
