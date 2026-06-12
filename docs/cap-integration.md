# CAP Integration Notes

CAP integration is not implemented in the skeleton. This file defines the intended contract so the backend can be wired to a paid agent marketplace without changing report schemas.

## Paid Services

| Service | Endpoint | Price |
| --- | --- | --- |
| `get_meta_report` | `/api/v1/meta-report` | 0.1 USDC |
| `get_team_report` | `/api/v1/team-report` | 0.3 USDC |
| `get_patch_impact` | `/api/v1/patch-impact` | 0.5 USDC |
| `verify_meta_claim` | `/api/v1/verify-claim` | 0.05 USDC |

## Planned Order Flow

```text
1. Caller discovers services through /api/v1/services.
2. Caller creates a CAP order with service name, price, and request payload hash.
3. MetaMind receives order callback or verifies order status.
4. MetaMind runs the matching report service.
5. MetaMind returns structured JSON plus sources, confidence, and evidence labels.
6. MetaMind writes an audit record for replay, dispute handling, and demo proof.
```

## Service Payload Shape

```json
{
  "service": "get_meta_report",
  "price_usdc": 0.1,
  "input": {
    "game": "dota2",
    "patch": "latest",
    "role": "offlane"
  },
  "callback_url": "https://agent.example/callback",
  "request_id": "external-order-id"
}
```

## Audit Fields

Persist these fields when database support is added:

- `request_id`
- `cap_order_id`
- `service_name`
- `price_usdc`
- `payment_status`
- `input_hash`
- `response_hash`
- `sources`
- `confidence`
- `created_at`

## Compliance Boundary

The MVP should not provide betting recommendations. It can provide public esports intelligence, patch adaptation analysis, evidence checks, and team context.
