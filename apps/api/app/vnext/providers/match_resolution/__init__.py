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
from .leagues import (
    LeagueCandidate,
    LeagueCandidateCategory,
    LeagueCandidateResult,
    LeagueFieldComparison,
    find_league_candidates,
)
from .resolver import (
    CandidateAssessment,
    GameResolutionResult,
    LeagueScopedCandidateAssessment,
    LeagueSearchDiagnostic,
    MultiLeagueCandidateAssessment,
    MultiLeagueGameResolutionResult,
    MultiLeagueResolutionCategory,
    resolve_game,
    resolve_game_across_leagues,
)

__all__ = [
    "GameCandidate",
    "GameCandidateResult",
    "GameIdentityEvidence",
    "GameIdentityFacts",
    "LeagueCandidate",
    "LeagueCandidateCategory",
    "LeagueCandidateResult",
    "LeagueFieldComparison",
    "GameResolutionResult",
    "CandidateAssessment",
    "LeagueScopedCandidateAssessment",
    "LeagueSearchDiagnostic",
    "MultiLeagueCandidateAssessment",
    "MultiLeagueGameResolutionResult",
    "MultiLeagueResolutionCategory",
    "ParticipantAssociation",
    "ParticipantFact",
    "compare_game_identity_evidence",
    "find_game_candidates",
    "find_league_candidates",
    "resolve_game_across_leagues",
    "resolve_game",
]
