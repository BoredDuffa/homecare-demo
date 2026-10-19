#!/bin/zsh
set -e
cd "$(dirname "$0")"
if [[ ! -x .venv/bin/python ]]; then
  if ! command -v uv >/dev/null 2>&1; then
    print 'Install uv from https://docs.astral.sh/uv/ and try again.'
    read '?Press Return to close.'
    exit 1
  fi
  uv venv --python 3.13
  uv pip install --python .venv/bin/python -r requirements.txt
fi
if curl --silent --fail http://127.0.0.1:8765/api/health >/dev/null; then
  open http://127.0.0.1:8765
  exit 0
fi
.venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port 8765 &
server_pid=$!
trap 'kill "$server_pid" 2>/dev/null || true' EXIT INT TERM
for attempt in {1..50}; do
  if curl --silent --fail http://127.0.0.1:8765/api/health >/dev/null; then
    open http://127.0.0.1:8765
    break
  fi
  sleep 0.2
done
wait "$server_pid"
