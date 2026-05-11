# ABOUTME: Analyzes the editorial environment around a Wikipedia article.
# ABOUTME: Computes edit history metrics and extracts talk page context to produce a risk profile.

import asyncio
import json
import os
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import openai
from dotenv import load_dotenv

from cache import cache, cache_key, record_llm_start, record_llm_tokens
from utils.log import log_llm_call, log_llm_response
from models import WikiArticle, EditorialEnvironment
from tools.wikipedia import fetch_edit_history, fetch_talk_page

_BOT_PATTERN = re.compile(r'\bbot\b', re.IGNORECASE)
_REVERT_PATTERN = re.compile(r'\brevert(ed)?\b', re.IGNORECASE)
_SECTION_PATTERN = re.compile(r'/\*\s*(.+?)\s*\*/')


def _extract_section_name(comment: str) -> Optional[str]:
    """Extract section name from a MediaWiki edit comment like '/* Section */ ...'."""
    m = _SECTION_PATTERN.search(comment)
    return m.group(1) if m else None


def _parse_timestamp(ts: str) -> datetime:
    """Parse ISO 8601 timestamp from MediaWiki API into a UTC-aware datetime."""
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _compute_edit_metrics(edits: list[dict]) -> dict:
    """
    Compute revert_rate_12mo, edit_velocity, and dominant_editor
    from the raw list of edit dicts returned by the MediaWiki API.
    """
    cutoff_12mo = datetime.now(timezone.utc) - timedelta(days=365)
    recent = [e for e in edits if _parse_timestamp(e["timestamp"]) >= cutoff_12mo]

    if not recent:
        return {"revert_rate_12mo": 0.0, "edit_velocity": 0, "dominant_editor": None}

    revert_count = sum(
        1 for e in recent
        if _REVERT_PATTERN.search(e.get("comment", ""))
    )
    revert_rate = revert_count / len(recent)

    velocity_count = sum(
        1 for e in recent
        if not _BOT_PATTERN.search(e.get("comment", ""))
        and not _REVERT_PATTERN.search(e.get("comment", ""))
    )

    user_counts = Counter(e.get("user", "") for e in recent)
    total = len(recent)
    dominant_editor = None
    for user, count in user_counts.most_common(1):
        if count / total > 0.40:
            dominant_editor = user

    return {
        "revert_rate_12mo": revert_rate,
        "edit_velocity": velocity_count,
        "dominant_editor": dominant_editor,
    }


def _find_flip_flopped_sections(edits: list[dict]) -> list[str]:
    """
    Identify sections that appear in 4+ edit comments by 2+ distinct users
    within the last 6 months — a signal of back-and-forth editing.
    """
    cutoff_6mo = datetime.now(timezone.utc) - timedelta(days=182)
    recent = [e for e in edits if _parse_timestamp(e["timestamp"]) >= cutoff_6mo]

    section_users: dict[str, set] = defaultdict(set)
    section_counts: Counter = Counter()

    for edit in recent:
        section = _extract_section_name(edit.get("comment", ""))
        if section:
            section_counts[section] += 1
            section_users[section].add(edit.get("user", ""))

    return [
        section for section, count in section_counts.items()
        if count >= 4 and len(section_users[section]) >= 2
    ]


def _compute_risk_tier(
    revert_rate: float,
    flip_flopped: list[str],
    active_disputes: list[dict],
    dominant_editor: Optional[str],
    edit_velocity: int,
) -> str:
    """Compute risk tier from deterministic metrics (kept for v1 planner compatibility)."""
    if revert_rate > 0.30 and len(flip_flopped) > 0:
        return "CRITICAL"
    if len(flip_flopped) > 0 or (dominant_editor and revert_rate > 0.15) or len(active_disputes) >= 2:
        return "HIGH"
    if revert_rate > 0.15 or len(active_disputes) == 1 or dominant_editor:
        return "MODERATE"
    return "LOW"


