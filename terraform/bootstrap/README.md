# Bootstrap: backend remoto Terraform

Crea el bucket S3 y la tabla DynamoDB para el estado del proyecto **rag-agents** (cuenta 615216531593, perfil `asap_dev` por defecto).

## Requisitos

- AWS CLI configurado (`asap_dev`).
- Ejecutar **una sola vez** por cuenta/región.

## Pasos

```powershell
cd terraform/bootstrap
terraform init
terraform apply -auto-approve
```

Este módulo usa **estado local** (`terraform.tfstate` en esta carpeta); no commitees ese archivo si contiene datos sensibles.

Después, en el directorio `terraform/` del proyecto raíz:

```powershell
cd ..
# Si venías de otro backend o state local antiguo, elimina o renombra terraform.tfstate
terraform init -reconfigure
terraform workspace new dev   # opcional
terraform apply -var-file=environments/asap_dev_615.tfvars -auto-approve
```

Ver también `environments/asap_dev_615.tfvars` y la raíz `terraform/main.tf` (bloque `backend "s3"`).

## QA (cuenta 913, perfil `asap_main`)

1. Crear bucket + tabla DynamoDB en 913:

```powershell
cd terraform/bootstrap
terraform init
terraform apply -var-file=terraform.qa_913.tfvars -auto-approve
```

2. En `terraform/` del raíz, apuntar el backend a QA y aplicar:

```powershell
cd ..
terraform init -reconfigure -backend-config=environments/backend-qa-913.hcl
terraform apply -var-file=environments/asap_main_qa_913.tfvars
```

Para volver a **dev (615)**:

```powershell
terraform init -reconfigure -backend-config=environments/backend-dev-615.hcl
```
