# Local rollout fix — 2026-10-12

Windows PowerShell native-command JSON patching now uses UTF-8 `--patch-file` inputs for backend/frontend image-content annotations, avoiding `invalid JSON patch` argument-quoting failures.


## Failure analyzed

The supplied log shows the Docker builds, Kind image loads, Kustomize server-side validation, and Kubernetes applies succeeding. The failure happens later, when Kubernetes waits for the backend Deployment to finish replacing an old Pod. The exact line `1 old replicas are pending termination` means the remaining blocker is an old Pod that Kubernetes has not finished removing; the supplied log does not include the Pod events or node/container state needed to identify why that particular Pod became stuck.

A bootstrap defect made this easier to trigger: after `kubectl apply -k`, the script unconditionally restarted both Deployments. Applying a changed image tag can itself start a rollout, so issuing another restart immediately can supersede that in-flight rollout. Static image tags also meant that rebuilding the same tag did not, by itself, notify Kubernetes that image contents changed.

## Changes

- Removed unconditional backend/frontend `kubectl rollout restart` calls.
- Recorded the actual Docker image IDs and use Pod-template annotations to trigger a single rollout only when an image's content changed while its tag stayed the same.
- Avoided the content-annotation rollout when `kubectl apply` already changed the Pod template.
- Replaced opaque rollout timeout errors with polling and diagnostics for Deployment status, Pods, events, `describe`, and current/previous container logs.
- Added a narrowly scoped local-Kind recovery: only when updated replicas are healthy, an old Pod has been terminating for over 60 seconds, and its node is Ready does the script force-remove that stale Pod API object. PostgreSQL StatefulSet/PVC resources are not deleted.
- Added regression coverage and the `docs/LOCAL-ROLLOUT-TROUBLESHOOTING.md` runbook.

## Validation performed in this workspace

- Python compilation: passed.
- Focused parser/comparator/release/infrastructure tests: 16 passed.
- YAML parsing: 17 Kubernetes YAML files parsed successfully.
- Release version consistency and static rollout-script assertions: passed.

## Validation still required

This workspace has no Windows PowerShell runtime, Docker daemon, or Kind cluster, so the edited PowerShell script and the live Windows rollout could not be executed end-to-end here. The full Python test suite also could not be collected in this workspace because the environment does not have the `psycopg` package installed. Run the supplied PowerShell bootstrap on Windows to validate the actual cluster state. These changes target the reported local rollout failure; they do not independently certify every listed integration or make the product production-ready. Review `docs/PRODUCTION-CHECKLIST.md` and the production-boundary notes before selling a hosted service.

# Local admin-route smoke-test fix — 2026-10-12

## Failure analyzed

The new supplied log confirms that the backend rollout is now healthy (`updated 1/1`, `available 1/1`, no terminating Pods) and that the deployed release identity checks pass. The failure occurs only at the bootstrap's admin-route check. The source does define `/api/admin/context` by including `admin_router` with the `/api/admin` prefix, so inspecting only `app.routes` and checking for a top-level object whose `.path` equals that full route can produce a false negative when a FastAPI version represents included routers lazily. The log alone cannot prove the live endpoint's status; the corrected check tests the endpoint directly.

## Changes

- Replaced `app.routes` introspection with an HTTP request to `/api/admin/context` from inside the backend container and require HTTP 200.
- Captured exit codes immediately after each `kubectl exec` verification command so later commands cannot mask earlier failures.
- Improved the failure message to include exit status and command output, and added regression coverage plus troubleshooting documentation.

## Validation boundary

Static and automated checks are run in this workspace. A live PowerShell/Kind run remains necessary to establish that the endpoint returns HTTP 200 in the user's cluster; that cluster is not available from this environment. The project should not be described as fully production-certified solely because this local bootstrap smoke test passes.


# PowerShell parser-error fix — 2026-10-12

## Failure analyzed

The next local run failed before executing any commands because PowerShell parses `$BaseVersion:` inside a double-quoted string as a scoped/drive-qualified variable reference. The parser requires a delimiter around the variable name when literal punctuation immediately follows it.

## Changes

- Changed the interpolation to `${BaseVersion}:` so the colon is unambiguously literal text.
- Escaped the release version with `[regex]::Escape($BaseVersion)` before using it in `-match`, avoiding accidental regular-expression interpretation of version punctuation.
- Added a regression test for the PowerShell interpolation pattern.

## Validation boundary

Focused automated tests passed in the build workspace. No PowerShell runtime is available in this workspace, so a native PowerShell parser run and live Windows/Kind deployment remain to be confirmed on the target machine.
