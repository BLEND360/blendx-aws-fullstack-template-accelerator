#!/usr/bin/env bash
# Reads the CloudFormation outputs that @aws/agentcore-cdk's AgentCoreApplication L3
# construct emits automatically for every deployed Harness. The construct is nested
# inside an "Application" scope, so CDK's auto-generated OutputKey is not the clean
# Harness<Name><Field> name — it's <ScopePrefix>Harness<Name><Field>Output<hash>, e.g.
# ApplicationHarnessProjectAssistantVersionOutput1DFA7D31. Match by substring instead
# of exact equality so the (deploy-to-deploy stable, but otherwise opaque) scope
# prefix and CDK-assigned hash suffix don't matter.
#
# Usage: get-harness-version.sh <stack-name> <harness-logical-name>
# Example: get-harness-version.sh AgentCore-blendxhubharness-default ProjectAssistant
#
# Prints a JSON object: {"id":..., "arn":..., "status":..., "version":..., "agentRuntimeArn":...}
set -euo pipefail

STACK_NAME="${1:?Usage: get-harness-version.sh <stack-name> <harness-logical-name>}"
HARNESS_LOGICAL_NAME="${2:?Usage: get-harness-version.sh <stack-name> <harness-logical-name>}"

outputs=$(aws cloudformation describe-stacks \
  --stack-name "$STACK_NAME" \
  --query 'Stacks[0].Outputs' \
  --output json)

get_output() {
  local suffix="$1"
  echo "$outputs" | jq -r --arg needle "Harness${HARNESS_LOGICAL_NAME}${suffix}Output" \
    '.[] | select(.OutputKey | contains($needle)) | .OutputValue'
}

id=$(get_output "Id")
arn=$(get_output "Arn")
status=$(get_output "Status")
version=$(get_output "Version")
agent_runtime_arn=$(get_output "AgentRuntimeArn")

if [[ -z "$version" ]]; then
  echo "No output containing 'Harness${HARNESS_LOGICAL_NAME}VersionOutput' found on stack $STACK_NAME." >&2
  echo "Check that the harness logical name matches app/<harnessName>/harness.json." >&2
  echo "Actual outputs on this stack:" >&2
  echo "$outputs" | jq -r '.[].OutputKey' >&2
  exit 1
fi

jq -n \
  --arg id "$id" \
  --arg arn "$arn" \
  --arg status "$status" \
  --arg version "$version" \
  --arg agentRuntimeArn "$agent_runtime_arn" \
  '{id: $id, arn: $arn, status: $status, version: $version, agentRuntimeArn: $agentRuntimeArn}'
