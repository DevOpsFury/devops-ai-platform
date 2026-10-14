#!/usr/bin/env bash
set -euo pipefail

CLUSTER_NAME="k3s-lab"
NAMESPACE="devops-lab"
CONTEXT="k3d-${CLUSTER_NAME}"
SCENARIO="${1:-}"

if [[ -z "$SCENARIO" ]]; then
  printf 'Użycie: %s {web-down|api-bad-image|cache-kill|orders-api-db-auth|orders-api-fixme}\n' "$0" >&2
  exit 2
fi

call_orders_api() {
  local endpoint="$1"
  local port_forward_pid

  if ! command -v curl >/dev/null 2>&1; then
    printf 'Brak wymaganego polecenia: curl\n' >&2
    exit 1
  fi

  kubectl --context "$CONTEXT" --namespace "$NAMESPACE" \
    port-forward deployment/orders-api 18080:8080 >/dev/null 2>&1 &
  port_forward_pid=$!
  trap 'kill "$port_forward_pid" 2>/dev/null || true' EXIT

  for _ in {1..30}; do
    if curl --silent --fail http://127.0.0.1:18080/health/live >/dev/null; then
      break
    fi
    sleep 1
  done

  if ! curl --silent --fail http://127.0.0.1:18080/health/live >/dev/null; then
    printf 'Nie udało się połączyć z orders-api przez port-forward.\n' >&2
    exit 1
  fi

  curl --silent --show-error --fail \
    --request POST "http://127.0.0.1:18080${endpoint}"
  printf '\n'
}

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
  orders-api-db-auth)
    call_orders_api "/break/db-auth"
    printf '\norders-api-db-auth aktywny. Diagnozuj przez API aplikacji; '
    printf 'wyzeruj symulację: ./k3s_lab/break.sh orders-api-fixme\n'
    ;;
  orders-api-fixme)
    call_orders_api "/fixme"
    ;;
  *)
    printf 'Nieznany scenariusz: %s\nUżycie: %s {web-down|api-bad-image|cache-kill|orders-api-db-auth|orders-api-fixme}\n' \
      "$SCENARIO" "$0" >&2
    exit 2
    ;;
esac
