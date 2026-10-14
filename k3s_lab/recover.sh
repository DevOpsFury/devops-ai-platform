#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
CONTEXT="k3d-k3s-lab"

kubectl --context "$CONTEXT" apply -f "${SCRIPT_DIR}/manifests/lab.yaml"
"${SCRIPT_DIR}/break.sh" orders-api-fixme

for deployment in web api cache orders-api; do
  kubectl --context "$CONTEXT" --namespace devops-lab \
    rollout status "deployment/${deployment}" --timeout=180s
done
printf 'Usługi przywrócone do stanu bazowego.\n'
