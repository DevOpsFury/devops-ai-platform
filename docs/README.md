# Stan aplikacji AI DevOps Team

## Zakres

Aplikacja udostępnia agentom triage, observability i SecOps wspólny kontekst diagnostyczny z RAG oraz lokalnego klastra k3s. Przy każdym wywołaniu `POST /api/v1/incidents/diagnose` API pobiera bieżący, ograniczony do namespace `devops-lab` zrzut diagnostyczny klastra, dołącza wyniki wyszukiwania runbooków i przekazuje oba źródła do agentów oraz supervisora.

Dostęp do Kubernetes jest **wyłącznie read-only**. Agenci mogą analizować stan zasobów i rekomendować następne kroki, ale aplikacja nie restartuje podów, nie zmienia manifestów i nie wykonuje komend. Decyzje approval nadal są wpisami audytowymi; nie uruchamiają zaakceptowanej akcji.

## Dane diagnostyczne

Snapshot obejmuje:

- stan węzłów: Ready, wersja kubeleta, system operacyjny, architektura oraz capacity/allocatable;
- Deploymenty i ReplicaSety: liczby replik, dostępność, warunki i właściciel ReplicaSetu;
- pody: fazę, warunek Ready, węzeł, IP, obrazy kontenerów, restarty i bieżący/ostatni stan kontenerów;
- ostatnie logi kontenerów w podach; dla kontenerów po restarcie API próbuje pobrać także poprzednie logi;
- Services, selektory, porty oraz gotowe i niegotowe adresy Endpointów;
- do 100 zdarzeń namespace, posortowanych od najnowszych.

Odczyt ma limity: do 100 węzłów, usług, Endpointów, Deploymentów i ReplicaSetów; do 1000 podów; do 500 pobranych zdarzeń, z których do raportu trafia 100 najnowszych; oraz do 20 podów z logami i 100 ostatnich linii na kontener. Pody niegotowe albo z większą liczbą restartów są wybierane do odczytu logów w pierwszej kolejności. Pola `limits` wskazują, czy kolekcja została obcięta lub pominięto logi; brak danych po przekroczeniu limitu nie jest dowodem braku problemu. Odczyt logów można też wykonać osobno dla wybranego poda.

To nie jest pełna telemetria klastra: aplikacja nie pobiera metryk CPU/RAM z Metrics Server, danych Prometheus/Grafana, historii wdrożeń poza bieżącymi zasobami Kubernetes, ani zasobów z innych namespace. Dane workloadów i zdarzenia pochodzą tylko z `devops-lab`; informacje o węzłach są odczytywane na poziomie klastra.

## Uruchomienie laboratorium

1. Skonfiguruj `.env` według głównego [README](../README.md), uruchom Compose, a następnie utwórz laboratorium:

   ```sh
   docker compose up --build -d
   ./k3s_lab/start.sh
   ```

   Compose uruchamia również serwis `cache` (`redis:7-alpine`) i publikuje port `6379`. To osobny Redis pomocniczy; aplikacja obecnie z niego nie korzysta. Nie należy mylić go z Deploymentem `cache` w k3s, który jest częścią scenariusza `cache-kill`.

2. `start.sh` tworzy kubeconfig w `k3s_lab/credentials/config`. Jest on montowany do kontenera API tylko do odczytu. Zaktualizowane manifesty nadają ServiceAccount:
   - `get`, `list`, `watch` dla podów, usług, Endpointów i zdarzeń oraz `get` dla `pods/log` w `devops-lab`;
   - `get`, `list` dla obiektów Node;
   - żadnych uprawnień do zapisu, Secretów ani innych namespace’ów.

3. Po utworzeniu klastra sprawdź dostęp przez endpoint diagnostyczny:

   ```sh
   curl -H "X-API-Key: $APP_API_KEY" \
     http://localhost:8000/api/v1/k8s/diagnostics
   ```

   Jeśli kontener API był uruchomiony przed wygenerowaniem kubeconfigu, bind mount udostępnia nowy plik bez przebudowy obrazu. Endpoint zwraca `503` z jawnym błędem, jeśli pliku nie można wczytać, API klastra jest niedostępne albo ServiceAccount nie ma wymaganych praw. Po zmianie manifestów uruchom ponownie `./k3s_lab/start.sh`, aby zastosować RBAC.

## Endpointy diagnostyczne

Operacje wymagają nagłówka `X-API-Key` równemu `APP_API_KEY`.

- `GET /api/v1/k8s/diagnostics` — stan węzłów i zasobów w skonfigurowanym namespace, zdarzenia i ograniczone logi.
- `GET /api/v1/k8s/pods/{pod_name}/logs?tail_lines=100&container=nginx` — logi wskazanego poda; `tail_lines` przyjmuje wartości 1–500, a `container` jest opcjonalny.
- `POST /api/v1/incidents/diagnose` — wyszukuje runbooki, zbiera snapshot Kubernetes, uruchamia analizę agentów i zwraca oba źródła dowodów. Snapshot jest utrwalany przy przebiegu agenta i dostępny w polu `kubernetes_diagnostics` odpowiedzi.

