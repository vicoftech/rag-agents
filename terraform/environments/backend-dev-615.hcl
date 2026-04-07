# Backend remoto — cuenta 615216531593, perfil asap_dev (dev).
# Uso: terraform init -reconfigure -backend-config=environments/backend-dev-615.hcl

bucket         = "rag-agents-terraform-state-615216531593"
key            = "rag-agents/terraform.tfstate"
region         = "us-east-1"
encrypt        = true
dynamodb_table = "rag-agents-terraform-locks"
profile        = "asap_dev"
