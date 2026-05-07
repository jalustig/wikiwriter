# ABOUTME: Pydantic schemas for all WikiWriter worker inputs and outputs.
# ABOUTME: Single source of truth for data models — no raw strings between workers.

from typing import Literal
from pydantic import BaseModel


class ProgressEvent(BaseModel):
    stage: str
    status: Literal["running", "done", "error", "thinking"]
    message: str
    data: dict | None = None


class Citation(BaseModel):
    id: str               # cite key or index within the article
    url: str
    claim_text: str       # the sentence this citation supports


class WikiArticle(BaseModel):
    title: str
    url: str
    wikitext: str
    sections: list[str]              # section names in order
    section_texts: dict[str, str]    # section name → raw wikitext
    citations: list[Citation]
    assessment_class: str | None     # stub / start / C / B / A / FA


class SourceEvaluation(BaseModel):
    url: str
    status: Literal["LIVE", "ARCHIVED", "DEAD"]
    domain_type: str
    scores: dict[str, float]
    overall_score: float
    author: str | None = None
    publication: str | None = None
    publication_date: str | None = None
    claim_support_summary: str
    recommendation: Literal["USE", "WEAK", "REJECT"]
    further_claims: list[str] = []


class ContentGrade(BaseModel):
    overall_score: float
    letter_grade: str
    section_grades: dict[str, float]
    dimension_scores: dict[str, float]
    narrative: str


class EditorialRiskProfile(BaseModel):
    risk_tier: Literal["LOW", "MODERATE", "HIGH", "CRITICAL"]
    revert_rate_12mo: float
    edit_velocity: int
    dominant_editor: str | None = None
    flip_flopped_sections: list[str]
    active_disputes: list[dict]
    resolved_disputes: list[dict]
    editor_imposed_norms: list[str]
    wikiproject_affiliations: list[str]
    risk_narrative: str


class SectionPlan(BaseModel):
    name: str
    modes: list[str]
    rationale: str


class ImprovementPlan(BaseModel):
    sections_to_edit: list[SectionPlan]
    sections_excluded: list[str]
    exclusion_reasons: dict[str, str]
    narrative: str


class Claim(BaseModel):
    text: str
    status: Literal["cited", "undercited", "uncited", "consensus-uncited"]
    citation_id: str | None = None


class ClaimMap(BaseModel):
    claims: list[Claim]


class SectionDraft(BaseModel):
    section_name: str
    original_text: str
    revised_text: str
    changes_made: list[str]
    citations_added: list[str]
    citations_removed: list[str]


class DimensionCritique(BaseModel):
    verdict: Literal["PASS", "FAIL"]
    notes: str


class CritiqueResult(BaseModel):
    overall_verdict: Literal["PASS", "REVISE", "DISCARD"]
    dimension_results: dict[str, DimensionCritique]
    revision_instructions: list[str]
    discard_reason: str | None = None


class EditProposal(BaseModel):
    article: WikiArticle
    input_grade: ContentGrade
    output_grade: ContentGrade
    quality_delta: float
    editorial_risk: EditorialRiskProfile
    improvement_plan: ImprovementPlan
    source_audit: list[SourceEvaluation]
    new_sources: list[SourceEvaluation]
    section_drafts: list[SectionDraft]
    critique: CritiqueResult
    full_diff: str
    disclosure_edit_summary: str
