#!/usr/bin/env bash
# make-sandboxes.sh: one sandbox per student → roster.csv
# Each sandbox suspends after IDLE_SECONDS of inactivity and wakes up again
# when someone opens its editor or app URL.
set -uo pipefail

DISK_ID="5fcd9756-ae5a-46f4-9525-09f3d38991a0"
REGION="westus2"
SUBSCRIPTION="93eb79c7-f8d8-4658-9b17-90d14032d374"
RESOURCE_GROUP="agentic-interfaces-rg"
SANDBOX_GROUP="ag-ui-component"
IDLE_SECONDS=1800   # suspend after 30 minutes with no traffic
# S size: 0.5 vCPU, 1 GiB memory, 10 GiB disk
CPU="500m"
MEMORY="1024Mi"
DISK_SIZE="5Gi"
PROJ=/root/projects/agentic-interfaces-workshop

API="https://management.$REGION.azuredevcompute.io/subscriptions/$SUBSCRIPTION/resourceGroups/$RESOURCE_GROUP/sandboxGroups/$SANDBOX_GROUP/sandboxes"
API_VERSION="2026-02-01-preview"

# Switch every port on a sandbox to OnDemand so traffic to its URL wakes it.
# The aca CLI can't set this yet, so it goes through the REST API: read the
# ports back (the PUT needs every field, including url) and change one field.
enable_wake_on_request() {
  local sb=$1 token
  token=$(az account get-access-token --resource https://dynamicsessions.io --query accessToken -o tsv)
  curl -sf "$API/$sb?api-version=$API_VERSION" -H "Authorization: Bearer $token" \
  | jq '{ports: [.ports[] | .activationMode = "OnDemand"]}' \
  | curl -sf -X PUT "$API/$sb/ports?api-version=$API_VERSION" \
      -H "Authorization: Bearer $token" \
      -H "Content-Type: application/json" \
      -d @- >/dev/null
}

echo "student,sandbox_id,editor_url,app_url,password" > roster.csv
while read -r s; do
  [ -z "$s" ] && continue
  sb=$(aca sandbox create --disk-id "$DISK_ID" \
         --cpu "$CPU" --memory "$MEMORY" --disk-size "$DISK_SIZE" | grep -oE '[0-9a-f-]{36}' | head -1)
  if [ -z "$sb" ]; then
    echo "FAILED to create sandbox for $s" >&2
    continue
  fi
  pw=$(openssl rand -base64 9)
  aca sandbox exec --id "$sb" -c \
    "PASSWORD='$pw' nohup code-server --bind-addr 0.0.0.0:8080 --auth password $PROJ >/tmp/cs.log 2>&1 &"
  aca sandbox port add --id "$sb" --port 8080 --anonymous >/dev/null
  aca sandbox port add --id "$sb" --port 5173 --anonymous >/dev/null
  enable_wake_on_request "$sb" || echo "WARNING: could not enable wake-on-request for $s ($sb)" >&2
  # Memory mode keeps code-server and the dev servers running across a suspend.
  aca sandbox lifecycle set --id "$sb" --auto-suspend enable --mode Memory \
    --idle-timeout-seconds "$IDLE_SECONDS" >/dev/null
  echo "$s,$sb,https://$sb--8080.$REGION.adcproxy.io,https://$sb--5173.$REGION.adcproxy.io,$pw" >> roster.csv
  echo "created $s → $sb"
done < students.txt
