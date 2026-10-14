import json
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import yaml

from k3s_lab.orders_api.server import ScenarioState, create_handler


def request_json(url: str, method: str = "GET") -> tuple[int, Any]:
    request = Request(url, method=method)
    try:
        response = urlopen(request, timeout=2)
    except HTTPError as exc:
        response = exc
    with response:
        status = response.status
        if status is None:
            raise RuntimeError("HTTP response did not include a status code.")
        return status, json.loads(response.read())


def test_break_db_auth_and_fixme_toggle_readiness_and_emit_logs(caplog):
    state = ScenarioState()
    server = ThreadingHTTPServer(("127.0.0.1", 0), create_handler(state))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    try:
        status, body = request_json(f"{base_url}/health/ready")
        assert status == 200
        assert body == {"status": "ready"}

        status, body = request_json(
            f"{base_url}/break/db-auth",
            method="POST",
        )
        assert status == 200
        assert body == {
            "status": "problem_active",
            "problem": "db-auth",
            "already_active": False,
        }
        assert "password authentication failed for user" in caplog.text

        status, body = request_json(f"{base_url}/health/ready")
        assert status == 503
        assert body == {"status": "not_ready", "problem": "db-auth"}

        status, body = request_json(f"{base_url}/health/live")
        assert status == 200
        assert body == {"status": "alive"}

        status, body = request_json(f"{base_url}/fixme", method="POST")
        assert status == 200
        assert body == {"status": "healthy", "cleared_problem": "db-auth"}

        status, body = request_json(f"{base_url}/health/ready")
        assert status == 200
        assert body == {"status": "ready"}
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_unknown_problem_is_rejected():
    state = ScenarioState()
    server = ThreadingHTTPServer(("127.0.0.1", 0), create_handler(state))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, body = request_json(
            f"http://127.0.0.1:{server.server_port}/break/unknown",
            method="POST",
        )
        assert status == 404
        assert body == {
            "error": "unknown_problem",
            "supported_problems": ["db-auth"],
        }
        assert state.problem is None
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_orders_api_deployment_has_health_probes_and_service():
    manifest_path = Path(__file__).parents[1] / "k3s_lab/manifests/lab.yaml"
    documents = list(yaml.safe_load_all(manifest_path.read_text(encoding="utf-8")))
    deployment = next(
        document
        for document in documents
        if document.get("kind") == "Deployment"
        and document["metadata"]["name"] == "orders-api"
    )
    service = next(
        document
        for document in documents
        if document.get("kind") == "Service"
        and document["metadata"]["name"] == "orders-api"
    )

    container = deployment["spec"]["template"]["spec"]["containers"][0]
    assert container["image"] == "devops-lab/orders-api:latest"
    assert container["readinessProbe"]["httpGet"]["path"] == "/health/ready"
    assert container["livenessProbe"]["httpGet"]["path"] == "/health/live"
    assert service["spec"]["selector"] == {"app": "orders-api"}
