# SaaS / Enterprise Administration — DCV 15.0

DCV 10 provides organization-scoped tenancy, members, roles, invitations, usage metering, entitlements, audit logs and Stripe subscription state.

## Tenant model

Each organization owns its projects and verification history. The API uses `X-Dcv-Organization-Id` for tenant selection and a local development actor header (`X-Dcv-Actor-Email`) to emulate identity. This routing layer is deliberately separated from the authentication layer because the full production security phase is out of scope for this release.

## Plans

- FREE: 50 verification runs/month, 25 AI explanations/month, 3 projects.
- TEAM: 1,000 verification runs/month, 2,000 AI explanations/month, 25 projects.
- BUSINESS: 10,000 verification runs/month, 20,000 AI explanations/month, 100 projects.
- ENTERPRISE: unlimited limits in the product model; customer contract and provisioning remain an operational process.

Entitlements are checked before creating a verification/project and before consuming an AI explanation. Usage is persisted in PostgreSQL by calendar month.

## Billing

Stripe Checkout creates recurring subscriptions; Stripe Billing manages lifecycle/invoices; the hosted Customer Portal provides subscription and payment-method management. Stripe webhook events are persisted with an idempotency key and update local subscription state. This follows Stripe's recommended Checkout + Customer Portal + webhook pattern. https://docs.stripe.com/billing/subscriptions/build-subscriptions

## Administration

The Administration screen manages:

- organization profile
- members and roles
- invitations
- monthly usage and plan limits
- audit history

Before public exposure, connect the tenant-routing layer to the production identity provider and enforce the later security phase.
