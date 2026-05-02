# Prompt: subir `maintenance_work_mem` en Aurora (otro stack / Terraform dueño del RDS)

Copiá el bloque de abajo en el agente del **repositorio que crea y administra el cluster Aurora PostgreSQL** (no en rag-agents si la base vive en otro stack).

---

## Prompt (copiar desde aquí)

Necesito subir el parámetro de PostgreSQL **`maintenance_work_mem`** en nuestro **Amazon Aurora PostgreSQL** porque las migraciones fallan con:

`ERROR: memory required is 65 MB, maintenance_work_mem is 64 MB`

Eso pasa al construir índices (GIN full-text, HNSW vector, u otras operaciones de mantenimiento). El default de Aurora en instancias chicas suele ser **65536 kB = 64 MB**.

**Objetivo:** que el cluster use un **custom DB cluster parameter group** con `maintenance_work_mem` al menos **256 MB** (262144 kB), o **512 MB** (524288 kB) si hay tablas muy grandes.

**Restricciones:**

- En la consola de AWS/RDS, `maintenance_work_mem` se configura en **kilobytes (kB)**.
- El **`family`** del `aws_rds_cluster_parameter_group` debe coincidir con el motor, p. ej. motor `15.3` → `aurora-postgresql15`, `14.11` → `aurora-postgresql14`.
- Hay que asociar el parameter group al recurso correcto: en Aurora PostgreSQL casi siempre **`db_cluster_parameter_group_name`** en **`aws_rds_cluster`** (no confundir con parameter group solo de instancia si el diseño del proyecto lo separa).
- Preferí **Terraform** alineado al estilo del repo (nombres de recursos, variables, `terraform fmt`). Si el cluster ya existe, el plan debería ser **modify in place** al cambiar `db_cluster_parameter_group_name`; revisar si AWS marca **pending-reboot** y documentar si hace falta reinicio del writer.
- Exponer una **variable** (ej. `maintenance_work_mem_kb` o nombre que use el proyecto) con default **262144**, para poder subir a 524288 sin tocar código.
- No romper otros parámetros del cluster: si ya hay un custom cluster parameter group, **agregar** el parámetro ahí o **fusionar** recursos en lugar de crear un segundo grupo incompatible.

**Entregables:** cambios concretos en los `.tf` (y `.tfvars` de ejemplo si aplica), y una línea de verificación con SQL: `SHOW maintenance_work_mem;` después del apply.

Buscá en este repo dónde está definido `aws_rds_cluster` (o el módulo equivalente) y aplicá el cambio ahí.

---

## Prompt (hasta aquí)
