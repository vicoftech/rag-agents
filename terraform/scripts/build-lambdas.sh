#!/bin/bash
set -e

# ==============================================================================
# Build Lambda deployment packages with dependencies
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TERRAFORM_DIR="$(dirname "$SCRIPT_DIR")"
APPS_DIR="$(dirname "$TERRAFORM_DIR")/apps"
BUILD_DIR="${TERRAFORM_DIR}/.lambda-builds"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}============================================================${NC}"
echo -e "${GREEN}Building Lambda Deployment Packages${NC}"
echo -e "${GREEN}============================================================${NC}"

# Create build directory
mkdir -p "$BUILD_DIR"

# Function to build a single lambda
build_lambda() {
    local lambda_dir="$1"
    local lambda_name=$(basename "$lambda_dir")
    local package_dir="${BUILD_DIR}/${lambda_name}"
    
    echo -e "${YELLOW}Building ${lambda_name}...${NC}"
    
    # Clean previous build
    rm -rf "$package_dir"
    mkdir -p "$package_dir"
    
    # Copy source files
    cp -r "${lambda_dir}"/* "$package_dir/" 2>/dev/null || true
    
    # Remove unnecessary files
    rm -rf "${package_dir}/.git" \
           "${package_dir}/.gitignore" \
           "${package_dir}/.DS_Store" \
           "${package_dir}/__pycache__" \
           "${package_dir}/*.pyc" \
           "${package_dir}/test_*.py" \
           "${package_dir}/build_lambda.sh" \
           "${package_dir}/venv"
    
    # Install dependencies
    if [[ -f "${lambda_dir}/requirements.txt" ]]; then
        echo "  Installing dependencies..."
        pip install -q -r "${lambda_dir}/requirements.txt" \
            -t "$package_dir" \
            --upgrade \
            --platform manylinux2014_x86_64 \
            --only-binary=:all: \
            2>/dev/null || \
        pip install -q -r "${lambda_dir}/requirements.txt" \
            -t "$package_dir" \
            --upgrade
    fi
    
    # Remove unnecessary files from dependencies
    find "$package_dir" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
    find "$package_dir" -type d -name "*.dist-info" -exec rm -rf {} + 2>/dev/null || true
    find "$package_dir" -type d -name "tests" -exec rm -rf {} + 2>/dev/null || true
    find "$package_dir" -name "*.pyc" -delete 2>/dev/null || true
    
    # Create zip
    echo "  Creating zip package..."
    cd "$package_dir"
    zip -q -r "${BUILD_DIR}/${lambda_name}.zip" .
    cd - > /dev/null
    
    # Show package size
    local size=$(du -h "${BUILD_DIR}/${lambda_name}.zip" | cut -f1)
    echo -e "  ${GREEN}✓ ${lambda_name}.zip (${size})${NC}"
}

# Build each lambda
for lambda_dir in "${APPS_DIR}/rag_lmbd_embeddings" "${APPS_DIR}/rag_lmbd_query"; do
    if [[ -d "$lambda_dir" ]]; then
        build_lambda "$lambda_dir"
    fi
done

echo ""
echo -e "${GREEN}============================================================${NC}"
echo -e "${GREEN}Build complete! Packages in: ${BUILD_DIR}${NC}"
echo -e "${GREEN}============================================================${NC}"
ls -la "${BUILD_DIR}"/*.zip 2>/dev/null || echo "No zip files found"
