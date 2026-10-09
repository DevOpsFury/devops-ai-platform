#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
CLUSTER_NAME="k3s-lab"

if ! command -v k3d >/dev/null 2>&1; then
  printf 'Brak wymaganego polecenia: k3d\n' >&2
  exit 1
fi

if k3d cluster list | awk 'NR > 1 { print $1 }' | grep -Fxq "$CLUSTER_NAME"; then
  k3d cluster delete "$CLUSTER_NAME"
fi

rm -f "${SCRIPT_DIR}/credentials/config"
printf 'Klaster %s został usunięty. Pozostałe usługi Compose nie zostały zatrzymane.\n' \
  "$CLUSTER_NAME"
