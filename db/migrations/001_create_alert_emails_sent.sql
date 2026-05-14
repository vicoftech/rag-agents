-- Migration: AL-02 - Tabla de idempotencia para prevenir emails duplicados
-- Fecha: 2026-05-13
-- Autor: Claude Sonnet 4.5
-- Descripción: Crea tabla para registrar emails enviados y prevenir duplicados

-- Crear tabla de emails enviados
CREATE TABLE IF NOT EXISTS alert_emails_sent (
    id BIGSERIAL PRIMARY KEY,
    alert_id BIGINT NOT NULL,
    recipient_email VARCHAR(255) NOT NULL,
    sent_date DATE NOT NULL DEFAULT CURRENT_DATE,
    template_name VARCHAR(100) NOT NULL DEFAULT 'alert_aviso',
    sent_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- Metadata adicional
    corrida_label VARCHAR(50),  -- anmat, boletin
    chunks_count INTEGER,

    -- Constraint de idempotencia: una alerta solo se envía una vez por día a cada destinatario
    CONSTRAINT uq_alert_email_sent_per_day
        UNIQUE (alert_id, recipient_email, sent_date)
);

-- Índice para búsquedas rápidas de duplicados
CREATE INDEX IF NOT EXISTS idx_alert_emails_sent_lookup
    ON alert_emails_sent(alert_id, recipient_email, sent_date);

-- Índice para limpieza de datos antiguos
CREATE INDEX IF NOT EXISTS idx_alert_emails_sent_cleanup
    ON alert_emails_sent(sent_date);

-- Comentarios en tabla y columnas
COMMENT ON TABLE alert_emails_sent IS
'Registro de emails de alertas enviados. Previene duplicados mediante constraint UNIQUE.';

COMMENT ON COLUMN alert_emails_sent.alert_id IS
'ID de la alerta generada (relación con tabla alerta_generada)';

COMMENT ON COLUMN alert_emails_sent.recipient_email IS
'Email del destinatario de la notificación';

COMMENT ON COLUMN alert_emails_sent.sent_date IS
'Fecha de envío (solo fecha, sin hora). Parte de la constraint de idempotencia.';

COMMENT ON COLUMN alert_emails_sent.template_name IS
'Nombre del template SES usado (normalmente "alert_aviso")';

COMMENT ON COLUMN alert_emails_sent.sent_at IS
'Timestamp exacto del envío (incluye hora)';

COMMENT ON CONSTRAINT uq_alert_email_sent_per_day ON alert_emails_sent IS
'Idempotencia: una alerta solo puede enviarse una vez por día a cada email';
