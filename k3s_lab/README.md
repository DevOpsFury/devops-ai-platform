# Lab k3s

Lokalny klaster k3s uruchamiany przez k3d oraz trzy przykładowe usługi w namespace `devops-lab`:

| Usługa | Obraz | Port w klastrze | Scenariusz awarii |
| --- | --- | --- | --- |
| `web` | `nginx:1.27-alpine` | HTTP 80 | `web-down` — skala do zera |
| `api` | `hashicorp/http-echo:1.0.0` | HTTP 80 | `api-bad-image` — nieistniejący tag obrazu |
| `cache` | `redis:7-alpine` | Redis 6379 | `cache-kill` — usunięcie poda i obserwacja samonaprawy |

## Wymagania

- Docker Desktop uruchomiony na macOS.
- `kubectl` i `k3d` dostępne w `PATH`.

Uruchom aplikację przez Compose zgodnie z głównym README, a następnie utwórz klaster i workloady:

```sh
./k3s_lab/start.sh
```

Skrypt tworzy klaster `k3s-lab` z API wystawionym lokalnie na `127.0.0.1:6550`, wdraża trzy usługi i czeka na ich gotowość. Obrazy kontenerów są pobierane z Docker Hub, dlatego pierwsze uruchomienie wymaga dostępu do internetu.

API klastra jest osiągalne z kontenera `api` pod adresem `https://host.docker.internal:6550`. Compose udostępnia aplikacji zmienne `KUBERNETES_API_URL` oraz `KUBECONFIG=/run/k3s-lab/config`; wygenerowany kubeconfig jest montowany tylko do odczytu. Dedykowany ServiceAccount ma prawa `get`, `list` i `watch` dla podów, usług, Endpointów, zdarzeń, Deploymentów i ReplicaSetów oraz tylko `get` dla logów podów — wyłącznie w namespace `devops-lab`. Osobna ClusterRole pozwala mu wyłącznie na `get` i `list` obiektów Node, aby raportować stan węzłów; nie daje prawa do zmieniania zasobów, czytania Secretów ani dostępu do workloadów w innych namespace’ach. API udostępnia zbiorczy snapshot diagnostyczny oraz ograniczony odczyt logów, a diagnoza incydentu przekazuje ten snapshot agentom.

## Podgląd i awarie

```sh
./k3s_lab/status.sh
./k3s_lab/break.sh web-down
./k3s_lab/break.sh api-bad-image
./k3s_lab/break.sh cache-kill
```

Awarię `cache-kill` deployment naprawia sam. Aby przywrócić wszystkie wdrożenia do stanu bazowego, w tym replikę `web` i prawidłowy obraz `api`, uruchom:

```sh
./k3s_lab/recover.sh
```

Usunięcie klastra i wygenerowanego kubeconfigu:

```sh
./k3s_lab/stop.sh
```

Skrypt `stop.sh` nie zatrzymuje PostgreSQL, Qdrant, Ollama ani API uruchomionych przez Compose.
