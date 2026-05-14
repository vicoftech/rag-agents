# Database Migrations - rag-agents

Este directorio contiene las migraciones de base de datos para el sistema rag-agents.

---

## Orden de Ejecución

Las migraciones deben ejecutarse en orden numérico ascendente.

| Número | Nombre | Fecha | Descripción | Estado |
|--------|--------|-------|-------------|--------|
| 001 | create_alert_emails_sent | 2026-05-13 | Tabla de idempotencia para prevenir emails duplicados (AL-02) | ✅ Lista |

---

## Cómo Aplicar una Migración

### Conexión a PostgreSQL

```bash
# Ambiente local
psql -h localhost -U postgres -d alert_db

# Ambiente prod (ejemplo)
psql -h <RDS_ENDPOINT> -U <DB_USER> -d alert_prod
```

### Ejecutar Migración

```bash
# Ejecutar migration
psql -h localhost -U postgres -d alert_db -f db/migrations/001_create_alert_emails_sent.sql

# Verificar que se creó la tabla
psql -h localhost -U postgres -d alert_db -c "\d alert_emails_sent"
```

### Rollback de Migración

```bash
# Revertir migration
psql -h localhost -U postgres -d alert_db -f db/migrations/001_create_alert_emails_sent_rollback.sql
```

---

## Verificación Post-Migración

### 001_create_alert_emails_sent

```sql
-- Verificar que la tabla existe
SELECT table_name, table_type
FROM information_schema.tables
WHERE table_name = 'alert_emails_sent';

-- Verificar estructura
\d alert_emails_sent

-- Verificar constraint de idempotencia
SELECT constraint_name, constraint_type
FROM information_schema.table_constraints
WHERE table_name = 'alert_emails_sent';

-- Verificar índices
SELECT indexname, indexdef
FROM pg_indexes
WHERE tablename = 'alert_emails_sent';
```

---

## Formato de Archivos

- **Migrations:** `<numero>_<nombre_descriptivo>.sql`
- **Rollbacks:** `<numero>_<nombre_descriptivo>_rollback.sql`
- Cada migration debe tener su rollback correspondiente

---

## Política de Migraciones

1. **Nunca modificar migrations aplicadas** - Crear nueva migration en su lugar
2. **Siempre incluir rollback** - Facilita revertir en caso de error
3. **Usar `IF NOT EXISTS`** - Permite re-ejecutar migrations sin errores
4. **Documentar cada migration** - Comentarios SQL explicando propósito
5. **Testar en local primero** - Nunca ejecutar directamente en producción

---

**Última actualización:** 2026-05-13
**Mantenido por:** Claude Sonnet 4.5
