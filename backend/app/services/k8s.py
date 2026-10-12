from __future__ import annotations
import json
from kubernetes import client, config
from kubernetes.client.rest import ApiException
from app.config import get_settings


class KubernetesRunner:
    def __init__(self):
        self.settings = get_settings()
        try:
            config.load_incluster_config()
        except config.ConfigException:
            config.load_kube_config()
        self.batch = client.BatchV1Api()
        self.core = client.CoreV1Api()

    def create_job(self, run_id: str, ecosystem: str, package_name: str, old_version: str, new_version: str, smoke_import: str | None) -> str:
        job_name = f"verify-{run_id}"
        image = self.settings.runner_image_python if ecosystem == "python" else self.settings.runner_image_node
        env = [
            client.V1EnvVar(name="PACKAGE_NAME", value=package_name),
            client.V1EnvVar(name="OLD_VERSION", value=old_version),
            client.V1EnvVar(name="NEW_VERSION", value=new_version),
        ]
        if smoke_import:
            env.append(client.V1EnvVar(name="SMOKE_IMPORT", value=smoke_import))
        container = client.V1Container(
            name="runner",
            image=image,
            image_pull_policy="IfNotPresent",
            env=env,
            resources=client.V1ResourceRequirements(
                requests={"cpu": "100m", "memory": "256Mi"},
                limits={"cpu": "500m", "memory": "768Mi"},
            ),
            security_context=client.V1SecurityContext(
                run_as_non_root=True,
                run_as_user=10001,
                allow_privilege_escalation=False,
                capabilities=client.V1Capabilities(drop=["ALL"]),
                seccomp_profile=client.V1SeccompProfile(type="RuntimeDefault"),
            ),
        )
        pod_spec = client.V1PodSpec(
            restart_policy="Never",
            automount_service_account_token=False,
            containers=[container],
            security_context=client.V1PodSecurityContext(run_as_non_root=True),
        )
        job = client.V1Job(
            metadata=client.V1ObjectMeta(name=job_name, labels={"app": "dcv-verification", "run-id": run_id}),
            spec=client.V1JobSpec(
                backoff_limit=0,
                active_deadline_seconds=self.settings.k8s_job_timeout_seconds,
                ttl_seconds_after_finished=900,
                template=client.V1PodTemplateSpec(metadata=client.V1ObjectMeta(labels={"run-id": run_id}), spec=pod_spec),
            ),
        )
        self.batch.create_namespaced_job(namespace=self.settings.k8s_namespace, body=job)
        return job_name

    def job_state(self, job_name: str) -> tuple[str, str | None]:
        try:
            job = self.batch.read_namespaced_job(job_name, self.settings.k8s_namespace)
        except ApiException as exc:
            if getattr(exc, "status", None) == 404:
                return "UNKNOWN", None
            return "ERROR", None
        if job.status and job.status.succeeded:
            return "SUCCEEDED", self._logs(job_name)
        if job.status and job.status.failed:
            return "FAILED", self._logs(job_name)
        return "RUNNING", None

    def _logs(self, job_name: str) -> str:
        try:
            pods = self.core.list_namespaced_pod(
                self.settings.k8s_namespace,
                label_selector=f"run-id={job_name.removeprefix('verify-')}",
            ).items
        except ApiException:
            return ""
        if not pods:
            return ""
        try:
            return self.core.read_namespaced_pod_log(pods[0].metadata.name, self.settings.k8s_namespace, tail_lines=1500)
        except ApiException:
            return ""


def parse_result_from_logs(logs: str) -> dict | None:
    for line in reversed(logs.splitlines()):
        if line.startswith("VERIFICATION_RESULT:"):
            try:
                return json.loads(line.split(":", 1)[1])
            except json.JSONDecodeError:
                return None
    return None
