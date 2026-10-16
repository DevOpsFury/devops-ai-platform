# AI DevOps Team

Minimalny, uruchamialny szkielet platformy: zespół agentów, RAG dla runbooków, centralna baza danych, audyt i zatwierdzanie zmian przez człowieka.

## Architektura

- **FastAPI** — API platformy i jej dokumentacja OpenAPI.
- **PostgreSQL + Alembic** — incydenty, runbooki, przebiegi agentów, zatwierdzenia i audyt. Migracje są wykonywane przy starcie kontenera API.
- **Qdrant + FastEmbed** — semantyczne wyszukiwanie wiedzy; model `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` pobiera się przy pierwszym indeksowaniu.
- **Redis (`cache`)** — pomocniczy serwis Compose dostępny na porcie `6379`; obecnie nie jest podłączony do kodu aplikacji. Jest niezależny od testowego Deploymentu `cache` w k3s.
- **Agenci** — triage, observability i SecOps analizują runbooki oraz read-only snapshot diagnostyczny lokalnego klastra k3s; supervisor scala ich raporty.
- **Anthropic, OpenAI lub Ollama** — wybór dostawcy przez zmienne środowiskowe, niezależny od reszty API.
- **Human-in-the-loop** — wnioski o zatwierdzenie i decyzje są zapisywane w audycie.

API odczytuje stan węzłów, podów, Deploymentów, ReplicaSetów, usług, Endpointów, zdarzeń i ograniczoną liczbę ostatnich linii logów z namespace `devops-lab`. Agenci mogą na tej podstawie formułować rekomendacje; dostęp Kubernetes jest wyłącznie read-only i nie obejmuje innych namespace’ów. System nie łączy się z zewnętrznym monitoringiem ani repozytorium wdrożeń i nie wykonuje działań naprawczych. Raport agenta pozostaje hipotezą do weryfikacji.

Logi są przekazywane do wybranego dostawcy LLM i zapisywane wraz z przebiegiem w PostgreSQL; mogą zawierać dane wrażliwe. Compose jest konfiguracją laboratoryjną: API i Ollama są publikowane na hosta bez TLS. Przed udostępnieniem poza zaufanym komputerem dodaj TLS, właściwe uwierzytelnianie/RBAC, zarządzanie sekretami i ograniczenia sieciowe; nie traktuj wspólnego klucza API jako tożsamości operatora.

## Uruchomienie

Wymagane: Docker z Compose. W katalogu projektu:

```sh
cp .env.example .env
```

Zmień `APP_API_KEY` i `POSTGRES_PASSWORD` na własne losowe wartości przed uruchomieniem. Hasło PostgreSQL powinno być alfanumeryczne, ponieważ Compose używa go także w URL połączenia. Następnie:

```sh
docker compose up --build -d
```

API: <http://localhost:8000>; Swagger UI: <http://localhost:8000/docs>; health check: <http://localhost:8000/health>.

Domyślny backend LLM to Ollama. Uruchom go wraz z platformą i pobierz przykładowy model:

```sh
docker compose up --build -d
docker compose exec ollama ollama pull qwen2.5:3b
```

Pierwsze indeksowanie wiedzy pobiera model embeddingów FastEmbed i może potrwać dłużej; kontener API potrzebuje dostępu do internetu podczas pobierania modelu.

### Zmiana dostawcy LLM

Ustaw w `.env`, a następnie zrestartuj API:

```dotenv
LLM_PROVIDER=anthropic
LLM_MODEL=claude-3-5-haiku-latest
ANTHROPIC_API_KEY=...
```

albo:

```dotenv
LLM_PROVIDER=openai
LLM_MODEL=gpt-4o-mini
OPENAI_API_KEY=...
```

Ollama:

```dotenv
LLM_PROVIDER=ollama
LLM_MODEL=qwen2.5:3b
LLM_BASE_URL=http://ollama:11434/v1
```

API keys dostawców są potrzebne tylko dla wybranego backendu. Nie umieszczaj sekretów w repozytorium.

## API

Operacje z wyjątkiem `/health` wymagają nagłówka `X-API-Key` równemu `APP_API_KEY`.

Dodanie runbooka (indeksowanie w PostgreSQL i Qdrant):

```sh
curl -X POST http://localhost:8000/api/v1/knowledge \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: replace-this-with-a-long-random-value' \
  -d '{"title":"Runbook: błędy połączeń do bazy","source":"ops/runbooks/database.md","content":"Sprawdź dostępność PostgreSQL, błędy uwierzytelniania, pulę połączeń i ostatnie wdrożenia. Nie restartuj produkcji bez zatwierdzenia."}'
```

Diagnoza incydentu:

```sh
curl -X POST http://localhost:8000/api/v1/incidents/diagnose \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: replace-this-with-a-long-random-value' \
  -d '{"title":"Wzrost błędów timeout","description":"Po wdrożeniu wzrosła liczba timeoutów. Brak jeszcze danych z metryk.","environment":"staging"}'
```

Pozostałe endpointy: `GET /api/v1/k8s/diagnostics`, `GET /api/v1/k8s/pods/{pod_name}/logs`, `GET /api/v1/knowledge`, `DELETE /api/v1/knowledge/{id}`, `POST /api/v1/approvals`, `POST /api/v1/approvals/{id}/decision`, `GET /api/v1/audit`.

Wspólny klucz API jest przeznaczony do lokalnego laboratorium; nie zapewnia indywidualnej tożsamości zatwierdzającego ani zastępstwa dla SSO/RBAC w środowisku produkcyjnym. Decyzja approval jest tylko wpisem audytowym — nie uruchamia zaakceptowanej akcji.

## Lab k3s

