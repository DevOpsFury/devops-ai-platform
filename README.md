# AI DevOps Team

[Polski](./README.pl.md)

A minimal, runnable platform skeleton: an agent team, RAG for runbooks, a central database, auditing, and human approval of changes.

## Architecture

- **FastAPI** — the platform API and its OpenAPI documentation.
- **PostgreSQL + Alembic** — incidents, runbooks, agent runs, approvals, and audit records. Migrations run when the API container starts.
- **Qdrant + FastEmbed** — semantic knowledge search; the `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` model is downloaded during the first indexing operation.
- **Redis (`cache`)** — an auxiliary Compose service available on port `6379`; it is not currently connected to the application code. It is independent of the test `cache` Deployment in k3s.
- **Agents** — triage, observability, and SecOps analyze runbooks and a read-only diagnostic snapshot of the local k3s cluster; the supervisor combines their reports.
- **Anthropic, OpenAI, or Ollama** — choose a provider using environment variables, independently of the rest of the API.
- **Human-in-the-loop** — approval requests and decisions are recorded in the audit log.

The API reads the state of nodes, pods, Deployments, ReplicaSets, Services, Endpoints, events, and a limited number of recent log lines from the `devops-lab` namespace. Agents can use this information to make recommendations; Kubernetes access is read-only and does not include other namespaces. The system does not connect to external monitoring or a deployment repository and does not perform remediation. An agent report remains a hypothesis to be verified.

Logs are sent to the selected LLM provider and stored along with the run in PostgreSQL; they may contain sensitive data. Compose is configured for a lab environment: the API and Ollama are published to the host without TLS. Before exposing the platform beyond a trusted computer, add TLS, appropriate authentication/RBAC, secrets management, and network restrictions; do not treat a shared API key as an operator identity.

## Getting started

Requirements: Docker with Compose. From the project directory:

```sh
cp .env.example .env
```

Change `APP_API_KEY` and `POSTGRES_PASSWORD` to your own random values before starting. The PostgreSQL password should be alphanumeric because Compose also uses it in the connection URL. Then run:

```sh
docker compose up --build -d
```

API: <http://localhost:8000>; Swagger UI: <http://localhost:8000/docs>; health check: <http://localhost:8000/health>.

The default LLM backend is Ollama. Start it with the platform and pull an example model:

```sh
docker compose up --build -d
docker compose exec ollama ollama pull qwen2.5:3b
```

The first knowledge indexing operation downloads the FastEmbed embedding model and may take longer; the API container needs internet access while the model is being downloaded.

### Changing the LLM provider

Set the values in `.env`, then restart the API:

```dotenv
LLM_PROVIDER=anthropic
LLM_MODEL=claude-3-5-haiku-latest
ANTHROPIC_API_KEY=...
```

or:

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

Provider API keys are needed only for the selected backend. Do not put secrets in the repository.

## API

All operations except `/health` require an `X-API-Key` header whose value matches `APP_API_KEY`.

Add a runbook (indexed in PostgreSQL and Qdrant):

```sh
curl -X POST http://localhost:8000/api/v1/knowledge \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: replace-this-with-a-long-random-value' \
  -d '{"title":"Runbook: database connection errors","source":"ops/runbooks/database.md","content":"Check PostgreSQL availability, authentication errors, the connection pool, and recent deployments. Do not restart production without approval."}'
```

Diagnose an incident:

```sh
curl -X POST http://localhost:8000/api/v1/incidents/diagnose \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: replace-this-with-a-long-random-value' \
  -d '{"title":"Increase in timeout errors","description":"Timeouts have increased since deployment. There is no metrics data yet.","environment":"staging"}'
```

Other endpoints: `GET /api/v1/k8s/diagnostics`, `GET /api/v1/k8s/pods/{pod_name}/logs`, `GET /api/v1/knowledge`, `DELETE /api/v1/knowledge/{id}`, `POST /api/v1/approvals`, `POST /api/v1/approvals/{id}/decision`, `GET /api/v1/audit`.

The shared API key is intended for a local lab; it does not provide individual approver identity or replace SSO/RBAC in production. An approval decision is only an audit record — it does not execute the approved action.

## k3s lab

The local k3s cluster available to the API container, four test services, and scripts for triggering and recovering from failures are described in [k3s_lab/README.md](./k3s_lab/README.md).

