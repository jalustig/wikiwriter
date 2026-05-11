# ABOUTME: Pydantic schemas for all WikiWriter worker inputs and outputs.
# ABOUTME: Single source of truth for data models — no raw strings between workers.

from typing import Any, Literal
from pydantic import BaseModel


class ProgressEvent(BaseModel):
    stage: str
    status: Literal["running", "done", "error", "thinking", "summary"]
    message: str
    data: dict | None = None
    count: int | None = None   # current item in a batch
    total: int | None = None   # total items in the batch


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
    topic_coverage_summary: str      # what aspects of the topic this source covers
    recommendation: Literal["USE", "WEAK", "REJECT"]
    claims: list[str] = []           # factual claims about the topic found in this source


class ContentGrade(BaseModel):
    overall_score: float
    letter_grade: str
    section_grades: dict[str, float]
    dimension_scores: dict[str, float]
    narrative: str


class EditorialEnvironment(BaseModel):
    revert_rate_12mo: float
    edit_velocity: int
    dominant_editor: str | None = None
    active_topics: list[str] = []
    flip_flopped_sections: list[str] = []
    active_disputes: list[dict] = []
    resolved_disputes: list[dict] = []
    editor_imposed_norms: list[str] = []
    policies_and_restrictions: list[str] = []
    wikiproject_affiliations: list[str] = []
    environment_narrative: str = ""
    caution_level: Literal["LOW", "MODERATE", "HIGH", "CRITICAL"] = "LOW"


# --- v2 article summary ---
class ArticleSummary(BaseModel):
    topic: str    # what this article is about, in 1-2 sentences
    scope: str    # what is included and what is not


# --- v2 assessment models ---
class ArticleImportance(BaseModel):
    tier: Literal["VITAL", "MAJOR", "NOTABLE", "MINOR"]
    rationale: str
    expected_depth: str


class SectionDecision(BaseModel):
    name: str
    action: Literal["EDIT", "SKIP"]
    edit_type: Literal["EXPAND", "FACT_CHECK", "PRUNE", "CITE_REPAIR"] | None = None
    rationale: str


class ArticleAssessment(BaseModel):
    importance: ArticleImportance
    article_class: Literal["STUB", "DEVELOPING", "COMPLETE", "OVER_DETAILED"]
    effort_ceiling: Literal["FULL", "MODERATE", "LIGHT"]
    edit_scope: Literal["WHOLE_ARTICLE", "SPECIFIC_SECTIONS"]
    sections: list[SectionDecision]          # only EDIT sections (capped at 2-3)
    primary_weaknesses: list[str]
    source_quality_summary: str
    source_trust_verdict: str = ""           # can this article be trusted as-is?
    edit_rationale: str
    no_edit: bool = False                    # True when guardrails block editing
    no_edit_reason: str = ""                 # human-readable guardrail explanation
    would_edit_sections: list[SectionDecision] = []  # what we'd fix if allowed
    scope_of_work: str = ""                  # 3-sentence brief of what will be done


# --- v1 planning models (kept for backward compat) ---
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


class SectionResearch(BaseModel):
    section_name: str
    claim_map: ClaimMap
    new_sources: list[SourceEvaluation] = []


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


class SectionCritiqueResult(BaseModel):
    section_name: str
    verdict: Literal["PASS", "FAIL"]
    dimensions: dict[str, DimensionCritique] = {}
    issues: list[str] = []
    suggested_fix: str = ""


class CritiqueResult(BaseModel):
    overall_verdict: Literal["PASS", "REVISE", "PARTIAL_ACCEPT", "DISCARD"]
    dimension_results: dict[str, DimensionCritique] = {}
    revision_instructions: list[str] = []
    discard_reason: str | None = None
    # v2 section-level fields
    section_results: dict[str, SectionCritiqueResult] = {}
    revision_scope: Literal["SECTIONS", "FULL_ARTICLE"] | None = None
    passing_sections: list[str] = []
    failing_sections: list[str] = []


class EditSummary(BaseModel):
    narrative: str
    sections_changed: list[str]
    disclosure_line: str


class EditProposal(BaseModel):
    article: WikiArticle
    input_grade: ContentGrade
    output_grade: ContentGrade
    quality_delta: float
    editorial_environment: EditorialEnvironment
    assessment: ArticleAssessment
    source_audit: list[SourceEvaluation]
    new_sources: list[SourceEvaluation]
    section_drafts: list[SectionDraft]
    critique: CritiqueResult
    edit_summary: EditSummary
    full_diff: str


# --- DAG task types ---
class TaskNode(BaseModel):
    id: str
    type: str
    params: dict[str, Any] = {}
    deps: list[str] = []
    status: Literal["pending", "running", "done", "failed"] = "pending"
    result: Any = None
