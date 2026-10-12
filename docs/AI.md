# AI Integration

AI is an explanation service, not the authorization gate.

Flow:

```text
Evidence
  -> deterministic comparator
  -> PASS / REVIEW / BLOCK
  -> OpenAI explanation
```

Set:

```text
AI_ENABLED=true
AI_AUTO_EXPLAIN=true
AI_MODEL=<configured OpenAI model>
OPENAI_API_KEY=...
```

Completed verification runs are queued for explanation. The worker tracks attempts, failure state and retry time. Manual explanation is also available from the run detail view.

The prompt instructs the model to use only supplied evidence and never override the deterministic decision. Calls use the Responses API and `store=false`.

Provider failures do not change the deterministic gate. Automatic AI work is retried up to the configured attempt limit; after the limit, the verification remains valid with its original PASS/REVIEW/BLOCK result and a failed AI status.
