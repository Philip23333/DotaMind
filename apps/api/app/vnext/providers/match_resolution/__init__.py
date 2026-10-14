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
from .resolver import (
    CandidateAssessment,
    GameResolutionResult,
    resolve_game,
)

__all__ = [
    "GameCandidate",
    "GameCandidateResult",
    "GameIdentityEvidence",
    "GameIdentityFacts",
    "GameResolutionResult",
    "CandidateAssessment",
    "ParticipantAssociation",
    "ParticipantFact",
    "compare_game_identity_evidence",
    "find_game_candidates",
    "resolve_game",
]
