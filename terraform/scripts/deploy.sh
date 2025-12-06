#!/bin/bash
set -e

# ==============================================================================
# RAG Agents - Terraform Deployment Script
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TERRAFORM_DIR="$(dirname "$SCRIPT_DIR")"
APPS_DIR="$(dirname "$TERRAFORM_DIR")/apps"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Default values
ENVIRONMENT="${ENVIRONMENT:-dev}"
ACTION="${1:-plan}"
AUTO_APPROVE="${AUTO_APPROVE:-false}"

usage() {
    echo "Usage: $0 [plan|apply|destroy] [options]"
    echo ""
    echo "Actions:"
    echo "  plan     - Show what changes would be made (default)"
    echo "  apply    - Apply the changes"
    echo "  destroy  - Destroy all resources"
    echo ""
    echo "Options:"
    echo "  -e, --environment  Environment name (default: dev)"
    echo "  -y, --auto-approve Auto approve apply/destroy"
    echo "  -h, --help         Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0 plan -e dev"
    echo "  $0 apply -e prod -y"
    exit 0
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        plan|apply|destroy)
            ACTION="$1"
            shift
            ;;
        -e|--environment)
            ENVIRONMENT="$2"
            shift 2
            ;;
        -y|--auto-approve)
            AUTO_APPROVE="true"
            shift
            ;;
        -h|--help)
            usage
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            usage
            ;;
    esac
done

echo -e "${GREEN}============================================================${NC}"
echo -e "${GREEN}RAG Agents - Terraform Deployment${NC}"
echo -e "${GREEN}============================================================${NC}"
echo -e "Environment: ${YELLOW}${ENVIRONMENT}${NC}"
echo -e "Action:      ${YELLOW}${ACTION}${NC}"
echo ""

# Check for tfvars file
TFVARS_FILE="${TERRAFORM_DIR}/environments/${ENVIRONMENT}.tfvars"
if [[ ! -f "$TFVARS_FILE" ]]; then
    # Try alternative naming
    TFVARS_FILE="${TERRAFORM_DIR}/environments/${ENVIRONMENT}_main.tfvars"
fi

if [[ ! -f "$TFVARS_FILE" ]]; then
    echo -e "${RED}Error: tfvars file not found for environment '${ENVIRONMENT}'${NC}"
    echo "Expected: ${TERRAFORM_DIR}/environments/${ENVIRONMENT}.tfvars"
    exit 1
fi

echo -e "Using tfvars: ${YELLOW}${TFVARS_FILE}${NC}"
echo ""

# Build Lambda packages
echo -e "${YELLOW}Building Lambda packages...${NC}"

for lambda_dir in "${APPS_DIR}/rag_lmbd_embeddings" "${APPS_DIR}/rag_lmbd_query"; do
    if [[ -d "$lambda_dir" ]]; then
        lambda_name=$(basename "$lambda_dir")
        echo "  Building ${lambda_name}..."
        
        # Install dependencies if requirements.txt exists
        if [[ -f "${lambda_dir}/requirements.txt" ]]; then
            pip install -q -r "${lambda_dir}/requirements.txt" -t "${lambda_dir}/" --upgrade 2>/dev/null || true
        fi
    fi
done

echo -e "${GREEN}Lambda packages built${NC}"
echo ""

# Change to terraform directory
cd "$TERRAFORM_DIR"

# Initialize Terraform
echo -e "${YELLOW}Initializing Terraform...${NC}"
terraform init -upgrade

# Select or create workspace
echo -e "${YELLOW}Selecting workspace: ${ENVIRONMENT}${NC}"
terraform workspace select "$ENVIRONMENT" 2>/dev/null || terraform workspace new "$ENVIRONMENT"

# Run Terraform action
case $ACTION in
    plan)
        echo -e "${YELLOW}Running terraform plan...${NC}"
        terraform plan -var-file="$TFVARS_FILE"
        ;;
    apply)
        echo -e "${YELLOW}Running terraform apply...${NC}"
        if [[ "$AUTO_APPROVE" == "true" ]]; then
            terraform apply -var-file="$TFVARS_FILE" -auto-approve
        else
            terraform apply -var-file="$TFVARS_FILE"
        fi
        ;;
    destroy)
        echo -e "${RED}Running terraform destroy...${NC}"
        if [[ "$AUTO_APPROVE" == "true" ]]; then
            terraform destroy -var-file="$TFVARS_FILE" -auto-approve
        else
            terraform destroy -var-file="$TFVARS_FILE"
        fi
        ;;
esac

echo ""
echo -e "${GREEN}============================================================${NC}"
echo -e "${GREEN}Deployment complete!${NC}"
echo -e "${GREEN}============================================================${NC}"
