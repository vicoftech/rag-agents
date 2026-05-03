# Backend remoto — cuenta 913123310997, perfil asap_main (PROD).
# Estado por workspace: env:/prod/rag-agents/prod/terraform.tfstate
#
#   cd terraform
#   terraform init -reconfigure -backend-config=environments/backend-prod-913.hcl
#   terraform workspace select prod
#   terraform plan -var-file=environments/prod.tfvars

bucket         = "rag-agents-terraform-state-913123310997"
key            = "rag-agents/prod/terraform.tfstate"
region         = "us-east-1"
encrypt        = true
dynamodb_table = "rag-agents-terraform-locks-913123310997"
profile        = "asap_main"