Lokalny klaster k3s dostępny dla kontenera API, cztery testowe usługi oraz skrypty do wywoływania i odtwarzania awarii opisano w [k3s_lab/README.md](./k3s_lab/README.md).
Szczegółowy opis zakresu diagnostyki, endpointów, RBAC i ograniczeń prywatności znajduje się w [docs/README.md](./docs/README.md).

### Pełny use case: od awarii do weryfikacji

Poniższy przebieg pokazuje pracę operatora z agentami i zatwierdzaniem zmian. Wymaga uruchomionej aplikacji, skonfigurowanego dostawcy LLM oraz klastra przygotowanego poleceniem `./k3s_lab/start.sh`.

1. **Wywołaj problem i sprawdź stan klastra.** Przykładowo wyłącz testową usługę WWW:

   ```sh
   ./k3s_lab/break.sh web-down
   ./k3s_lab/status.sh
   ```

   W statusie deployment `web` będzie miał zero replik.

2. **Przekaż agentom objawy do zbadania.** W opisie podaj zaobserwowane fakty i środowisko, a nie tylko oczekiwane rozwiązanie:

   ```sh
   API_URL=http://localhost:8000
   API_KEY='wartosc-APP_API_KEY-z-pliku-.env'

   curl -X POST "$API_URL/api/v1/incidents/diagnose" \
     -H 'Content-Type: application/json' \
     -H "X-API-Key: $API_KEY" \
     -d '{
       "title": "Usługa web nie odpowiada",
       "description": "W klastrze k3s-lab w namespace devops-lab deployment web ma 0/0 dostępnych replik. Problem pojawił się podczas testu web-down.",
       "environment": "devops-lab"
     }'
   ```

   Odpowiedź zawiera raporty agentów, rekomendację, snapshot aktualnego stanu klastra (`kubernetes_diagnostics`) oraz identyfikatory incydentu i przebiegu. API samodzielnie pobiera statusy, zdarzenia i ograniczone logi w `devops-lab`; agent formułuje hipotezę na podstawie tych danych, a nie wykonuje naprawy.

3. **Utwórz prośbę o decyzję.** Jeśli rekomendacja wymaga działania, opisz je konkretnie i utwórz wniosek approval:

   ```sh
   curl -X POST "$API_URL/api/v1/approvals" \
     -H 'Content-Type: application/json' \
     -H "X-API-Key: $API_KEY" \
     -d '{
       "requested_action": "Przywrócić deployment web do jednej repliki w namespace devops-lab przez zastosowanie manifestów bazowych laboratorium.",
       "risk_level": "low",
       "requested_by": "operator"
     }'
   ```

   Zapisz `id` z odpowiedzi. Operator może przejrzeć wniosek, a następnie wysłać decyzję (podstaw identyfikator otrzymany powyżej):

   ```sh
   curl -X POST "$API_URL/api/v1/approvals/<approval-id>/decision" \
     -H 'Content-Type: application/json' \
     -H "X-API-Key: $API_KEY" \
     -d '{
       "decision": "approved",
       "decided_by": "operator",
       "note": "Zatwierdzono przywrócenie usługi testowej."
     }'
   ```

   Decyzja jest rejestrowana w bazie i audycie, ale **nie wykonuje naprawy**. Działanie w klastrze wykonaj oddzielnie, ręcznie i tylko w tym lokalnym laboratorium:

   ```sh
   ./k3s_lab/recover.sh
   ./k3s_lab/status.sh
   ```

4. **Sprawdź rezultat i zamknij pętlę.** Potwierdź w statusie, że deployment `web` ma jedną dostępną replikę, a pody usług są gotowe. Następnie ponownie wyślij diagnozę z aktualnym wynikiem w opisie, aby uzyskać raport kontrolny; API nie prowadzi automatycznego monitoringu ani nie weryfikuje, czy zatwierdzona akcja została wykonana.

   ```sh
   curl -X POST "$API_URL/api/v1/incidents/diagnose" \
     -H 'Content-Type: application/json' \
     -H "X-API-Key: $API_KEY" \
     -d '{
       "title": "Weryfikacja naprawy usługi web",
       "description": "Po ręcznym uruchomieniu ./k3s_lab/recover.sh deployment web ma 1/1 dostępnych replik, a jego pod jest gotowy. Wynik sprawdzono poleceniem ./k3s_lab/status.sh.",
       "environment": "devops-lab"
     }'
   ```

Ten scenariusz demonstruje obecny przepływ human-in-the-loop: **operator zgłasza objawy → agenci przygotowują diagnozę i rekomendację → operator podejmuje i zapisuje decyzję → operator wykonuje zatwierdzoną czynność → operator sprawdza i przekazuje wynik**. Aplikacja nie wykonuje poleceń w klastrze; dostęp Kubernetes skonfigurowany dla kontenera jest tylko do odczytu.

## Aktualizacja schematu bazy

Przy uruchomieniu Compose migracje Alembic wykonują się automatycznie. Nową migrację można wygenerować i zastosować wewnątrz kontenera:

```sh
docker compose up -d --build api
```

Przebudowa i ponowne uruchomienie API wykonuje `alembic upgrade head`. Aby wygenerować migrację z nowo dodanych lub zmienionych modeli i zapisać ją w katalogu projektu, uruchom:

```sh
docker compose run --rm -v ./app:/app/app -v ./alembic:/app/alembic api alembic revision --autogenerate -m "opis zmiany"
```

Po zmianach modeli sprawdź wygenerowaną migrację i dodaj ją do repozytorium. Nie uruchamiaj `alembic downgrade` na danych produkcyjnych bez planu kopii i odtworzenia.

## Testy lokalne

Wymagany Python 3.12+:

```sh
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
APP_API_KEY=test-key DATABASE_URL=sqlite:///./test.db QDRANT_URL=http://localhost:6333 pytest
```