def _compute_caution_level(
    revert_rate: float,
    flip_flopped: list[str],
    active_disputes: list[dict],
    dominant_editor: Optional[str],
    edit_velocity: int,
    llm_caution: str = "LOW",
) -> str:
    """Merge deterministic metrics with LLM-derived caution level."""
    deterministic = _compute_risk_tier(
        revert_rate, flip_flopped, active_disputes, dominant_editor, edit_velocity
    )
    # Take the higher of the two
    order = ["LOW", "MODERATE", "HIGH", "CRITICAL"]
    return order[max(order.index(deterministic), order.index(llm_caution))]


class EditorialContextAnalyzer:
    def __init__(self):
        load_dotenv()
        self.client = openai.AsyncOpenAI()
        self.model = os.getenv("DRAFT_MODEL", "gpt-4o")
        with open(Path(__file__).parent.parent / "prompts" / "editorial_context.txt") as f:
            self.prompt_template = f.read()

    async def run(self, article: WikiArticle) -> EditorialEnvironment:
        key = f"editorial_env:{cache_key(article.title, article.url)}"
        if key in cache:
            return EditorialEnvironment.model_validate(cache[key])

        edit_history, talk_page_text = await asyncio.gather(
            fetch_edit_history(article.title),
            fetch_talk_page(article.title),
        )

        # Stage 1: deterministic metrics
        if edit_history:
            metrics = _compute_edit_metrics(edit_history)
            flip_flopped = _find_flip_flopped_sections(edit_history)
        else:
            metrics = {"revert_rate_12mo": 0.0, "edit_velocity": 0, "dominant_editor": None}
            flip_flopped = []

        # Stage 2: LLM talk page analysis
        if talk_page_text.strip():
            talk_data = await self._analyze_talk_page(article.title, talk_page_text)
        else:
            talk_data = {
                "active_disputes": [],
                "resolved_disputes": [],
                "editor_imposed_norms": [],
                "policies_and_restrictions": [],
                "wikiproject_affiliations": [],
                "active_topics": [],
                "caution_level": "LOW",
                "environment_narrative": "The talk page is empty; no editorial disputes or norms are documented.",
            }

        # Stage 3: compute caution_level from deterministic metrics + talk page
        caution_level = _compute_caution_level(
            metrics["revert_rate_12mo"],
            flip_flopped,
            talk_data["active_disputes"],
            metrics["dominant_editor"],
            metrics["edit_velocity"],
            talk_data.get("caution_level", "LOW"),
        )

        profile = EditorialEnvironment(
            revert_rate_12mo=metrics["revert_rate_12mo"],
            edit_velocity=metrics["edit_velocity"],
            dominant_editor=metrics["dominant_editor"],
            active_topics=talk_data.get("active_topics", []),
            flip_flopped_sections=flip_flopped,
            active_disputes=talk_data["active_disputes"],
            resolved_disputes=talk_data["resolved_disputes"],
            editor_imposed_norms=talk_data["editor_imposed_norms"],
            policies_and_restrictions=talk_data.get("policies_and_restrictions", []),
            wikiproject_affiliations=talk_data["wikiproject_affiliations"],
            environment_narrative=talk_data.get("environment_narrative", talk_data.get("risk_narrative", "")),
            caution_level=caution_level,
        )
        cache.set(key, profile.model_dump(), expire=3600)
        return profile

    async def _analyze_talk_page(self, title: str, talk_text: str) -> dict:
        """Send truncated talk page to LLM and parse structured response."""
        prompt = self.prompt_template.format(
            article_title=title,
            talk_page_text=talk_text[:6000],
        )
        log_llm_call("editorial_context", self.model, prompt)
        record_llm_start()
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        record_llm_tokens(response.usage)
        raw_text = response.choices[0].message.content
        log_llm_response("editorial_context", raw_text,
                         getattr(response.usage, "prompt_tokens", 0),
                         getattr(response.usage, "completion_tokens", 0))
        return json.loads(raw_text)
