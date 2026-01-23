#!/bin/bash

echo "Starting CAFC Precedential Copilot..."

# Kill any existing processes
pkill -f "uvicorn backend.main:app" 2>/dev/null || true

# Start Python FastAPI backend on port 8000 (internal)
echo "Starting Python FastAPI backend on port 8000..."
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 &
PYTHON_PID=$!

# Wait for Python backend to be ready
echo "Waiting for Python backend..."
for i in {1..30}; do
  if curl -s http://localhost:8000/api/status > /dev/null 2>&1; then
    echo "Python backend ready!"
    break
  fi
  sleep 0.5
done

# Start Node.js frontend/proxy on port 5000 (public)
echo "Starting Node.js frontend on port 5000..."
npm run dev

# Cleanup on exit
trap "kill $PYTHON_PID 2>/dev/null" EXIT
