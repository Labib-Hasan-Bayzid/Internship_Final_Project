# Argo CD

Argo CD is the deployment controller. GitHub Actions builds and publishes immutable images, then updates the GitOps desired state. Argo CD reconciles that desired state into Kubernetes.

The Applications use automated sync, self-healing, bounded retry/backoff and safe pruning behavior. Argo CD documents these options in the Application specification. https://argo-cd.readthedocs.io/en/latest/user-guide/application-specification/

Production should use a dedicated GitOps repository or protected path, a managed Kubernetes cluster, external PostgreSQL and a real secret-management solution. The repository contains a production Application manifest but cannot create or configure the customer's external cluster automatically.
