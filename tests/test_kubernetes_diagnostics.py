from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import main
from app import agents
from app.config import settings
from app.db import Base, get_db
from app.kubernetes_diagnostics import (
    KubernetesDiagnostics,
    KubernetesDiagnosticsUnavailable,
)
from app.models import AgentRun

API_HEADERS = {"X-API-Key": settings.app_api_key.get_secret_value()}


class FakeDiagnostics:
    def __init__(self, snapshot):
        self.snapshot = snapshot

    def collect(self):
        return self.snapshot

    def get_pod_logs(self, pod_name, tail_lines, container=None):
        return {
            "namespace": "devops-lab",
            "pod_name": pod_name,
            "tail_lines": tail_lines,
            "container": container,
        }


def test_diagnostics_endpoints_require_api_key():
    with TestClient(main.app) as client:
        response = client.get("/api/v1/k8s/diagnostics")
    assert response.status_code == 401


def test_pod_logs_endpoint_rejects_invalid_name_before_cluster_access():
    diagnostics = KubernetesDiagnostics(kubeconfig=None)
    main.app.dependency_overrides[main.get_kubernetes_diagnostics] = lambda: diagnostics
    try:
        with TestClient(main.app) as client:
            response = client.get(
                "/api/v1/k8s/pods/api%3Brm/logs",
                headers=API_HEADERS,
            )
        assert response.status_code == 422
        assert "valid Kubernetes pod name" in response.json()["detail"]
    finally:
        main.app.dependency_overrides.clear()


def test_diagnostics_and_logs_routes_return_read_only_data():
    snapshot = {"status": "ok", "namespace": "devops-lab", "pods": []}
    main.app.dependency_overrides[main.get_kubernetes_diagnostics] = lambda: FakeDiagnostics(
        snapshot
    )
    try:
        with TestClient(main.app) as client:
            diagnostics = client.get(
                "/api/v1/k8s/diagnostics",
                headers=API_HEADERS,
            )
            logs = client.get(
                "/api/v1/k8s/pods/web-123/logs?tail_lines=25&container=nginx",
                headers=API_HEADERS,
            )
        assert diagnostics.status_code == 200
        assert diagnostics.json() == snapshot
        assert logs.status_code == 200
        assert logs.json() == {
            "namespace": "devops-lab",
            "pod_name": "web-123",
            "tail_lines": 25,
            "container": "nginx",
        }
    finally:
        main.app.dependency_overrides.clear()


def test_diagnostic_route_reports_unavailable_cluster():
    class UnavailableDiagnostics:
        def collect(self):
            raise KubernetesDiagnosticsUnavailable("kubeconfig unavailable")

    main.app.dependency_overrides[main.get_kubernetes_diagnostics] = (
        lambda: UnavailableDiagnostics()
    )
    try:
        with TestClient(main.app) as client:
            response = client.get(
                "/api/v1/k8s/diagnostics",
                headers=API_HEADERS,
            )
        assert response.status_code == 503
        assert response.json()["detail"] == "kubeconfig unavailable"
    finally:
        main.app.dependency_overrides.clear()


