# Backend remoto — cuenta 913123310997, perfil asap_main (QA).
# Uso: desde terraform/
#   terraform init -reconfigure -backend-config=environments/backend-qa-913.hcl

bucket         = "rag-agents-terraform-state-913123310997"
key            = "rag-agents/qa/terraform.tfstate"
region         = "us-east-1"
encrypt        = true
dynamodb_table = "rag-agents-terraform-locks-913123310997"
profile        = "asap_main"
