# CAP Integration Notes

> **Status: parked.** CAP/CROO work is intentionally outside the active
> `feature/v3-functional-loop` development line. Do not implement or merge it
> unless the project explicitly resumes this capability.

CAP integration is not implemented. The previous fixed report service catalog
has been removed together with the old report endpoints.

Future CAP work should price agentic capabilities around `/api/v1/plan`
contracts rather than resurrecting fixed service routes.

## Current Boundary

- No `/api/v1/services` discovery endpoint.
- No paid report endpoints.
- No payment verification or callback handling.
- No compatibility wrapper around deleted report services.

## Planned Order Flow

```text
1. Caller selects a registered agentic output contract, such as
   `natural_language_answer`.
2. Caller creates a CAP order with query, output_contract intent, price, and payload hash.
3. MetaMind verifies order status or receives a callback.
4. MetaMind runs /api/v1/plan.
5. MetaMind returns plan, evidence, answer, critic review, sources, and confidence metadata.
6. MetaMind writes an audit record for replay, dispute handling, and demo proof.
```

## Candidate Payload Shape

```json
{
  "output_contract": "natural_language_answer",
  "price_usdc": 0.1,
  "input": {
    "game": "dota2",
    "query": "enemy picked Lina, what should I pick?"
  },
  "callback_url": "https://agent.example/callback",
  "request_id": "external-order-id"
}
```

## Audit Fields

Persist these fields when database support is added:

- `request_id`
- `cap_order_id`
- `output_contract`
- `price_usdc`
- `payment_status`
- `input_hash`
- `response_hash`
- `sources`
- `confidence`
- `created_at`

## Compliance Boundary

The MVP should not provide betting recommendations. It can provide public
esports intelligence, patch adaptation analysis, evidence checks, and team
context.
