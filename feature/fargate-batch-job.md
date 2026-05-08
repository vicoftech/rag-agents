# AWS Fargate Scheduled Batch Job — `alerts_semantic_matches.py`

Infrastructure and CI/CD pipeline for running `alerts_semantic_matches.py` on a daily schedule using ECS Fargate. The script receives the current date and the previous day as arguments at runtime. Compute costs are incurred only while the task is running — no persistent infrastructure beyond free-tier ECS cluster and task definitions.

---

## Architecture

```
EventBridge Scheduler (cron)
        │
        ▼
ECS Cluster (Fargate)
        │
        ▼
Fargate Task (runs → exits)
  ├── ECR image (Python script)
  ├── CloudWatch Logs
  └── IAM Task Role (your permissions)
```

**Cost model:** You pay only for vCPU and memory seconds while the container is running. The ECS Cluster, Task Definition, and EventBridge Scheduler have no cost when idle.

---

## Project Structure

```
/
├── infra/
│   ├── main.tf              # Provider, backend, data sources
│   ├── versions.tf          # Terraform and provider version constraints
│   ├── variables.tf         # All input variables
│   ├── terraform.tfvars     # Your values (fill before running)
│   ├── outputs.tf           # Key ARNs and names
│   ├── ecr.tf               # ECR repository + lifecycle policy
│   ├── ecs.tf               # ECS Cluster, Task Definition, Security Group, CloudWatch
│   ├── scheduler.tf         # EventBridge Scheduler + schedule group
│   └── iam.tf               # Four IAM roles (task exec, task, scheduler, GitHub OIDC)
├── app/
│   ├── alerts_semantic_matches.py   # batch script — receives --date-from and --date-to at runtime
│   ├── requirements.txt             # Python dependencies
│   └── Dockerfile
└── .github/
    └── workflows/
        └── deploy.yml       # Build → push ECR → update scheduler
```

---

## Prerequisites

| Tool | Minimum Version | Notes |
|------|----------------|-------|
| Terraform | >= 1.5 | |
| AWS CLI | >= 2.x | Configured with admin credentials |
| Docker | any | For local builds |
| Python | 3.12 | Matches the container runtime |

