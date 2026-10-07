from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.db import Base, get_db
from app.main import app

API_HEADERS = {"X-API-Key": settings.app_api_key.get_secret_value()}


def test_health_route_reports_database_ready():
    class FakeSession:
        def execute(self, _):
            return 1

    def fake_db():
        yield FakeSession()

    app.dependency_overrides[get_db] = fake_db
    with TestClient(app) as client:
        response = client.get("/health")
    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_api_key_is_required():
    with TestClient(app) as client:
        response = client.get("/api/v1/knowledge")
    assert response.status_code == 401


def test_approval_decision_is_audited():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override_db():
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(app) as client:
            created = client.post(
                "/api/v1/approvals",
                headers=API_HEADERS,
                json={
                    "requested_action": "Restart service in staging",
                    "risk_level": "medium",
                    "requested_by": "on-call",
                },
            )
            assert created.status_code == 201
            approval_id = created.json()["id"]

            decided = client.post(
                f"/api/v1/approvals/{approval_id}/decision",
                headers=API_HEADERS,
                json={"decision": "approved", "decided_by": "reviewer", "note": "Reviewed"},
            )
            assert decided.status_code == 200
            assert decided.json()["status"] == "approved"

            audit = client.get("/api/v1/audit", headers=API_HEADERS)
            assert audit.status_code == 200
            assert {event["event_type"] for event in audit.json()} == {
                "approval.requested",
                "approval.approved",
            }
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
