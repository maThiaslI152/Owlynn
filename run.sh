#!/bin/bash
# Script to launch the Local Cowork Agent

echo "Starting Local Cowork Agent..."

# Ensure we're in the right directory
cd "$(dirname "$0")"

# Export PYTHONPATH so Python can resolve the local 'src' module
export PYTHONPATH=$PYTHONPATH:$(pwd)

# Activate the virtual environment
source .venv/bin/activate

echo "Checking dependencies..."
pip install -r requirements.txt --quiet

echo "✅ Launching FastAPI backend + frontend at http://127.0.0.1:8000"
echo ""
echo "Open your browser and navigate to: http://127.0.0.1:8000"
echo ""

# Run the FastAPI app via Uvicorn
uvicorn src.api.server:app --host 127.0.0.1 --port 8000 --reload
