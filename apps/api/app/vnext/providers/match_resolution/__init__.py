"""Provider-side cross-source match resolution primitives."""

from .candidates import (
    GameCandidate,
    GameCandidateResult,
    find_game_candidates,
)
from .evidence import (
    GameIdentityEvidence,
    GameIdentityFacts,
    ParticipantAssociation,
    ParticipantFact,
    compare_game_identity_evidence,
)

__all__ = [
    "GameCandidate",
    "GameCandidateResult",
    "GameIdentityEvidence",
    "GameIdentityFacts",
    "ParticipantAssociation",
    "ParticipantFact",
    "compare_game_identity_evidence",
    "find_game_candidates",
]
