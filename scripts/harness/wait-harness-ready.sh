#!/usr/bin/env bash
# Polls a Harness endpoint (alias) until it reports READY, using GetHarnessEndpoint:
# https://docs.aws.amazon.com/bedrock-agentcore-control/latest/APIReference/API_GetHarnessEndpoint.html
#
# Endpoint lifecycle: CREATING|UPDATING -> READY, or CREATE_FAILED|UPDATE_FAILED on error.
# Call this right after point-harness-alias.sh so the pipeline only proceeds (staging tests,
# production promotion, DB status write) once the alias is actually serving the new version.
#
# Usage: wait-harness-ready.sh --harness-id <id> --alias STAGING|PROD [--timeout <seconds>] [--interval <seconds>]
set -euo pipefail

HARNESS_ID=""
ALIAS=""
TIMEOUT_SECONDS=300
POLL_INTERVAL_SECONDS=10

while [[ $# -gt 0 ]]; do
  case "$1" in
    --harness-id) HARNESS_ID="$2"; shift 2 ;;
    --alias) ALIAS="$2"; shift 2 ;;
    --timeout) TIMEOUT_SECONDS="$2"; shift 2 ;;
    --interval) POLL_INTERVAL_SECONDS="$2"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
done

if [[ -z "$HARNESS_ID" || -z "$ALIAS" ]]; then
  echo "Usage: wait-harness-ready.sh --harness-id <id> --alias STAGING|PROD [--timeout <seconds>] [--interval <seconds>]" >&2
  exit 1
fi

elapsed=0
while true; do
  endpoint=$(aws bedrock-agentcore-control get-harness-endpoint \
    --harness-id "$HARNESS_ID" \
    --endpoint-name "$ALIAS" \
    --output json)
  status=$(echo "$endpoint" | jq -r '.endpoint.status')

  case "$status" in
    READY)
      # Once READY, GetHarnessEndpoint reports the applied version as liveVersion —
      # targetVersion is null again (it only holds a value mid-transition).
      echo "Harness endpoint ${ALIAS} is ready (liveVersion=$(echo "$endpoint" | jq -r '.endpoint.liveVersion'))." >&2
      echo "$endpoint"
      exit 0
      ;;
    CREATE_FAILED|UPDATE_FAILED)
      echo "Harness endpoint ${ALIAS} failed: $(echo "$endpoint" | jq -r '.endpoint.failureReason // "unknown reason"')" >&2
      exit 1
      ;;
  esac

  if (( elapsed >= TIMEOUT_SECONDS )); then
    echo "Timed out after ${TIMEOUT_SECONDS}s waiting for Harness endpoint ${ALIAS} to become ready (last status=$status)." >&2
    exit 1
  fi

  sleep "$POLL_INTERVAL_SECONDS"
  elapsed=$((elapsed + POLL_INTERVAL_SECONDS))
done
