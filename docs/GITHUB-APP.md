# GitHub App Setup

Create a GitHub App in the customer/owner GitHub account with these repository permissions:

- Contents: Read-only
- Metadata: Read-only
- Pull requests: Read-only
- Checks: Read and write
- Issues: Read and write (used for a single upserted PR summary comment)

Subscribe to:

- `pull_request`
- `installation`
- `installation_repositories`

Set the App webhook URL to:

```text
https://YOUR-DCV-DOMAIN/webhooks/github
```

Set a high-entropy webhook secret. DCV validates `X-Hub-Signature-256` before persisting the delivery. GitHub recommends HMAC-SHA256 signature validation for webhook authenticity. https://docs.github.com/en/webhooks/using-webhooks/validating-webhook-deliveries

DCV then creates a short-lived installation access token for repository API calls. Installation tokens expire after one hour; the implementation creates a token when it needs to act rather than persisting a token. https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/authenticating-as-a-github-app-installation

Use the organization-specific **Install App for this organization** link in DCV. DCV sends an organization state value through the GitHub App installation flow; the setup endpoint verifies the installation through GitHub, links it to that organization, and requeues waiting webhook deliveries. The local/demo identity layer is still intentionally outside the production security phase.
