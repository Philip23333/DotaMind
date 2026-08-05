from app.application.idempotency import build_request_hash


def test_request_hash_uses_exact_validated_inputs_and_canonical_json() -> None:
    assert build_request_hash(query="Lina", game="dota2") == build_request_hash(
        game="dota2", query="Lina"
    )
    assert build_request_hash(query="Lina", game="dota2") != build_request_hash(
        query="lina", game="dota2"
    )
