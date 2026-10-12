# Stripe Billing Setup

1. Create Stripe Products/Prices for Team and Business.
2. Put the recurring price IDs in `STRIPE_PRICE_TEAM` and `STRIPE_PRICE_BUSINESS`.
3. Set `STRIPE_SECRET_KEY` in the backend deployment secret.
4. Create a Stripe webhook endpoint at:

```text
https://YOUR-DCV-DOMAIN/api/billing/webhook
```

5. Subscribe to these events:

```text
checkout.session.completed
customer.subscription.created
customer.subscription.updated
customer.subscription.deleted
invoice.paid
invoice.payment_failed
```

6. Put the webhook signing secret in `STRIPE_WEBHOOK_SECRET`.

7. Use the DCV Billing screen to create Checkout sessions or open the hosted Customer Portal.

Stripe recommends using webhooks to keep subscription state synchronized because subscription and invoice lifecycles are asynchronous. https://docs.stripe.com/billing/subscriptions/webhooks
