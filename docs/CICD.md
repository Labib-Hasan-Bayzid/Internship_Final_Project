# CI/CD — DCV 15.0

## Pull-request/main CI

`.github/workflows/ci.yml` runs on pull requests and `main`: backend compile/tests against PostgreSQL, frontend production build, local/production Kustomize rendering, and four container-build validations.

## Container release gate

`.github/workflows/container.yml` has a mandatory release quality gate before any image is published. It runs backend tests, frontend build and Kubernetes rendering, then builds four GHCR images with Buildx cache plus SBOM/provenance metadata.

Production image references are pinned by commit SHA in Git, avoiding a mutable release reference after the workflow finishes.

## GitOps

The production Argo CD Application watches `infra/k8s/production`, with automated sync, self-healing, pruning, bounded retries, and foreground prune propagation. The local Argo Application is available for cluster-based development.

## External credential boundary

Cloud/GitHub/registry credentials are intentionally owned by the deploying organization. The later security phase should use workload identity/OIDC and a dedicated secret manager instead of long-lived secrets wherever the target platform supports it.
