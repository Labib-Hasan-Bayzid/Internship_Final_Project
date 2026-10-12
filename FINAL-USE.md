# DCV Final Use Guide

## Windows local deployment

Use a fresh extraction directory. Do not merge the archive into a previous DCV release directory.

```powershell
cd C:\dev\dependency-change-verification-final
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\scripts\start-local.ps1
```

The bootstrap is designed for an existing `kind-dcv` cluster and an existing DCV PostgreSQL StatefulSet/PVC. It builds four versioned images, loads them into every kind node, validates the local Kustomize tree before application deployment, deploys application resources, preserves the existing PostgreSQL StatefulSet, and verifies backend release identity.

Open the dashboard with:

```powershell
kubectl port-forward svc/frontend 3000:3000 -n dcv
```

Then browse to `http://localhost:3000`.

The API is available with:

```powershell
kubectl port-forward svc/backend 8000:8000 -n dcv
```

and then `http://localhost:8000/docs`.

## What is intentionally required for production

Production requires customer-owned PostgreSQL, Kubernetes/Argo CD, DNS/Ingress, GitHub App credentials, Stripe credentials, and OpenAI credentials. Populate the production integration Secret from the customer's secret-management system. Full production security hardening remains outside the requested scope.
