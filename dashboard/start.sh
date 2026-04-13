#!/bin/bash
cd "$(dirname "$0")/.."
python3 -m uvicorn dashboard.server:app --host 127.0.0.1 --port 8080 --reload
