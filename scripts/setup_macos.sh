#!/usr/bin/env bash
set -euo pipefail

# shellcheck disable=SC1091
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate d2l

python -m pip install -r requirements.txt
cd frontend && npm install

echo "macOS setup done. Start backend in backend/: uvicorn app.main:app --reload"
