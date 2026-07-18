#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${VIDEO_SUMMARIZER_URL:-http://localhost:8000}"

# --- Health check ---
HEALTH=$(curl -sf --connect-timeout 3 "$BASE_URL/health" 2>/dev/null || echo "")
if ! echo "$HEALTH" | grep -q '"ok"'; then
    echo "Error: Video summarizer service is not running"
    exit 1
fi

# --- Read cookies ---
if [ $# -gt 0 ]; then
    # From file argument
    if [ ! -f "$1" ]; then
        echo "Error: File not found: $1"
        exit 1
    fi
    COOKIES=$(cat "$1")
else
    # From stdin
    echo "Paste Bilibili cookies (Netscape format), then press Ctrl+D:"
    COOKIES=$(cat)
fi

if [ -z "$COOKIES" ]; then
    echo "Error: No cookies provided"
    exit 1
fi

# --- Update cookies ---
RESP=$(curl -sf --connect-timeout 3 -X PUT "$BASE_URL/api/settings/cookies" \
    -H "Content-Type: application/json" \
    -d "$(python3 -c "import json; print(json.dumps({'cookies': open('/dev/stdin').read()}))" <<< "$COOKIES")" 2>/dev/null || echo "")

if [ -z "$RESP" ]; then
    echo "Error: Failed to update cookies"
    exit 1
fi

STATUS=$(echo "$RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status','unknown'))" 2>/dev/null || echo "unknown")
case "$STATUS" in
    valid)          echo "Cookies updated and verified: VALID" ;;
    expired)        echo "Cookies updated but verification failed: EXPIRED" ;;
    not_configured) echo "Cookies updated but file not found" ;;
    *)              echo "Cookies updated, status: $STATUS" ;;
esac
