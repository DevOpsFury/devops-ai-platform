import re
from datetime import datetime, timezone
from threading import Lock
from typing import Any, cast

from kubernetes import client, config
from kubernetes.client.exceptions import ApiException
from kubernetes.config.config_exception import ConfigException
from urllib3.exceptions import HTTPError

from app.config import settings

POD_NAME_PATTERN = re.compile(
    r"^[a-z0-9](?:[-a-z0-9]*[a-z0-9])?(?:\.[a-z0-9](?:[-a-z0-9]*[a-z0-9])?)*$"
)
CONTAINER_NAME_PATTERN = re.compile(r"^[a-z0-9](?:[-a-z0-9]*[a-z0-9])?$")


class KubernetesDiagnosticsUnavailable(RuntimeError):
    pass


class KubernetesResourceNotFound(LookupError):
    pass


class KubernetesDiagnostics:
    def __init__(
        self,
        namespace: str = settings.kubernetes_namespace,
        kubeconfig: str | None = settings.kubernetes_kubeconfig,
        logs_tail_lines: int = settings.kubernetes_logs_tail_lines,
        max_pods_with_logs: int = settings.kubernetes_max_pods_with_logs,
    ) -> None:
        self.namespace = namespace
        self.kubeconfig = kubeconfig
        self.logs_tail_lines = logs_tail_lines
        self.max_pods_with_logs = max_pods_with_logs
        self._api_client: client.ApiClient | None = None
        self._core_api: client.CoreV1Api | None = None
        self._apps_api: client.AppsV1Api | None = None
        self._client_lock = Lock()

    def _apis(self) -> tuple[client.CoreV1Api, client.AppsV1Api]:
        if self._core_api is not None and self._apps_api is not None:
            return self._core_api, self._apps_api

        with self._client_lock:
            if self._core_api is None or self._apps_api is None:
                if not self.kubeconfig:
                    raise KubernetesDiagnosticsUnavailable(
                        "KUBECONFIG is not configured; Kubernetes diagnostics are unavailable."
                    )
                configuration = client.Configuration()
                try:
                    config.load_kube_config(
                        config_file=self.kubeconfig,
                        client_configuration=configuration,
                    )
                except (ConfigException, OSError) as exc:
                    raise KubernetesDiagnosticsUnavailable(
                        f"Could not load Kubernetes configuration: {exc}"
                    ) from exc

                self._api_client = client.ApiClient(configuration)
                self._core_api = client.CoreV1Api(self._api_client)
                self._apps_api = client.AppsV1Api(self._api_client)

        return self._core_api, self._apps_api

    @staticmethod
    def _timestamp(value: datetime | None) -> str | None:
        return value.isoformat() if value else None

    @staticmethod
    def _ready(conditions: list[Any] | None) -> dict[str, Any]:
        condition = next(
            (item for item in conditions or [] if item.type == "Ready"),
            None,
        )
        if condition is None:
            return {"ready": False, "reason": "Ready condition unavailable"}
        return {
            "ready": condition.status == "True",
            "reason": condition.reason,
            "message": condition.message,
            "last_transition_time": KubernetesDiagnostics._timestamp(
                condition.last_transition_time
            ),
        }

    def _pod_logs(
        self,
        core_api: client.CoreV1Api,
        pod_name: str,
        containers: list[Any],
        statuses: list[Any],
        tail_lines: int,
    ) -> list[dict[str, Any]]:
        status_by_name = {item.name: item for item in statuses or []}
        results = []
        for container in containers:
            container_status = status_by_name.get(container.name)
            restart_count = container_status.restart_count if container_status else 0
            for previous in ([False, True] if restart_count else [False]):
                try:
                    content = core_api.read_namespaced_pod_log(
                        name=pod_name,
                        namespace=self.namespace,
                        container=container.name,
                        tail_lines=tail_lines,
                        previous=previous,
                        timestamps=True,
                        _request_timeout=10,
                    )
                except ApiException as exc:
                    if exc.status == 404:
                        results.append(
                            {
                                "container": container.name,
                                "previous": previous,
                                "status": "unavailable",
                                "error": "Pod or container logs were not found.",
                            }
                        )
                        continue
                    results.append(
                        {
                            "container": container.name,
                            "previous": previous,
                            "status": "unavailable",
                            "error": exc.reason or "Kubernetes API request failed",
                        }
                    )
                    continue
                except HTTPError:
                    results.append(
                        {
                            "container": container.name,
                            "previous": previous,
                            "status": "unavailable",
                            "error": "Could not connect to the Kubernetes API.",
                        }
                    )
                    continue
                results.append(
                    {
                        "container": container.name,
                        "previous": previous,
                        "status": "ok",
                        "content": content,
                    }
                )
        return results

    def collect(self) -> dict[str, Any]:
        core_api, apps_api = self._apis()
        try:
            node_page = core_api.list_node(limit=101, _request_timeout=10)
            nodes_truncated = len(node_page.items) > 100
            nodes = node_page.items[:100]
            pod_page = core_api.list_namespaced_pod(
                namespace=self.namespace,
                limit=1001,
                _request_timeout=10,
            )
            pods_truncated = len(pod_page.items) > 1000
            pods = pod_page.items[:1000]
            service_page = core_api.list_namespaced_service(
                namespace=self.namespace, limit=101, _request_timeout=10
            )
            services_truncated = len(service_page.items) > 100
            services = service_page.items[:100]
            endpoint_page = core_api.list_namespaced_endpoints(
                namespace=self.namespace, limit=101, _request_timeout=10
            )
            endpoints_truncated = len(endpoint_page.items) > 100
            endpoints = endpoint_page.items[:100]
            event_page = core_api.list_namespaced_event(
                namespace=self.namespace, limit=501, _request_timeout=10
            )
            events_truncated = len(event_page.items) > 500
            events = event_page.items[:500]
            deployment_page = apps_api.list_namespaced_deployment(
                namespace=self.namespace, limit=101, _request_timeout=10
            )
            deployments_truncated = len(deployment_page.items) > 100
            deployments = deployment_page.items[:100]
            replicaset_page = apps_api.list_namespaced_replica_set(
                namespace=self.namespace, limit=101, _request_timeout=10
            )
            replicasets_truncated = len(replicaset_page.items) > 100
            replicasets = replicaset_page.items[:100]
        except (ApiException, HTTPError) as exc:
            detail = exc.reason if isinstance(exc, ApiException) else str(exc)
            raise KubernetesDiagnosticsUnavailable(
                f"Could not collect Kubernetes diagnostics: {detail}"
            ) from exc

        endpoint_by_name: dict[str, list[dict[str, Any]]] = {}
        for endpoint in endpoints:
            endpoint_by_name[endpoint.metadata.name] = [
                {
                    "addresses": [
                        address.ip for address in subset.addresses or []
                    ],
                    "not_ready_addresses": [
                        address.ip for address in subset.not_ready_addresses or []
                    ],
                    "ports": [
                        {
                            "name": port.name,
                            "port": port.port,
                            "protocol": port.protocol,
                        }
                        for port in subset.ports or []
                    ],
                }
                for subset in endpoint.subsets or []
            ]

        ordered_pods = sorted(
            pods,
            key=lambda pod: (
                self._ready(pod.status.conditions)["ready"],
                -sum(
                    item.restart_count
                    for item in pod.status.container_statuses or []
                ),
                pod.metadata.name,
            ),
        )
        pod_results = []
        for pod_index, pod in enumerate(ordered_pods):
            status = pod.status
            container_statuses = status.container_statuses or []
            container_status_by_name = {
                item.name: item for item in container_statuses
            }
            logs_included = pod_index < self.max_pods_with_logs
            pod_results.append(
                {
                    "name": pod.metadata.name,
                    "namespace": pod.metadata.namespace,
                    "phase": status.phase,
                    "ready": self._ready(status.conditions),
                    "node": pod.spec.node_name,
                    "ip": status.pod_ip,
                    "started_at": self._timestamp(status.start_time),
                    "containers": [
                        self._pod_container_status(item, container_status_by_name)
                        for item in pod.spec.containers or []
                    ],
                    "logs_status": "included" if logs_included else "skipped_limit",
                    "logs": (
                        self._pod_logs(
                            core_api,
                            pod.metadata.name,
                            pod.spec.containers or [],
                            container_statuses,
                            self.logs_tail_lines,
                        )
                        if logs_included
                        else []
                    ),
                }
            )

        node_results = [
            {
                "name": node.metadata.name,
                "ready": self._ready(node.status.conditions),
                "kubelet_version": node.status.node_info.kubelet_version,
                "os_image": node.status.node_info.os_image,
                "architecture": node.status.node_info.architecture,
                "capacity": node.status.capacity,
                "allocatable": node.status.allocatable,
            }
            for node in nodes
        ]
        ready_node_count = sum(item["ready"]["ready"] for item in node_results)
        deployment_results = [
            {
                "name": item.metadata.name,
                "desired_replicas": item.spec.replicas,
                "updated_replicas": item.status.updated_replicas or 0,
                "ready_replicas": item.status.ready_replicas or 0,
                "available_replicas": item.status.available_replicas or 0,
                "unavailable_replicas": item.status.unavailable_replicas or 0,
                "conditions": [
                    {
                        "type": condition.type,
                        "status": condition.status,
                        "reason": condition.reason,
                        "message": condition.message,
                        "last_update_time": self._timestamp(
                            condition.last_update_time
                        ),
                    }
                    for condition in item.status.conditions or []
                ],
            }
            for item in deployments
        ]
        service_results = [
            {
                "name": item.metadata.name,
                "type": item.spec.type,
                "cluster_ip": item.spec.cluster_ip,
                "selector": item.spec.selector or {},
                "ports": [
                    {
                        "name": port.name,
                        "port": port.port,
                        "target_port": str(port.target_port),
                        "protocol": port.protocol,
                    }
                    for port in item.spec.ports or []
                ],
                "endpoints": endpoint_by_name.get(item.metadata.name, []),
            }
            for item in services
        ]
        event_results = [
            {
                "type": item.type,
                "reason": item.reason,
                "message": item.message,
                "count": item.count,
                "object": {
                    "kind": item.involved_object.kind,
                    "name": item.involved_object.name,
                    "namespace": item.involved_object.namespace,
                },
                "first_timestamp": self._timestamp(item.first_timestamp),
                "last_timestamp": self._timestamp(
                    item.last_timestamp or item.event_time or item.first_timestamp
                ),
            }
            for item in sorted(
                events,
                key=lambda event: (
                    event.last_timestamp or event.event_time or event.first_timestamp
                    or datetime.min.replace(tzinfo=timezone.utc)
                ),
                reverse=True,
            )[:100]
        ]
        replica_set_results = [
            {
                "name": item.metadata.name,
                "owner": next(
                    (
                        owner.name
                        for owner in item.metadata.owner_references or []
                        if owner.kind == "Deployment"
                    ),
                    None,
                ),
                "desired_replicas": item.spec.replicas,
                "ready_replicas": item.status.ready_replicas or 0,
            }
            for item in replicasets
        ]
        return {
            "status": "ok",
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "namespace": self.namespace,
            "limits": {
                "max_pods_with_logs": self.max_pods_with_logs,
                "logs_tail_lines_per_container": self.logs_tail_lines,
                "nodes_truncated": nodes_truncated,
                "pods_truncated": pods_truncated,
                "services_truncated": services_truncated,
                "endpoints_truncated": endpoints_truncated,
                "deployments_truncated": deployments_truncated,
                "replicasets_truncated": replicasets_truncated,
                "events_truncated": events_truncated,
                "pods_without_logs_due_to_limit": max(
                    0, len(pods) - self.max_pods_with_logs
                ),
            },
            "cluster": {
                "status": (
                    "unknown"
                    if not node_results
                    else "healthy"
                    if ready_node_count == len(node_results)
                    else "degraded"
                ),
                "ready_nodes": ready_node_count,
                "total_nodes": len(node_results),
                "nodes": node_results,
            },
            "deployments": deployment_results,
            "replicasets": replica_set_results,
            "pods": pod_results,
            "services": service_results,
            "events": event_results,
        }

    @staticmethod
    def _container_state(state: Any) -> dict[str, Any] | None:
        if state is None:
            return None
        for name in ("running", "waiting", "terminated"):
            value = getattr(state, name, None)
            if value is not None:
                return {
                    "state": name,
                    "reason": getattr(value, "reason", None),
                    "message": getattr(value, "message", None),
                    "exit_code": getattr(value, "exit_code", None),
                    "started_at": KubernetesDiagnostics._timestamp(
                        getattr(value, "started_at", None)
                    ),
                    "finished_at": KubernetesDiagnostics._timestamp(
                        getattr(value, "finished_at", None)
                    ),
                }
        return None

    @staticmethod
    def _pod_container_status(
        container: Any,
        statuses: dict[str, Any],
    ) -> dict[str, Any]:
        container_status = statuses.get(container.name)
        resources = container.resources
        return {
            "name": container.name,
            "image": container.image,
            "ready": container_status.ready if container_status else False,
            "restart_count": container_status.restart_count if container_status else 0,
            "state": KubernetesDiagnostics._container_state(
                container_status.state if container_status else None
            ),
            "last_state": KubernetesDiagnostics._container_state(
                container_status.last_state if container_status else None
            ),
            "resources": {
                "requests": resources.requests or {} if resources else {},
                "limits": resources.limits or {} if resources else {},
            },
        }

    def get_pod_logs(
        self, pod_name: str, tail_lines: int, container: str | None = None
    ) -> dict[str, Any]:
        if not POD_NAME_PATTERN.fullmatch(pod_name):
            raise ValueError("pod_name must be a valid Kubernetes pod name.")
        if container is not None and not CONTAINER_NAME_PATTERN.fullmatch(container):
            raise ValueError("container must be a valid Kubernetes container name.")
        core_api, _ = self._apis()
        try:
            pod = cast(
                client.V1Pod,
                core_api.read_namespaced_pod(
                    name=pod_name,
                    namespace=self.namespace,
                    _request_timeout=10,
                ),
            )
            if pod.spec is None or pod.status is None:
                raise KubernetesDiagnosticsUnavailable(
                    f"Pod {pod_name!r} has incomplete Kubernetes status."
                )
            containers = pod.spec.containers or []
            if container is not None:
                containers = [item for item in containers if item.name == container]
                if not containers:
                    raise ValueError(
                        f"Container {container!r} is not part of pod {pod_name!r}."
                    )
            result = self._pod_logs(
                core_api,
                pod_name,
                containers,
                pod.status.container_statuses or [],
                tail_lines,
            )
        except KubernetesResourceNotFound:
            raise
        except ValueError:
            raise
        except (ApiException, HTTPError) as exc:
            if isinstance(exc, ApiException) and exc.status == 404:
                raise KubernetesResourceNotFound(
                    f"Pod {pod_name!r} was not found in namespace {self.namespace!r}."
                ) from exc
            detail = exc.reason if isinstance(exc, ApiException) else str(exc)
            raise KubernetesDiagnosticsUnavailable(
                f"Could not read pod logs: {detail}"
            ) from exc
        return {
            "namespace": self.namespace,
            "pod_name": pod_name,
            "tail_lines": tail_lines,
            "logs": result,
        }


kubernetes_diagnostics = KubernetesDiagnostics()