**AWS prerequisites:**
- VPC with private subnets (or public subnets with `assign_public_ip = true`)
- NAT Gateway (if using private subnets — required for ECR pulls)
- S3 bucket for Terraform state
- DynamoDB table for state locking
- GitHub OIDC provider configured in the AWS account (see [GitHub docs](https://docs.github.com/en/actions/security-for-github-actions/security-hardening-your-deployments/configuring-openid-connect-in-amazon-web-services))

---

## Deployment Guide

### 1. Add your Python script

Copy `alerts_semantic_matches.py` to the `app/` directory and populate `requirements.txt` with its dependencies.

```bash
cp /path/to/alerts_semantic_matches.py app/
pip freeze > app/requirements.txt   # or write requirements.txt manually
```

The script must accept `--date-from` and `--date-to` as CLI arguments. The Dockerfile injects these dynamically at container startup using a shell entrypoint (see the Dockerfile section below). If the script already uses `argparse`, no changes are needed — just ensure the argument names match.

### 2. Configure Terraform variables

Edit `infra/terraform.tfvars` with your values:

```hcl
project_name       = "my-batch-job"
environment        = "prod"
aws_region         = "us-east-1"
aws_account_id     = "123456789012"

# Cron schedule — runs at 03:00 UTC every day
schedule_cron      = "cron(0 3 * * ? *)"

# Fargate sizing — 512 CPU / 1024 MB is the minimum viable
task_cpu           = 512
task_memory        = 1024

# Networking — use your existing VPC
vpc_id             = "vpc-xxxxxxxxxxxxxxxxx"
private_subnet_ids = ["subnet-xxxxxxxxxxxxxxxxx", "subnet-yyyyyyyyyyyyyyyyy"]
assign_public_ip   = false   # set true if using public subnets without NAT

# GitHub OIDC — format: "org/repo-name"
github_repo        = "myorg/my-batch-repo"
```

**CPU / Memory combinations (Fargate limits):**

| CPU units | Valid memory values |
|-----------|-------------------|
| 256 | 512 MB – 2 GB |
| 512 | 1 GB – 4 GB |
| 1024 | 2 GB – 8 GB |
| 2048 | 4 GB – 16 GB |
| 4096 | 8 GB – 30 GB |

### 3. Configure Terraform backend

Edit the backend block in `infra/main.tf`:

```hcl
terraform {
  backend "s3" {
    bucket         = "your-terraform-state-bucket"
    key            = "batch-job/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "your-terraform-lock-table"
    encrypt        = true
  }
}
```

### 4. Deploy the infrastructure

```bash
cd infra

terraform init
terraform plan
terraform apply
```

After `apply` completes, note the outputs — you'll need them for the next steps:

```bash
terraform output
```

## Dockerfile

The entrypoint is a shell script that computes `date-from` (yesterday) and `date-to` (today) at container startup and passes them to the script as arguments. This way the dates are always relative to the moment the Fargate task runs, regardless of when the image was built.

```dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY alerts_semantic_matches.py .

# Non-root user for security
RUN adduser --disabled-password --gecos "" appuser
USER appuser

# Shell entrypoint: compute yesterday and today at runtime, pass as args
ENTRYPOINT ["sh", "-c", "\
  DATE_TO=$(date -u +%Y-%m-%d) && \
  DATE_FROM=$(date -u -d 'yesterday' +%Y-%m-%d) && \
  echo \"Running for date-from=$DATE_FROM date-to=$DATE_TO\" && \
  exec python alerts_semantic_matches.py --date-from \"$DATE_FROM\" --date-to \"$DATE_TO\" \
"]
```

> **Alpine vs slim:** `python:3.12-slim` uses Debian's `date -d` syntax (GNU coreutils). If you switch to `python:3.12-alpine`, replace `date -d 'yesterday'` with `date -d @$(($(date +%s) - 86400))` — BusyBox does not support the `-d yesterday` shorthand.

**Expected script interface (`argparse`):**

```python
import argparse

parser = argparse.ArgumentParser()
parser.add_argument("--date-from", required=True)  # e.g. 2026-05-07
parser.add_argument("--date-to",   required=True)  # e.g. 2026-05-08
args = parser.parse_args()
```

---



### 5. Build and push the initial Docker image

Before the GitHub Actions pipeline runs for the first time, do an initial push manually:

```bash
# Get the ECR URL from Terraform output
ECR_URL=$(terraform output -raw ecr_repository_url)
AWS_REGION="us-east-1"   # match your region

# Authenticate Docker to ECR
aws ecr get-login-password --region $AWS_REGION | \
  docker login --username AWS --password-stdin $ECR_URL

# Build and push
docker build -t $ECR_URL:latest ./app
docker push $ECR_URL:latest
```

To validate the image locally before pushing (dates are computed at runtime):

```bash
docker run --rm $ECR_URL:latest
# Expected output: Running for date-from=YYYY-MM-DD date-to=YYYY-MM-DD
```

### 6. Configure GitHub secrets

In your GitHub repository → Settings → Secrets and variables → Actions, add:

| Secret | Value |
|--------|-------|
| `AWS_ROLE_ARN` | Value of `terraform output github_actions_role_arn` |

Then set the environment variables at the top of `.github/workflows/deploy.yml`:

```yaml
env:
  AWS_REGION: us-east-1
  ECR_REPO: <value of terraform output ecr_repository_url>
  ECS_CLUSTER: <value of terraform output ecs_cluster_name>
  TASK_FAMILY: <value of terraform output task_definition_family>
  TASK_EXEC_ROLE_ARN: <value of terraform output task_execution_role_arn>
  TASK_ROLE_ARN: <value of terraform output task_role_arn>
```

### 7. Verify the schedule

The scheduler is created in `ENABLED` state. To confirm it's active:

```bash
aws scheduler get-schedule \
  --group-name my-batch-job-prod \
  --name my-batch-job-prod-batch \
  --region us-east-1
```

To trigger a manual run immediately (without waiting for the cron):

```bash
aws ecs run-task \
  --cluster my-batch-job-prod \
  --task-definition my-batch-job-prod \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[subnet-xxx],securityGroups=[sg-xxx],assignPublicIp=DISABLED}" \
  --region us-east-1
```

---

## Cron Schedule Reference

EventBridge uses a 6-field cron with a mandatory `?` for either day-of-month or day-of-week (not both).

```
cron(Minutes Hours Day-of-month Month Day-of-week Year)
```

| Expression | Meaning |
|-----------|---------|
| `cron(0 3 * * ? *)` | Every day at 03:00 UTC |
| `cron(0 8 ? * MON-FRI *)` | Weekdays at 08:00 UTC |
| `cron(0 0 1 * ? *)` | First day of each month at midnight UTC |
| `cron(30 6 ? * MON *)` | Every Monday at 06:30 UTC |
| `cron(0 */6 * * ? *)` | Every 6 hours |

> **Timezone:** EventBridge cron always runs in UTC. Argentina (ART) is UTC-3, so to run at midnight ART use `cron(0 3 * * ? *)`. There is no daylight saving in Argentina, so this offset is constant year-round.

---

## Adding Permissions to the Batch Script

The `ecs-task-role` is created with no policies by default. Add permissions based on what your script needs:

### Access to S3

```hcl
# Add to infra/iam.tf inside the task role inline policy

{
  Effect   = "Allow"
  Action   = ["s3:GetObject", "s3:PutObject", "s3:ListBucket"]
  Resource = [
    "arn:aws:s3:::your-bucket-name",
    "arn:aws:s3:::your-bucket-name/*"
  ]
}
```

### Access to Secrets Manager

```hcl
{
  Effect   = "Allow"
  Action   = ["secretsmanager:GetSecretValue"]
  Resource = "arn:aws:secretsmanager:us-east-1:123456789012:secret:my-secret-*"
}
```

### Access to RDS / Aurora

For Aurora, grant access at the database level (not IAM) using a Secrets Manager secret, and give the task role `secretsmanager:GetSecretValue` on that secret. For IAM database authentication:

```hcl
{
  Effect   = "Allow"
  Action   = ["rds-db:connect"]
  Resource = "arn:aws:rds-db:us-east-1:123456789012:dbuser:*/your-db-user"
}
```

After editing `iam.tf`, run `terraform apply` to update the role.

---

## CI/CD Pipeline

The GitHub Actions workflow triggers on every push to `main` that changes files under `app/`. It:

1. Authenticates to AWS via OIDC (no long-lived access keys)
2. Builds the Docker image with layer caching (GitHub Actions cache)
3. Pushes two tags: `:latest` and `:{git-sha}`
4. Registers a new ECS Task Definition revision with the SHA-pinned image
5. Updates the EventBridge Scheduler target to use the new task definition revision

To trigger a deploy manually without a code push: **Actions → deploy → Run workflow**.

---

## Monitoring

### View task logs

```bash
aws logs tail /ecs/my-batch-job-prod --follow --region us-east-1
```

### View execution history

```bash
aws scheduler list-schedule-group-schedules \
  --group-name my-batch-job-prod \
  --region us-east-1
```

### CloudWatch alarms to consider adding

- `ECS/ContainerInsights` → `TaskCount` falling to 0 after expected run time (task never started)
- Log metric filter on `ERROR` or `Exception` in the log group → SNS alert
- EventBridge → rule on `ECS Task State Change` with `lastStatus = STOPPED` and non-zero `exitCode`

---

## Cost Estimate

Assuming the task runs once per day for 5 minutes with 512 CPU / 1024 MB:

| Component | Calculation | Monthly cost |
|-----------|------------|-------------|
| Fargate vCPU | 0.5 vCPU × 300s × 30 runs × $0.04048/vCPU-hr | ~$0.05 |
| Fargate memory | 1 GB × 300s × 30 runs × $0.004445/GB-hr | ~$0.01 |
| ECR storage | ~500 MB image × 10 images | ~$0.05 |
| EventBridge Scheduler | 30 invocations/month | Free tier |
| CloudWatch Logs | Depends on log volume | ~$0.01 |
| **Total** | | **~$0.12/month** |

Costs scale linearly with runtime, frequency, and resource allocation.

---

## Teardown

```bash
cd infra

# Disable the schedule first to stop future runs
aws scheduler update-schedule \
  --group-name my-batch-job-prod \
  --name my-batch-job-prod-batch \
  --state DISABLED \
  --region us-east-1

# Delete all infrastructure
terraform destroy
```

> **Note:** ECR images must be deleted manually before `terraform destroy` can remove the repository, or set `force_delete = true` on the `aws_ecr_repository` resource.
