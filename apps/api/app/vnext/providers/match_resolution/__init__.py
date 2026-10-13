"""Provider-side cross-source match resolution primitives."""

from .candidates import (
    GameCandidate,
    GameCandidateResult,
    find_game_candidates,
)

__all__ = ["GameCandidate", "GameCandidateResult", "find_game_candidates"]
