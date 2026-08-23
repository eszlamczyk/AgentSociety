#!/bin/bash
set -e

# Navigate to repo root regardless of where script is called from
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

echo "==> Creating virtual environment..."
python3 -m venv .venv

echo "==> Activating virtual environment..."
source .venv/bin/activate

echo "==> Installing agentsociety from local source..."
pip install -e packages/agentsociety/

echo "==> Pinning numpy to 2.x (required by mosstool)..."
pip install "numpy>=2.0.0,<3.0.0"

echo ""
echo "Setup complete. Activate the environment with:"
echo "  source .venv/bin/activate"
echo ""
echo "Then run the simulation from examples/internet/:"
echo "  cd examples/internet && python internet.py"