Jeśli Kubernetes jest niedostępny podczas diagnozy incydentu, system nadal może przygotować ograniczoną analizę na podstawie zgłoszenia i runbooków, ale `kubernetes_diagnostics.status` będzie równe `unavailable`, a błąd zostanie przekazany agentom i zwrócony w odpowiedzi. Agenci mają obowiązek jawnie zaznaczyć brak danych klastra, a nie wyciągać wniosków z ich nieobecności.

## Scenariusze odtwarzalne

Golden Dataset powinien opierać się na scenariuszach opisanych w [k3s_lab/README.md](../k3s_lab/README.md):

- `web-down` — Deployment `web` zostaje przeskalowany do zera;
- `api-bad-image` — Deployment `api` otrzymuje nieistniejący tag obrazu; przyczynę należy potwierdzić zdarzeniami poda;
- `cache-kill` — usunięty pod `cache` zostaje odtworzony przez Deployment.
- `orders-api-db-auth` — `orders-api` zapisuje sekwencję błędów uwierzytelnienia PostgreSQL i przechodzi w stan not-ready bez restartowania procesu; po diagnozie można wyzerować symulację przez `/fixme`.

Scenariusze są wyzwalane i odtwarzane ręcznie przez skrypty laboratorium. `orders-api` udostępnia testowe endpointy `/break/db-auth` i `/fixme`; awaria nie restartuje procesu, dzięki czemu endpoint naprawczy pozostaje dostępny przez port-forward. Sam agent pozostaje diagnostyczny i nie wykonuje napraw.

## Granice bezpieczeństwa i prywatność

- Dostęp Kubernetes jest ograniczony RBAC-em; nie udostępnia agentom shella ani narzędzi modyfikujących klaster.
- Nazwy zasobów i treści logów/zdarzeń są niezaufanym wejściem. Prompty instruują agentów, by traktowali je jako dane, a nie polecenia.
- Logi mogą zawierać dane wrażliwe. Są dołączane do żądania skonfigurowanego dostawcy LLM, a snapshot jest zapisywany w PostgreSQL wraz z przebiegiem agenta. Przed użyciem z dostawcą zewnętrznym należy uwzględnić jego warunki przetwarzania danych i politykę retencji.
- Lokalny Compose nie zapewnia TLS, indywidualnej tożsamości operatora ani produkcyjnego zarządzania sekretami. Nie wystawiaj usług bez dodatkowego utwardzenia.

## Ustawienia Kubernetes

| Zmienna | Domyślna wartość | Znaczenie |
| --- | --- | --- |
| `KUBECONFIG` | brak poza konfiguracją Compose | Ścieżka do kubeconfigu. Brak konfiguracji nie uruchamia domyślnego kubeconfigu użytkownika hosta. |
| `KUBERNETES_NAMESPACE` | `devops-lab` | Namespace, z którego pobierane są workloady, usługi, endpointy i zdarzenia. |
| `KUBERNETES_LOGS_TAIL_LINES` | `100` | Liczba ostatnich linii na kontener w snapshotcie, maksymalnie `500`. |
| `KUBERNETES_MAX_PODS_WITH_LOGS` | `20` | Maksymalna liczba podów objętych zbieraniem logów, maksymalnie `100`. |
| `OLLAMA_NUM_CTX` | `8192` | Rozmiar okna kontekstu przekazywany Ollama; zakres `2048`–`32768`. |

Zmiana namespace nie rozszerza uprawnień ServiceAccount; RBAC musi nadal ograniczać dostęp do zamierzonego zakresu.

Kontekst przekazywany modelowi jest skracany do najistotniejszych zasobów, ale nadal może być większy od limitu modelu. Ollama otrzymuje `num_ctx` z `OLLAMA_NUM_CTX`; zwiększenie tej wartości podnosi zużycie pamięci. Raport zawsze należy porównać ze snapshotem `kubernetes_diagnostics`, który jest pełniejszym źródłem dowodów.

## Stan implementacji

Kod integracji znajduje się w `app/kubernetes_diagnostics.py`; endpointy i dołączenie dowodów do diagnozy są w `app/main.py` i `app/agents.py`. Model przebiegu zapisuje snapshot Kubernetes, a migracja `0002_k8s_diagnostics` dodaje tę kolumnę do `agent_runs`.

Integracja pozostaje ograniczona do lokalnego laboratorium. Nie jest to autonomiczny operator Kubernetes, system alertowy ani zamiennik monitoringu SRE. Testy automatyczne używają atrap klienta Kubernetes; rzeczywista łączność wymaga działającego Docker Desktop, klastra k3d oraz aktualnego kubeconfigu.
