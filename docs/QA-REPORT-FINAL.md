# DCV 15.0.0 — Final QA Record

This record covers the final consolidated functional release and the recurring local deployment failures reported during the prior release iterations.

## Source and release consistency

- `VERSION` = `15.0.0`
- `RELEASE_VERSION` = `15.0.0`
- Backend application version = `15.0.0`
- Frontend package version = `15.0.0`
- Local image family for the current release = `15.0.0-local`; Windows deployment scripts resolve local image tags and the expected-release marker from `VERSION` in a disposable copy while preserving a directly renderable checked-in overlay for Argo CD.

## Infrastructure checks

- All Kustomize resource paths resolve inside the repository.
- Local Kustomize root is `infra/k8s/local` and references `../base`.
- Production Kustomize root is `infra/k8s/production` and references `../base`.
- The legacy `infra/k8s/overlays` tree is removed.
- PostgreSQL StatefulSet is excluded from application Kustomizations.
- PostgreSQL local deployment is separated into a Service and a create-only-if-absent StatefulSet flow.
- No Deployment manifest combines `strategy.type: Recreate` with `rollingUpdate`.

## User-reported failures addressed

1. Clean build failure because a versioned Docker image did not exist before the build.
2. PowerShell parser failure caused by Bash-style `\"` escaping.
3. Frontend TypeScript failure from `Role | null | undefined` reaching role guards.
4. Kubernetes Deployment strategy patch conflict between `Recreate` and `rollingUpdate`.
5. PostgreSQL StatefulSet `volumeClaimTemplates` immutable-field failures.
6. Kustomize resource traversal that resolved outside the repository to `C:\\dev\\base`.

## Validation performed in the release workspace

- Python compilation: PASS.
- YAML parsing: PASS.
- Release/version consistency tests: PASS.
- Patch verification in the current offline workspace: 19 tests passed across dependency parser, comparator, release consistency, and infrastructure checks before the rollout-race follow-up; the current patch adds two rollout regression tests.
- Full backend test collection was not available in this workspace because the `psycopg` driver is absent and package registries are unreachable; the CI workflow installs the declared backend requirements and runs against PostgreSQL.
- Kustomize resource-containment checks: PASS.
- Deployment strategy invariant checks: PASS.
- Stale legacy Kustomize path scan: PASS.
- PowerShell invalid-escape scan: PASS.

The audit environment cannot execute the user's Windows PowerShell, Docker Desktop, kind cluster, or external GitHub/Stripe/OpenAI services. The supplied follow-up diagnostics show two backend ReplicaSets created about one second apart with the same image tag, consistent with an apply followed immediately by a second explicit rollout restart. The local scripts now stamp the pod template before apply and do not issue the redundant restart. The backend termination grace period is 60 seconds. Node sandbox recreation is a separate kind/Docker/WSL2 signal and should be investigated if it recurs. End-to-end rollout status still needs verification on the user's Windows kind cluster.
