#!/usr/bin/env bash
set -euo pipefail

CLUSTER_NAME="k3s-lab"
NAMESPACE="devops-lab"
CONTEXT="k3d-${CLUSTER_NAME}"
SCENARIO="${1:-}"

if [[ -z "$SCENARIO" ]]; then
  printf 'Użycie: %s {web-down|api-bad-image|cache-kill}\n' "$0" >&2
  exit 2
fi

case "$SCENARIO" in
  web-down)
    kubectl --context "$CONTEXT" --namespace "$NAMESPACE" \
      scale deployment/web --replicas=0
    ;;
  api-bad-image)
    kubectl --context "$CONTEXT" --namespace "$NAMESPACE" \
      set image deployment/api http-echo=hashicorp/http-echo:does-not-exist
    ;;
  cache-kill)
    kubectl --context "$CONTEXT" --namespace "$NAMESPACE" \
      delete pod --selector=app=cache --wait=false
    ;;
  *)
    printf 'Nieznany scenariusz: %s\nUżycie: %s {web-down|api-bad-image|cache-kill}\n' \
      "$SCENARIO" "$0" >&2
    exit 2
    ;;
esac
