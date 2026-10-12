from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Query, status
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.agents import diagnose, provider_metadata
from app.auth import require_api_key
from app.config import settings
from app.db import get_db
from app.llm import ProviderConfigurationError
from app.kubernetes_diagnostics import (
    KubernetesDiagnostics,
    KubernetesDiagnosticsUnavailable,
    KubernetesResourceNotFound,
    kubernetes_diagnostics,
)
from app.models import AgentRun, Approval, AuditEvent, Incident, KnowledgeDocument, utcnow
from app.retrieval import knowledge_index
from app.schemas import (
    ApprovalCreate,
    ApprovalDecision,
    IncidentCreate,
    KnowledgeCreate,
    KnowledgeRead,
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield


app = FastAPI(
    title="AI DevOps Team API",
    description="Platforma do diagnozy incydentów, RAG i zatwierdzania rekomendowanych działań.",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health")
def health(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    return {"status": "ok", "database": "ok"}


def get_kubernetes_diagnostics() -> KubernetesDiagnostics:
    return kubernetes_diagnostics


@app.get("/api/v1/k8s/diagnostics")
def get_cluster_diagnostics(
    _: str = Depends(require_api_key),
    diagnostics: KubernetesDiagnostics = Depends(get_kubernetes_diagnostics),
):
    try:
        return diagnostics.collect()
    except KubernetesDiagnosticsUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/api/v1/k8s/pods/{pod_name}/logs")
def get_pod_logs(
    pod_name: str,
    tail_lines: int = Query(default=settings.kubernetes_logs_tail_lines, ge=1, le=500),
    container: str | None = None,
    _: str = Depends(require_api_key),
    diagnostics: KubernetesDiagnostics = Depends(get_kubernetes_diagnostics),
):
    try:
        return diagnostics.get_pod_logs(pod_name, tail_lines, container)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except KubernetesResourceNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except KubernetesDiagnosticsUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/api/v1/knowledge", response_model=KnowledgeRead, status_code=status.HTTP_201_CREATED)
def add_knowledge(
    payload: KnowledgeCreate,
    db: Session = Depends(get_db),
    _: str = Depends(require_api_key),
):
    document_id = str(payload.id or uuid4())
    document = db.get(KnowledgeDocument, document_id)
    if document is None:
        document = KnowledgeDocument(id=document_id, **payload.model_dump(exclude={"id"}))
        db.add(document)
    else:
        document.title = payload.title
        document.content = payload.content
        document.source = payload.source
        document.updated_at = utcnow()
    db.commit()
    db.refresh(document)

    try:
        knowledge_index.upsert(document.id, document.title, document.content, document.source)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Document saved in PostgreSQL but indexing in Qdrant failed: {exc}",
        ) from exc
    return document


@app.get("/api/v1/knowledge", response_model=list[KnowledgeRead])
def list_knowledge(
    db: Session = Depends(get_db),
    _: str = Depends(require_api_key),
):
    return list(db.scalars(select(KnowledgeDocument).order_by(KnowledgeDocument.created_at.desc())))


@app.delete("/api/v1/knowledge/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_knowledge(
    document_id: str,
    db: Session = Depends(get_db),
    _: str = Depends(require_api_key),
):
    document = db.get(KnowledgeDocument, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Knowledge document not found")
    try:
        knowledge_index.delete(document.id)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Could not remove document from Qdrant: {exc}") from exc
    db.delete(document)
    db.commit()


@app.post("/api/v1/incidents/diagnose")
def diagnose_incident(
    payload: IncidentCreate,
    db: Session = Depends(get_db),
    _: str = Depends(require_api_key),
    diagnostics: KubernetesDiagnostics = Depends(get_kubernetes_diagnostics),
):
    try:
        evidence = knowledge_index.search(
            f"{payload.title}\n{payload.description}\nEnvironment: {payload.environment}",
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Knowledge retrieval failed: {exc}") from exc

    try:
        cluster_diagnostics = diagnostics.collect()
    except KubernetesDiagnosticsUnavailable as exc:
        cluster_diagnostics = {
            "status": "unavailable",
            "namespace": settings.kubernetes_namespace,
            "error": str(exc),
        }

    incident = Incident(**payload.model_dump())
    db.add(incident)
    db.flush()
    try:
        agent_reports, report = diagnose(
            payload.title,
            payload.description,
            payload.environment,
            evidence,
            cluster_diagnostics,
        )
    except ProviderConfigurationError as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=502, detail=f"LLM diagnosis failed: {exc}") from exc

    provider, model = provider_metadata()
    run = AgentRun(
        incident_id=incident.id,
        provider=provider,
        model=model,
        evidence=evidence,
        kubernetes_diagnostics=cluster_diagnostics,
        agent_reports=agent_reports,
        final_report=report,
    )
    db.add(run)
    db.flush()
    db.add(
        AuditEvent(
            event_type="incident.diagnosed",
            entity_id=incident.id,
            actor="api-key",
            details={"agent_run_id": run.id, "provider": provider, "model": model},
        )
    )
    db.commit()
    return {
        "incident_id": incident.id,
        "agent_run_id": run.id,
        "provider": provider,
        "model": model,
        "evidence": evidence,
        "kubernetes_diagnostics": cluster_diagnostics,
        "agent_reports": agent_reports,
        "report": report,
        "disclaimer": "Raport AI jest hipotezą do weryfikacji; platforma nie wykonuje zmian infrastruktury.",
    }


@app.post("/api/v1/approvals", status_code=status.HTTP_201_CREATED)
def create_approval(
    payload: ApprovalCreate,
    db: Session = Depends(get_db),
    _: str = Depends(require_api_key),
):
    if payload.incident_id and db.get(Incident, payload.incident_id) is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    approval = Approval(**payload.model_dump())
    db.add(approval)
    db.flush()
    db.add(
        AuditEvent(
            event_type="approval.requested",
            entity_id=approval.id,
            actor=payload.requested_by,
            details={"risk_level": payload.risk_level},
        )
    )
    db.commit()
    db.refresh(approval)
    return approval


@app.post("/api/v1/approvals/{approval_id}/decision")
def decide_approval(
    approval_id: str,
    payload: ApprovalDecision,
    db: Session = Depends(get_db),
    _: str = Depends(require_api_key),
):
    approval = db.get(Approval, approval_id)
    if approval is None:
        raise HTTPException(status_code=404, detail="Approval not found")
    if approval.status != "pending":
        raise HTTPException(status_code=409, detail="Approval has already been decided")
    approval.status = payload.decision
    approval.decided_by = payload.decided_by
    approval.decision_note = payload.note
    approval.decided_at = utcnow()
    db.add(
        AuditEvent(
            event_type=f"approval.{payload.decision}",
            entity_id=approval.id,
            actor=payload.decided_by,
            details={"note": payload.note},
        )
    )
    db.commit()
    db.refresh(approval)
    return approval


@app.get("/api/v1/audit")
def list_audit_events(
    limit: int = 100,
    db: Session = Depends(get_db),
    _: str = Depends(require_api_key),
):
    if not 1 <= limit <= 500:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 500")
    events = db.scalars(select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(limit))
    return list(events)