For details about diagnostic scope, endpoints, RBAC, and privacy limitations, see [docs/README.md](./docs/README.md).

### End-to-end use case: from failure to verification

The following walkthrough shows an operator working with agents and approvals. It requires a running application, a configured LLM provider, and a cluster initialized with `./k3s_lab/start.sh`.

1. **Trigger an issue and check the cluster state.** For example, take down the test web service:

   ```sh
   ./k3s_lab/break.sh web-down
   ./k3s_lab/status.sh
   ```

   The `web` Deployment will show zero replicas in the status.

2. **Give the agents symptoms to investigate.** Describe the observed facts and the environment, rather than only stating the expected solution:

   ```sh
   API_URL=http://localhost:8000
   API_KEY='APP_API_KEY-value-from-.env'

   curl -X POST "$API_URL/api/v1/incidents/diagnose" \
     -H 'Content-Type: application/json' \
     -H "X-API-Key: $API_KEY" \
     -d '{
       "title": "The web service is not responding",
       "description": "In the k3s-lab cluster, in the devops-lab namespace, the web Deployment has 0/0 available replicas. The problem appeared during the web-down test.",
       "environment": "devops-lab"
     }'
   ```

   The response includes agent reports, a recommendation, a snapshot of the current cluster state (`kubernetes_diagnostics`), and incident and run IDs. The API fetches statuses, events, and a limited number of logs from `devops-lab`; the agent forms a hypothesis based on this data and does not perform remediation.

3. **Create an approval request.** If the recommendation calls for action, describe it specifically and create an approval request:

   ```sh
   curl -X POST "$API_URL/api/v1/approvals" \
     -H 'Content-Type: application/json' \
     -H "X-API-Key: $API_KEY" \
     -d '{
       "requested_action": "Restore the web Deployment to one replica in the devops-lab namespace by applying the lab baseline manifests.",
       "risk_level": "low",
       "requested_by": "operator"
     }'
   ```

   Save the `id` from the response. The operator can review the request and then submit a decision (replace the placeholder with the ID received above):

   ```sh
   curl -X POST "$API_URL/api/v1/approvals/<approval-id>/decision" \
     -H 'Content-Type: application/json' \
     -H "X-API-Key: $API_KEY" \
     -d '{
       "decision": "approved",
       "decided_by": "operator",
       "note": "Approved restoring the test service."
     }'
   ```

   The decision is recorded in the database and audit log, but **does not perform remediation**. Carry out the cluster action separately, manually, and only in this local lab:

   ```sh
   ./k3s_lab/recover.sh
   ./k3s_lab/status.sh
   ```

4. **Check the outcome and close the loop.** Confirm in the status that the `web` Deployment has one available replica and the service pods are ready. Then submit a new diagnosis with the current outcome in the description to get a verification report; the API does not perform automatic monitoring or verify whether the approved action was carried out.

   ```sh
   curl -X POST "$API_URL/api/v1/incidents/diagnose" \
     -H 'Content-Type: application/json' \
     -H "X-API-Key: $API_KEY" \
     -d '{
       "title": "Verify the web service recovery",
       "description": "After manually running ./k3s_lab/recover.sh, the web Deployment has 1/1 available replicas and its pod is ready. The result was checked with ./k3s_lab/status.sh.",
       "environment": "devops-lab"
     }'
   ```

This scenario demonstrates the current human-in-the-loop workflow: **the operator reports symptoms → agents prepare a diagnosis and recommendation → the operator makes and records a decision → the operator performs the approved action → the operator checks and reports the outcome**. The application does not run commands in the cluster; the Kubernetes access configured for the container is read-only.

## Updating the database schema

When Compose starts, Alembic migrations run automatically. A new migration can be generated and applied inside the container:

```sh
docker compose up -d --build api
```

Rebuilding and restarting the API runs `alembic upgrade head`. To generate a migration from newly added or changed models and save it in the project directory, run:

```sh
docker compose run --rm -v ./app:/app/app -v ./alembic:/app/alembic api alembic revision --autogenerate -m "describe the change"
```

After changing models, review the generated migration and add it to the repository. Do not run `alembic downgrade` on production data without a backup and recovery plan.

## Local tests

Python 3.12+ is required:

```sh
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
APP_API_KEY=test-key DATABASE_URL=sqlite:///./test.db QDRANT_URL=http://localhost:6333 pytest
```
