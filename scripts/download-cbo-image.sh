#!/usr/bin/env bash
# ==============================================================================
# Downloads, verifies, and optionally loads the CBO AI Docker image (.tar.gz)
# from GitHub Releases:
# https://github.com/abdulrahimzadjali/cbo-open-webui/releases/tag/cbo-latest
# ==============================================================================

set -euo pipefail

REPO="${REPO:-abdulrahimzadjali/cbo-open-webui}"
TAG="${TAG:-cbo-latest}"
OUTPUT_DIR="${OUTPUT_DIR:-./docker-exports}"
SKIP_LOAD="${SKIP_LOAD:-0}"

ARCHIVE_NAME="cbo-open-webui-latest.tar.gz"
CHECKSUM_NAME="${ARCHIVE_NAME}.sha256"

BASE_URL="https://github.com/${REPO}/releases/download/${TAG}"
ARCHIVE_URL="${BASE_URL}/${ARCHIVE_NAME}"
CHECKSUM_URL="${BASE_URL}/${CHECKSUM_NAME}"

mkdir -p "${OUTPUT_DIR}"

ARCHIVE_PATH="${OUTPUT_DIR}/${ARCHIVE_NAME}"
CHECKSUM_PATH="${OUTPUT_DIR}/${CHECKSUM_NAME}"

echo "=========================================================="
echo "  CBO AI Docker Image Downloader"
echo "=========================================================="
echo "Release Tag : ${TAG}"
echo "Repository  : ${REPO}"
echo "Output Dir  : ${OUTPUT_DIR}"
echo ""

echo "[1/4] Downloading SHA-256 checksum..."
curl -fsSL "${CHECKSUM_URL}" -o "${CHECKSUM_PATH}"
EXPECTED_HASH=$(awk '{print $1}' "${CHECKSUM_PATH}")
echo "Expected SHA-256: ${EXPECTED_HASH}"

echo "[2/4] Downloading container image archive (~1.1 GB)..."
echo "URL: ${ARCHIVE_URL}"
curl -fL "${ARCHIVE_URL}" -o "${ARCHIVE_PATH}" --progress-bar

echo "[3/4] Verifying SHA-256 checksum..."
cd "${OUTPUT_DIR}"
if command -v sha256sum &>/dev/null; then
    sha256sum -c "${CHECKSUM_NAME}"
elif command -v shasum &>/dev/null; then
    shasum -a 256 -c "${CHECKSUM_NAME}"
fi
cd - >/dev/null
echo "Checksum verified successfully!"

if [ "${SKIP_LOAD}" -eq 0 ]; then
    echo "[4/4] Loading container into Docker engine..."
    if command -v docker &>/dev/null; then
        docker load -i "${ARCHIVE_PATH}"
        echo "Docker image loaded successfully!"
        echo ""
        echo "To run CBO AI:"
        echo "  docker run -d -p 3000:8080 -v open-webui:/app/backend/data --name cbo-open-webui ghcr.io/${REPO}:latest"
    else
        echo "Docker command not found. To load manually: docker load -i ${ARCHIVE_PATH}"
    fi
else
    echo "[4/4] Skipping Docker load (SKIP_LOAD=1)."
    echo "To load manually: docker load -i ${ARCHIVE_PATH}"
fi
