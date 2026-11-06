#!/usr/bin/env bash
# make-sandboxes.sh: one sandbox per student → roster.csv
DISK_ID="5fcd9756-ae5a-46f4-9525-09f3d38991a0"
REGION="westus2"
PROJ=/root/projects/agentic-interfaces-workshop

echo "student,sandbox_id,editor_url,app_url,password" > roster.csv
while read -r s; do
  sb=$(aca sandbox create --disk-id "$DISK_ID" | grep -oE '[0-9a-f-]{36}' | head -1)
  pw=$(openssl rand -base64 9)
  aca sandbox exec --id "$sb" -c \
    "PASSWORD='$pw' nohup code-server --bind-addr 0.0.0.0:8080 --auth password $PROJ >/tmp/cs.log 2>&1 &"
  aca sandbox port add --id "$sb" --port 8080 --anonymous >/dev/null
  aca sandbox port add --id "$sb" --port 5173 --anonymous >/dev/null
  aca sandbox lifecycle set --id "$sb" --auto-suspend disable >/dev/null
  echo "$s,$sb,https://$sb--8080.$REGION.adcproxy.io,https://$sb--5173.$REGION.adcproxy.io,$pw" >> roster.csv
done < students.txt
