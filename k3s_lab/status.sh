#!/usr/bin/env bash
set -euo pipefail

CLUSTER_NAME="k3s-lab"
NAMESPACE="devops-lab"
CONTEXT="k3d-${CLUSTER_NAME}"

if ! command -v kubectl >/dev/null 2>&1; then
  printf 'Brak wymaganego polecenia: kubectl\n' >&2
  exit 1
fi

kubectl --context "$CONTEXT" --namespace "$NAMESPACE" get deployments,pods,services
printf '\nOstatnie zdarzenia:\n'
kubectl --context "$CONTEXT" --namespace "$NAMESPACE" \
  get events --sort-by=.lastTimestamp | tail -n 10
