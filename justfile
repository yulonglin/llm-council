# LLM Council development commands

# Start both backend and frontend
dev:
    #!/usr/bin/env bash
    trap 'kill 0' EXIT
    python -m backend.main &
    cd frontend && npx vite &
    wait

# Start backend only (port 8001)
backend:
    python -m backend.main

# Start frontend only (port 5173)
frontend:
    cd frontend && npx vite

# Install all dependencies
install:
    uv sync
    cd frontend && npm install
