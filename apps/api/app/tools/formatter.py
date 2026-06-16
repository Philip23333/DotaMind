import logging
from typing import Any

from app.api.v1.schemas import (
    HeroRecommendation,
    MetaReportResponse,
    Source,
)

logger = logging.getLogger(__name__)


class FormatterTool:
    """Formatting boundary for report rendering and future A2A/CAP responses."""

    def format_meta_report(
        self,
        game: str,
        patch: str,
        role: str,
        heroes: list[HeroRecommendation],
        sources: list[str],
        analysis_steps: list[str],
    ) -> MetaReportResponse:
        """Format meta report response."""
        # Calculate overall confidence from hero confidences
        confidence = (
            sum(h.confidence for h in heroes) / len(heroes) if heroes else 0.0
        )
        
        # Build source list
        source_objects = []
        if "opendota" in sources:
            source_objects.append(
                Source(
                    name="OpenDota",
                    kind="live_api",
                    url="https://api.opendota.com",
                    status="connected",
                )
            )
        if "patch_json" in sources:
            source_objects.append(
                Source(
                    name="Patch Notes",
                    kind="local_json",
                    status="loaded",
                )
            )
        
        summary = f"Analysis of {len(heroes)} {role} heroes for patch {patch}."
        logger.info(
            "Formatter meta_report start game=%s patch=%s role=%s heroes=%s "
            "sources=%s confidence=%.3f",
            game,
            patch,
            role,
            len(heroes),
            sources,
            confidence,
        )
        
        return MetaReportResponse(
            game=game,  # type: ignore
            patch=patch,
            role=role,
            summary=summary,
            top_heroes=heroes,
            sources=source_objects,
            analysis_steps=analysis_steps,
            confidence=confidence,
        )

    def json_response(self, response: Any) -> Any:
        """Generic JSON passthrough for future use."""
        return response
