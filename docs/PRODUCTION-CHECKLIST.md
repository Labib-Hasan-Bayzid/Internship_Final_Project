# Production operations checklist (security phase excluded)

This release completes the non-security product path. Before customer traffic, configure the following operational dependencies.

## GitHub

- Create the GitHub App with `docs/GITHUB-APP.md` permissions.
- Set the webhook URL to the public DCV endpoint.
- Configure the webhook secret and App private key in the production Secret.
- Protect `main` and make the DCV Check required where the customer wants a dependency gate.

## AI

- Configure an OpenAI API key in the production Secret.
- Set `AI_ENABLED=true` and `AI_AUTO_EXPLAIN=true`.
- Choose the model through `AI_MODEL`.
- Validate the AI explanation endpoint before enabling automatic explanations.

## CI/CD

- Confirm GHCR packages are published by GitHub Actions.
- Configure the `production` GitHub Environment.
- Confirm production image tags in Git are immutable commit SHAs.
- Install Argo CD in the target cluster and register the AppProject/Application.

## Database

Production does not deploy the laptop PostgreSQL StatefulSet. Provide an external PostgreSQL service and set `DATABASE_URL` in `dcv-integrations`.

## Verification

- Run a known-good dependency upgrade.
- Run an intentional compatibility/test failure.
- Run a dependency with a package-registry warning.
- Confirm PASS, REVIEW and BLOCK Checks reach GitHub correctly.
- Confirm a PR synchronization creates new verification records rather than duplicates from webhook redelivery.
- Confirm a repeated Stripe event is idempotent and an out-of-order older Stripe event cannot overwrite newer subscription state.
- Confirm GitOps image tags are commit SHAs after the Container Release workflow completes.
