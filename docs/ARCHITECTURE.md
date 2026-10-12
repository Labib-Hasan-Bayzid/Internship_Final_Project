# DCV 15.0 architecture

## Runtime

```text
                        GitHub PR
                           |
                    signed webhook
                           v
                 PostgreSQL webhook queue
                           |
                           v
                     FastAPI worker
                           |
             dependency manifest discovery
                           |
                           v
                 verification records
                           |
                           v
                   Kubernetes Jobs
                  /              \
          Python runner        Node runner
                  \              /
                   \--- evidence ---/
                           |
                           v
                 deterministic comparator
                           |
                   PASS/REVIEW/BLOCK
                    /            \
                   v              v
             GitHub Check      PostgreSQL
                   |              |
                   +-------> Dashboard
                           |
                           v
                 optional AI explanation
```

## GitHub integration

The GitHub App is the external event source. The webhook endpoint validates the signature and persists the GitHub delivery ID before doing any expensive work. A database-backed worker processes the queue, which means a process restart does not lose an accepted delivery.

The GitHub API client uses installation access tokens, pagination for changed PR files, transient-error retries and the GitHub API version header. Each dependency change receives a Check Run; the completed deterministic result is mapped to GitHub's Check conclusions.

## CI/CD

```text
Pull Request
     |
     v
GitHub Actions CI
  |   |   |   |
  |   |   |   +-- Kustomize render
  |   |   +------ container build validation
  |   +---------- frontend build
  +-------------- backend tests

main
 |
 v
Container Release workflow
 |
 +--> GHCR immutable image tags
 |
 +--> production Kustomize image SHA update
             |
             v
           Git
             |
             v
          Argo CD
             |
             v
       Production Kubernetes
```

## Production deployment boundary

The production overlay does not deploy the local PostgreSQL StatefulSet. It expects an external PostgreSQL service and reads `DATABASE_URL` from the `dcv-integrations` Secret.

The public ingress routes `/api` and `/webhooks` to FastAPI and `/` to Next.js.

## AI boundary

```text
evidence -> deterministic comparator -> gate decision -> AI explanation
```

The AI client is never in the critical decision path. Provider failures are persisted as AI failures/retryable work and do not alter PASS/REVIEW/BLOCK.

## Deliberately deferred security phase

Authentication, tenant isolation, stronger workload isolation, network policy, secret-management hardening, abuse prevention and enterprise security controls remain outside this release.
