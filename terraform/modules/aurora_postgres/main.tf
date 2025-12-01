resource "aws_db_subnet_group" "this" {
  name       = "aurora-pg-subnets-${var.environment}"
  subnet_ids = var.subnets
}

resource "aws_security_group" "this" {
  name   = "aurora-pg-sg-${var.environment}"
  vpc_id = var.vpc_id

  ingress {
    from_port   = 5432
    to_port     = 5432
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"] # Ajustar para prod
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_rds_cluster" "this" {
  cluster_identifier     = "aurora-pg-${var.environment}"
  engine                 = "aurora-postgresql"
  engine_version         = var.engine_version
  database_name          = var.db_name

  master_username = var.master_username
  master_password = var.master_password

  db_subnet_group_name   = aws_db_subnet_group.this.name
  vpc_security_group_ids = [aws_security_group.this.id]

  storage_encrypted   = true
  skip_final_snapshot = true

  serverlessv2_scaling_configuration {
    min_capacity = var.min_capacity
    max_capacity = var.max_capacity
  }
}

resource "aws_rds_cluster_instance" "this" {
  identifier         = "aurora-pg-${var.environment}-instance"
  cluster_identifier = aws_rds_cluster.this.id
  instance_class     = "db.serverless"
  engine             = "aurora-postgresql"
  engine_version     = var.engine_version
}
