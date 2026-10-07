# AI DevOps Team

Minimalny, uruchamialny szkielet platformy inspirowany artykułem: zespół agentów, RAG dla runbooków, centralna baza danych, audyt i zatwierdzanie zmian przez człowieka.

## Architektura

- **FastAPI** — API platformy i jej dokumentacja OpenAPI.
- **PostgreSQL + Alembic** — incydenty, runbooki, przebiegi agentów, zatwierdzenia i audyt. Migracje są wykonywane przy starcie kontenera API.
- **Qdrant + FastEmbed** — semantyczne wyszukiwanie wiedzy; model `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` pobiera się przy pierwszym indeksowaniu.
- **Agenci** — triage, observability i SecOps pracują na tej samej sprawie; supervisor scala ich raporty.
- **Anthropic, OpenAI lub Ollama** — wybór dostawcy przez zmienne środowiskowe, niezależny od reszty API.
- **Human-in-the-loop** — wnioski o zatwierdzenie i decyzje są zapisywane w audycie.

Wersja bazowa celowo nie łączy się z klastrami, chmurą, monitoringiem ani shell’em i nie wykonuje działań naprawczych. Raport agenta jest hipotezą, a nie dowodem ani poleceniem wykonanym w infrastrukturze.

Compose jest konfiguracją laboratoryjną: API i Ollama są publikowane na hosta bez TLS. Przed udostępnieniem poza zaufanym komputerem dodaj TLS, właściwe uwierzytelnianie/RBAC, zarządzanie sekretami i ograniczenia sieciowe; nie traktuj wspólnego klucza API jako tożsamości operatora.

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

Pozostałe endpointy: `GET /api/v1/knowledge`, `DELETE /api/v1/knowledge/{id}`, `POST /api/v1/approvals`, `POST /api/v1/approvals/{id}/decision`, `GET /api/v1/audit`.

Wspólny klucz API jest przeznaczony do lokalnego laboratorium; nie zapewnia indywidualnej tożsamości zatwierdzającego ani zastępstwa dla SSO/RBAC w środowisku produkcyjnym. Decyzja approval jest tylko wpisem audytowym — nie uruchamia zaakceptowanej akcji.

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
