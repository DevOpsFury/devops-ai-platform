#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
CLUSTER_NAME="k3s-lab"
NAMESPACE="devops-lab"
CONTEXT="k3d-${CLUSTER_NAME}"
API_URL="https://host.docker.internal:6550"
KUBECONFIG_DIR="${SCRIPT_DIR}/credentials"
APP_KUBECONFIG="${KUBECONFIG_DIR}/config"

for command in docker k3d kubectl; do
  if ! command -v "$command" >/dev/null 2>&1; then
    printf 'Brak wymaganego polecenia: %s\n' "$command" >&2
    exit 1
  fi
done

if ! docker info >/dev/null 2>&1; then
  printf 'Docker nie jest uruchomiony. Uruchom Docker Desktop i ponów próbę.\n' >&2
  exit 1
fi

ORDERS_API_IMAGE="devops-lab/orders-api:latest"
docker build -t "$ORDERS_API_IMAGE" "${SCRIPT_DIR}/orders_api"

if ! k3d cluster list | awk 'NR > 1 { print $1 }' | grep -Fxq "$CLUSTER_NAME"; then
  k3d cluster create "$CLUSTER_NAME" \
    --servers 1 \
    --agents 1 \
    --api-port 127.0.0.1:6550 \
    --k3s-arg '--tls-san=host.docker.internal@server:0' \
    --wait
fi

k3d image import "$ORDERS_API_IMAGE" --cluster "$CLUSTER_NAME"
kubectl --context "$CONTEXT" apply -f "${SCRIPT_DIR}/manifests/lab.yaml"
kubectl --context "$CONTEXT" --namespace "$NAMESPACE" \
  rollout restart deployment/orders-api

for deployment in web api cache orders-api; do
  kubectl --context "$CONTEXT" --namespace "$NAMESPACE" \
    rollout status "deployment/${deployment}" --timeout=180s
done

secret="devops-platform-reader-token"
token=""
for _ in {1..30}; do
  token="$(kubectl --context "$CONTEXT" --namespace "$NAMESPACE" \
    get secret "$secret" -o 'jsonpath={.data.token}' | base64 -D)"
  if [[ -n "$token" ]]; then
    break
  fi
  sleep 1
done

if [[ -z "$token" ]]; then
  printf 'Nie udało się pobrać tokenu konta devops-platform-reader z klastra.\n' >&2
  exit 1
fi

ca_data="$(kubectl config view --raw --minify --context "$CONTEXT" \
  -o 'jsonpath={.clusters[0].cluster.certificate-authority-data}')"
if [[ -z "$ca_data" ]]; then
  printf 'Nie udało się odczytać certyfikatu CA klastra z kubeconfig.\n' >&2
  exit 1
fi

mkdir -p "$KUBECONFIG_DIR"
cat >"$APP_KUBECONFIG" <<EOF
apiVersion: v1
kind: Config
clusters:
  - name: ${CLUSTER_NAME}
    cluster:
      server: ${API_URL}
      certificate-authority-data: ${ca_data}
contexts:
  - name: ${CONTEXT}
    context:
      cluster: ${CLUSTER_NAME}
      namespace: ${NAMESPACE}
      user: devops-platform-reader
current-context: ${CONTEXT}
users:
  - name: devops-platform-reader
    user:
      token: ${token}
EOF
chmod 644 "$APP_KUBECONFIG"

printf '\nLab gotowy.\n'
printf 'Kontekst kubectl: %s\n' "$CONTEXT"
printf 'API dla kontenera Compose: %s\n' "$API_URL"
printf 'Kubeconfig aplikacji: %s\n' "$APP_KUBECONFIG"
printf 'Sprawdź stan: %s/status.sh\n' "$SCRIPT_DIR"
