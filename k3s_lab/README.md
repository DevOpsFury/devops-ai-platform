# Lab k3s

Lokalny klaster k3s uruchamiany przez k3d oraz cztery przykładowe usługi w namespace `devops-lab`:

| Usługa | Obraz | Port w klastrze | Scenariusz awarii |
| --- | --- | --- | --- |
| `web` | `nginx:1.27-alpine` | HTTP 80 | `web-down` — skala do zera |
| `api` | `hashicorp/http-echo:1.0.0` | HTTP 80 | `api-bad-image` — nieistniejący tag obrazu |
| `cache` | `redis:7-alpine` | Redis 6379 | `cache-kill` — usunięcie poda i obserwacja samonaprawy |
| `orders-api` | `devops-lab/orders-api:latest` | HTTP 8080 | `orders-api-db-auth` — symulowany błąd uwierzytelnienia PostgreSQL |

## Wymagania

- Docker Desktop uruchomiony na macOS.
- `kubectl` i `k3d` dostępne w `PATH`.

Uruchom aplikację przez Compose zgodnie z głównym README, a następnie utwórz klaster i workloady:

```sh
./k3s_lab/start.sh
```

Skrypt buduje obraz lokalny `orders-api`, importuje go do k3d, tworzy klaster `k3s-lab` z API wystawionym lokalnie na `127.0.0.1:6550`, wdraża cztery usługi i czeka na ich gotowość. Pozostałe obrazy są pobierane z Docker Hub, dlatego pierwsze uruchomienie wymaga dostępu do internetu.

API klastra jest osiągalne z kontenera `api` pod adresem `https://host.docker.internal:6550`. Compose udostępnia aplikacji zmienne `KUBERNETES_API_URL` oraz `KUBECONFIG=/run/k3s-lab/config`; wygenerowany kubeconfig jest montowany tylko do odczytu. Dedykowany ServiceAccount ma prawa `get`, `list` i `watch` dla podów, usług, Endpointów, zdarzeń, Deploymentów i ReplicaSetów oraz tylko `get` dla logów podów — wyłącznie w namespace `devops-lab`. Osobna ClusterRole pozwala mu wyłącznie na `get` i `list` obiektów Node, aby raportować stan węzłów; nie daje prawa do zmieniania zasobów, czytania Secretów ani dostępu do workloadów w innych namespace’ach. API udostępnia zbiorczy snapshot diagnostyczny oraz ograniczony odczyt logów, a diagnoza incydentu przekazuje ten snapshot agentom.

## Podgląd i awarie

```sh
./k3s_lab/status.sh
./k3s_lab/break.sh web-down
./k3s_lab/break.sh api-bad-image
./k3s_lab/break.sh cache-kill
./k3s_lab/break.sh orders-api-db-auth
```

Awarię `cache-kill` deployment naprawia sam. Aby przywrócić wszystkie wdrożenia do stanu bazowego, w tym replikę `web` i prawidłowy obraz `api`, uruchom:

```sh
./k3s_lab/recover.sh
```

`orders-api` udostępnia `POST /break/db-auth`, `POST /fixme`, `GET /health/live` i `GET /health/ready`. Scenariusz `orders-api-db-auth` zapisuje w logach błędy połączenia z PostgreSQL i błędnego hasła `orders_user`; proces pozostaje aktywny, aby można go było odwrócić. Gotowość poda spada, ale liveness pozostaje zdrowy. Skrypt `break.sh` wywołuje endpoint przez `kubectl port-forward`, ponieważ niegotowy pod zostaje usunięty z Endpointów Service. Symulację można wyzerować poleceniem:

```sh
./k3s_lab/break.sh orders-api-fixme
```

`./k3s_lab/recover.sh` również wywołuje `/fixme` i czeka na gotowość wszystkich wdrożeń. Pełna sekwencja logów aplikacji jest pobierana w snapshotcie przez API diagnostyczne i przekazywana agentom; `/fixme` przywraca gotowość bez restartu poda.

Usunięcie klastra i wygenerowanego kubeconfigu:

```sh
./k3s_lab/stop.sh
```

Skrypt `stop.sh` nie zatrzymuje PostgreSQL, Qdrant, Ollama ani API uruchomionych przez Compose.
