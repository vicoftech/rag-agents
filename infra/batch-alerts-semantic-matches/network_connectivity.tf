# Conectividad Fargate batch → Secrets Manager VPCE, Aurora y S3.
# S3: Gateway endpoint en la VPC (prefix list); el SG del batch no requiere regla extra.
# Secrets/Textract: Interface VPCE con SG rag-vpce-if-* (antes solo Lambdas RAG).

data "aws_security_group" "rag_vpce_interface" {
  count = var.rag_vpce_interface_security_group_id == "" ? 1 : 0

  filter {
    name   = "group-name"
    values = ["rag-vpce-if-${var.rag_vpce_environment_suffix}-sg"]
  }
  filter {
    name   = "vpc-id"
    values = [var.vpc_id]
  }
}

locals {
  rag_vpce_interface_sg_id = (
    var.rag_vpce_interface_security_group_id != ""
    ? var.rag_vpce_interface_security_group_id
    : data.aws_security_group.rag_vpce_interface[0].id
  )
}

resource "aws_vpc_security_group_ingress_rule" "vpce_interface_from_batch" {
  security_group_id            = local.rag_vpce_interface_sg_id
  referenced_security_group_id = aws_security_group.batch.id
  ip_protocol                  = "tcp"
  from_port                    = 443
  to_port                      = 443
  description                  = "HTTPS desde ECS batch (Secrets Manager, Textract VPCE)"
}

resource "aws_vpc_security_group_ingress_rule" "rds_from_batch" {
  count = var.db_security_group_id != "" ? 1 : 0

  security_group_id            = var.db_security_group_id
  referenced_security_group_id = aws_security_group.batch.id
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
  description                  = "PostgreSQL desde ECS batch (rekey ANMAT, etc.)"
}
