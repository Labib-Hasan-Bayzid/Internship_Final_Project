# Beginner setup — Windows 11

The intended control terminal is **Windows PowerShell**. Docker Desktop supplies the container runtime and kind supplies the local Kubernetes cluster.

## First local run

From the repository root:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\scripts\start-local.ps1
```

The script:

1. checks Docker
2. starts or creates the `dcv` kind cluster
3. builds the backend, frontend and two runner images
4. preserves an existing PostgreSQL StatefulSet/PVC
5. applies the application manifests
6. waits for backend/frontend rollouts

Then run the frontend port-forward in its own PowerShell:

```powershell
kubectl port-forward svc/frontend 3000:3000 -n dcv
```

Open `http://localhost:3000`.

For direct API work:

```powershell
kubectl port-forward svc/backend 8000:8000 -n dcv
```

## GitHub integration

Configure the GitHub App using `docs/GITHUB-APP.md`. A public deployment must expose:

```text
https://YOUR-DOMAIN/webhooks/github
```

The App private key and webhook secret are runtime configuration; do not commit them.

## AI

Set `AI_ENABLED=true`, `AI_AUTO_EXPLAIN=true`, `AI_MODEL=gpt-5`, and `OPENAI_API_KEY` in the deployment environment/Secret.

The dashboard exposes an AI explanation action for completed verification runs.

## Argo CD locally

```powershell
.\scripts\install-argocd.ps1
.\scripts\enable-argocd-local.ps1
```

Then:

```powershell
kubectl port-forward svc/argocd-server -n argocd 8080:443
```

Browse to `https://localhost:8080`.
