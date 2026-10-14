import json
import logging
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock
from urllib.parse import urlsplit

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("orders-api")


class ScenarioState:
    def __init__(self) -> None:
        self._lock = Lock()
        self._problem: str | None = None

    @property
    def problem(self) -> str | None:
        with self._lock:
            return self._problem

    def activate(self, problem: str) -> bool:
        with self._lock:
            already_active = self._problem == problem
            self._problem = problem
            return not already_active

    def reset(self) -> str | None:
        with self._lock:
            previous_problem = self._problem
            self._problem = None
            return previous_problem


def create_handler(state: ScenarioState) -> type[BaseHTTPRequestHandler]:
    class OrdersApiHandler(BaseHTTPRequestHandler):
        def _respond(self, status: int, payload: dict) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            path = urlsplit(self.path).path
            if path == "/health/live":
                self._respond(200, {"status": "alive"})
            elif path == "/health/ready":
                problem = state.problem
                if problem:
                    self._respond(503, {"status": "not_ready", "problem": problem})
                else:
                    self._respond(200, {"status": "ready"})
            elif path == "/":
                self._respond(
                    200,
                    {"service": "orders-api", "problem": state.problem},
                )
            else:
                self._respond(404, {"error": "not_found"})

        def do_POST(self) -> None:
            path = urlsplit(self.path).path
            if path.startswith("/break/"):
                problem = path.removeprefix("/break/")
                if problem != "db-auth":
                    self._respond(
                        404,
                        {
                            "error": "unknown_problem",
                            "supported_problems": ["db-auth"],
                        },
                    )
                    return

                activated = state.activate(problem)
                if activated:
                    logger.error(
                        "Database connection failed at "
                        "postgres.devops-lab.svc:5432"
                    )
                    logger.critical(
                        'FATAL: password authentication failed for user "orders_user"'
                    )
                    logger.critical(
                        "EMERG: Application would shut down after failed "
                        "authentication; simulation control remains active for /fixme."
                    )
                self._respond(
                    200,
                    {
                        "status": "problem_active",
                        "problem": problem,
                        "already_active": not activated,
                    },
                )
            elif path == "/fixme":
                problem = state.reset()
                if problem:
                    logger.info("Problem %s cleared by /fixme.", problem)
                self._respond(
                    200,
                    {"status": "healthy", "cleared_problem": problem},
                )
            else:
                self._respond(404, {"error": "not_found"})

        def log_message(self, format: str, *args: object) -> None:
            logger.info("%s - %s", self.address_string(), format % args)

    return OrdersApiHandler


def main() -> None:
    state = ScenarioState()
    server = ThreadingHTTPServer(("0.0.0.0", 8080), create_handler(state))
    logger.info("orders-api listening on port 8080")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