def test_incident_diagnosis_includes_and_persists_cluster_evidence(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override_db():
        with session_factory() as session:
            yield session

    cluster_snapshot = {
        "status": "ok",
        "namespace": "devops-lab",
        "pods": [{"name": "api-123", "phase": "Running"}],
    }
    main.app.dependency_overrides[get_db] = override_db
    main.app.dependency_overrides[main.get_kubernetes_diagnostics] = lambda: FakeDiagnostics(
        cluster_snapshot
    )
    monkeypatch.setattr(main.knowledge_index, "search", lambda _query: [])
    monkeypatch.setattr(
        main,
        "diagnose",
        lambda *_args: ({"triage": "Pod api-123 działa."}, "Raport testowy."),
    )
    monkeypatch.setattr(main, "provider_metadata", lambda: ("test", "test-model"))
    try:
        with TestClient(main.app) as client:
            response = client.post(
                "/api/v1/incidents/diagnose",
                headers=API_HEADERS,
                json={
                    "title": "API niedostępne",
                    "description": "Użytkownicy zgłaszają błędy.",
                    "environment": "devops-lab",
                },
            )
        assert response.status_code == 200
        body = response.json()
        assert body["kubernetes_diagnostics"] == cluster_snapshot
        with session_factory() as session:
            run = session.get(AgentRun, body["agent_run_id"])
            assert run is not None
            assert run.kubernetes_diagnostics == cluster_snapshot
    finally:
        main.app.dependency_overrides.clear()
        engine.dispose()


def test_collect_builds_bounded_pod_and_cluster_snapshot(monkeypatch):
    condition = SimpleNamespace(
        type="Ready",
        status="True",
        reason=None,
        message=None,
        last_transition_time=None,
    )
    container_state = SimpleNamespace(running=SimpleNamespace(started_at=None))
    pod = SimpleNamespace(
        metadata=SimpleNamespace(name="web-123", namespace="devops-lab"),
        status=SimpleNamespace(
            phase="Running",
            conditions=[condition],
            container_statuses=[
                SimpleNamespace(
                    name="nginx",
                    ready=True,
                    restart_count=1,
                    state=container_state,
                    last_state=SimpleNamespace(terminated=None),
                )
            ],
            pod_ip="10.42.0.5",
            start_time=None,
        ),
        spec=SimpleNamespace(
            node_name="k3d-k3s-lab-agent-0",
            containers=[
                SimpleNamespace(
                    name="nginx",
                    image="nginx:1.27-alpine",
                    resources=SimpleNamespace(
                        requests={"memory": "32Mi"},
                        limits={"memory": "128Mi"},
                    ),
                )
            ],
        ),
    )
    node = SimpleNamespace(
        metadata=SimpleNamespace(name="k3d-k3s-lab-server-0"),
        status=SimpleNamespace(
            conditions=[condition],
            node_info=SimpleNamespace(
                kubelet_version="v1.30.0",
                os_image="Linux",
                architecture="arm64",
            ),
            capacity={"cpu": "2"},
            allocatable={"cpu": "1800m"},
        ),
    )
    service = SimpleNamespace(
        metadata=SimpleNamespace(name="web"),
        spec=SimpleNamespace(
            type="ClusterIP",
            cluster_ip="10.43.0.10",
            selector={"app": "web"},
            ports=[
                SimpleNamespace(
                    name="http",
                    port=80,
                    target_port=80,
                    protocol="TCP",
                )
            ],
        ),
    )
    endpoint = SimpleNamespace(
        metadata=SimpleNamespace(name="web"),
        subsets=[
            SimpleNamespace(
                addresses=[SimpleNamespace(ip="10.42.0.5")],
                not_ready_addresses=[],
                ports=[SimpleNamespace(name="http", port=80, protocol="TCP")],
            )
        ],
    )
    core_api = SimpleNamespace(
        list_node=lambda **_kwargs: SimpleNamespace(items=[node]),
        list_namespaced_pod=lambda **_kwargs: SimpleNamespace(items=[pod]),
        list_namespaced_service=lambda **_kwargs: SimpleNamespace(items=[service]),
        list_namespaced_endpoints=lambda **_kwargs: SimpleNamespace(items=[endpoint]),
        list_namespaced_event=lambda **_kwargs: SimpleNamespace(items=[]),
        read_namespaced_pod_log=lambda **kwargs: (
            "previous error" if kwargs["previous"] else "current log"
        ),
    )
    apps_api = SimpleNamespace(
        list_namespaced_deployment=lambda **_kwargs: SimpleNamespace(
            items=[
                SimpleNamespace(
                    metadata=SimpleNamespace(name="web"),
                    spec=SimpleNamespace(replicas=1),
                    status=SimpleNamespace(
                        updated_replicas=1,
                        ready_replicas=1,
                        available_replicas=1,
                        unavailable_replicas=0,
                        conditions=[],
                    ),
                )
            ]
        ),
        list_namespaced_replica_set=lambda **_kwargs: SimpleNamespace(items=[]),
    )
    diagnostics = KubernetesDiagnostics(
        kubeconfig="unused-in-test",
        logs_tail_lines=2,
        max_pods_with_logs=1,
    )
    monkeypatch.setattr(
        diagnostics,
        "_apis",
        lambda: (core_api, apps_api),
    )

    snapshot = diagnostics.collect()
    assert snapshot["status"] == "ok"
    assert snapshot["cluster"]["nodes"][0]["ready"]["ready"] is True
    assert snapshot["deployments"][0]["available_replicas"] == 1
    assert snapshot["services"][0]["endpoints"][0]["addresses"] == ["10.42.0.5"]
    assert [item["content"] for item in snapshot["pods"][0]["logs"]] == [
        "current log",
        "previous error",
    ]
    assert snapshot["limits"]["logs_tail_lines_per_container"] == 2


def test_pod_log_request_validates_resource_names_before_connecting():
    diagnostics = KubernetesDiagnostics(kubeconfig=None)
    with pytest.raises(ValueError, match="valid Kubernetes pod name"):
        diagnostics.get_pod_logs("web;id", 20)


def test_each_agent_receives_the_same_cluster_snapshot(monkeypatch):
    cluster_snapshot = {"status": "ok", "pods": [{"name": "api-123"}]}
    calls = []

    def fake_complete(system_prompt, user_prompt):
        calls.append((system_prompt, user_prompt))
        return "analysis"

    monkeypatch.setattr(agents, "complete", fake_complete)
    reports, final_report = agents.diagnose(
        "API unavailable",
        "Errors observed",
        "devops-lab",
        [],
        cluster_snapshot,
    )

    assert set(reports) == {"triage", "observability", "security"}
    assert final_report == "analysis"
    assert len(calls) == 4
    assert all('"status": "ok"' in user_prompt for _, user_prompt in calls)
    assert all(
        "niezaufanymi danymi" in system_prompt.lower()
        for system_prompt, _ in calls
    )


def test_agent_prompts_prioritize_failed_workload_and_its_events(monkeypatch):
    snapshot = {
        "status": "ok",
        "namespace": "devops-lab",
        "limits": {"events_truncated": False},
        "cluster": {
            "status": "healthy",
            "ready_nodes": 2,
            "total_nodes": 2,
            "nodes": [{"name": "node-1", "ready": {"ready": True}}],
        },
        "deployments": [
            {
                "name": "api",
                "desired_replicas": 1,
                "ready_replicas": 1,
                "unavailable_replicas": 1,
            }
        ],
        "replicasets": [
            {"name": "api-new", "owner": "api"},
            {"name": "api-old", "owner": "api"},
        ],
        "pods": [
            {
                "name": "api-new-pod",
                "namespace": "devops-lab",
                "phase": "Pending",
                "ready": {"ready": False},
                "containers": [
                    {
                        "name": "http-echo",
                        "image": "hashicorp/http-echo:does-not-exist",
                        "ready": False,
                        "restart_count": 0,
                        "state": {"state": "waiting", "reason": "ImagePullBackOff"},
                    }
                ],
                "logs": [{"status": "unavailable", "error": "Bad Request"}],
            },
            {
                "name": "api-old-pod",
                "namespace": "devops-lab",
                "phase": "Running",
                "ready": {"ready": True},
                "containers": [
                    {
                        "name": "http-echo",
                        "image": "hashicorp/http-echo:1.0.0",
                        "ready": True,
                        "restart_count": 0,
                        "state": {"state": "running"},
                    }
                ],
                "logs": [{"status": "ok", "content": "very long healthy log"}],
            },
        ],
        "services": [],
        "events": [
            {
                "type": "Warning",
                "reason": "Failed",
                "message": "Image hashicorp/http-echo:does-not-exist not found",
                "object": {"name": "api-new-pod"},
            }
        ],
    }
    calls = []

    def fake_complete(system_prompt, user_prompt):
        calls.append((system_prompt, user_prompt))
        return "analysis"

    monkeypatch.setattr(agents, "complete", fake_complete)
    agents.diagnose("API unavailable", "Timeouts", "devops-lab", [], snapshot)

    for _, user_prompt in calls:
        assert "ImagePullBackOff" in user_prompt
        assert "does-not-exist not found" in user_prompt
        assert "Bad Request" in user_prompt
        assert "very long healthy log" not in user_prompt
    assert len(calls) == 4
