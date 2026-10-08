#!/usr/bin/env bash
# Points an environment alias (STAGING or PROD) at a specific immutable Harness version,
# using the real AgentCore Harness endpoint API:
# https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/harness-versioning.html
#
# A "Harness endpoint" is the alias primitive: DEFAULT auto-tracks the latest version,
# named endpoints (STAGING, PROD) stay pinned until explicitly repointed. This script
# creates the endpoint on first use, then updates it on every subsequent promotion.
#
# Usage: point-harness-alias.sh --alias STAGING|PROD --harness-id <id> --version <n> [--description <text>]
set -euo pipefail

ALIAS=""
HARNESS_ID=""
VERSION=""
DESCRIPTION=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --alias) ALIAS="$2"; shift 2 ;;
    --harness-id) HARNESS_ID="$2"; shift 2 ;;
    --version) VERSION="$2"; shift 2 ;;
    --description) DESCRIPTION="$2"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
done

if [[ -z "$ALIAS" || -z "$HARNESS_ID" || -z "$VERSION" ]]; then
  echo "Usage: point-harness-alias.sh --alias STAGING|PROD --harness-id <id> --version <n> [--description <text>]" >&2
  exit 1
fi

if [[ "$ALIAS" != "STAGING" && "$ALIAS" != "PROD" ]]; then
  echo "--alias must be STAGING or PROD, got: $ALIAS" >&2
  exit 1
fi

DESCRIPTION="${DESCRIPTION:-$ALIAS endpoint for harness $HARNESS_ID}"

if aws bedrock-agentcore-control get-harness-endpoint \
  --harness-id "$HARNESS_ID" \
  --endpoint-name "$ALIAS" \
  >/tmp/harness-endpoint-existing.json 2>/tmp/harness-endpoint-existing.err; then
  echo "[point-harness-alias] Endpoint $ALIAS exists — updating to version $VERSION." >&2
  aws bedrock-agentcore-control update-harness-endpoint \
    --harness-id "$HARNESS_ID" \
    --endpoint-name "$ALIAS" \
    --target-version "$VERSION" \
    --description "$DESCRIPTION"
elif grep -q "ResourceNotFoundException" /tmp/harness-endpoint-existing.err; then
  echo "[point-harness-alias] Endpoint $ALIAS does not exist — creating, pinned to version $VERSION." >&2
  aws bedrock-agentcore-control create-harness-endpoint \
    --harness-id "$HARNESS_ID" \
    --endpoint-name "$ALIAS" \
    --target-version "$VERSION" \
    --description "$DESCRIPTION"
else
  echo "[point-harness-alias] get-harness-endpoint failed for an unexpected reason:" >&2
  cat /tmp/harness-endpoint-existing.err >&2
  exit 1
fi
