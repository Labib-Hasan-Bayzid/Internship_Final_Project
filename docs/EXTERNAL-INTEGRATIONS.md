# External integrations checklist

## GitHub

1. Create the GitHub App using `docs/github-app-manifest.json` as the starting point.
2. Set the webhook to `https://YOUR-DCV-DOMAIN/webhooks/github`.
3. Configure `GITHUB_APP_ID`, `GITHUB_APP_SLUG`, `GITHUB_PRIVATE_KEY`, and `GITHUB_WEBHOOK_SECRET`.
4. Install the App into the target GitHub organization/repositories.
5. In DCV, open **GitHub & AI** and attach the installation to the DCV organization.

GitHub installation access tokens expire after one hour, so DCV mints them on demand rather than storing them.

## OpenAI

1. Create an API key in the OpenAI platform.
2. Set `OPENAI_API_KEY` and `AI_ENABLED=true`.
3. Select a model available to your account in `AI_MODEL`.
4. Use **GitHub & AI → Test AI connection**.

## Stripe

1. Create Team and Business recurring prices.
2. Set `STRIPE_PRICE_TEAM`, `STRIPE_PRICE_BUSINESS`, and `STRIPE_SECRET_KEY`.
3. Configure the webhook URL `https://YOUR-DCV-DOMAIN/api/billing/webhook`.
4. Add `checkout.session.completed`, `customer.subscription.created`, `customer.subscription.updated`, `customer.subscription.deleted`, `invoice.paid`, and `invoice.payment_failed` events.
5. Set `STRIPE_WEBHOOK_SECRET`.

Stripe's documented pattern is to use Checkout for subscription purchase, the hosted customer portal for management, and webhooks for lifecycle synchronization.

## Argo CD / Kubernetes

Production requires a reachable Kubernetes API, Argo CD installed in that cluster, external PostgreSQL, and a populated `dcv-integrations` secret. The repository supplies the declarative Application/AppProject and Kustomize overlay; it does not manufacture the customer's external infrastructure.

Argo CD's Application specification supports automated sync, prune, self-heal and bounded retry/backoff.
