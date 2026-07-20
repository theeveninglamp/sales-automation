from __future__ import annotations

import argparse
import importlib
import importlib.util
import json
import os
import re
from dataclasses import asdict, dataclass
from typing import Any, Protocol

DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
DEFAULT_SENDER_NAME = "Sales Team"
DEFAULT_VALUE_PROPOSITION = (
    "We help revenue teams identify qualified opportunities and automate personalized outreach without losing human oversight."
)
MAX_EMAIL_WORDS = 150
MAX_PROMPT_WEBSITE_CHARS = 4000


class LeadLike(Protocol):
    id: int | None
    company_name: str
    industry: str | None
    title: str | None
    meta_description: str | None
    visible_text: str | None


@dataclass(frozen=True)
class GeminiSettings:
    api_key: str | None
    model: str
    sender_name: str
    value_proposition: str

    @classmethod
    def from_environment(cls) -> GeminiSettings:
        return cls(
            api_key=os.getenv("GEMINI_API_KEY") or None,
            model=os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL),
            sender_name=os.getenv("SENDER_NAME", DEFAULT_SENDER_NAME),
            value_proposition=os.getenv("VALUE_PROPOSITION", DEFAULT_VALUE_PROPOSITION),
        )


@dataclass(frozen=True)
class Personalization:
    company_summary: str
    pain_points: list[str]
    personalized_email: str

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> Personalization:
        summary = str(payload.get("company_summary", "")).strip()
        raw_pain_points = payload.get("pain_points", [])
        if isinstance(raw_pain_points, str):
            pain_points = [line.strip(" -•") for line in raw_pain_points.splitlines() if line.strip(" -•")]
        elif isinstance(raw_pain_points, list):
            pain_points = [str(point).strip() for point in raw_pain_points if str(point).strip()]
        else:
            pain_points = []
        email = _limit_words(str(payload.get("personalized_email", "")).strip(), MAX_EMAIL_WORDS)
        errors = []
        if len(summary) < 20:
            errors.append("company_summary must contain at least 20 characters")
        if not pain_points:
            errors.append("pain_points must contain at least one item")
        if len(email) < 40:
            errors.append("personalized_email must contain at least 40 characters")
        if errors:
            raise ValueError("; ".join(errors))
        return cls(company_summary=summary, pain_points=pain_points[:5], personalized_email=email)

    @classmethod
    def from_json(cls, text: str) -> Personalization:
        return cls.from_mapping(_extract_json_object(text))


def _load_google_genai() -> Any | None:
    if importlib.util.find_spec("google") is None:
        return None
    if importlib.util.find_spec("google.generativeai") is None:
        return None
    return importlib.import_module("google.generativeai")


def _truncate(text: str | None, max_chars: int) -> str:
    if not text:
        return ""
    clean = re.sub(r"\s+", " ", text).strip()
    return clean[: max_chars - 1] + "…" if len(clean) > max_chars else clean


def _limit_words(text: str, max_words: int) -> str:
    words = text.split()
    return " ".join(words[:max_words]) if len(words) > max_words else text


def _extract_json_object(text: str) -> dict[str, Any]:
    clean = text.strip()
    if clean.startswith("```"):
        clean = re.sub(r"^```(?:json)?\s*", "", clean)
        clean = re.sub(r"\s*```$", "", clean)
    try:
        payload = json.loads(clean)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", clean, flags=re.S)
        if not match:
            raise
        payload = json.loads(match.group(0))
    if not isinstance(payload, dict):
        raise ValueError("Gemini response must be a JSON object")
    return payload


class GeminiService:
    def __init__(self, settings: GeminiSettings | None = None) -> None:
        self.settings = settings or GeminiSettings.from_environment()
        self._genai = _load_google_genai()
        self.model = None
        if self.settings.api_key and self._genai is not None:
            self._genai.configure(api_key=self.settings.api_key)
            self.model = self._genai.GenerativeModel(self.settings.model)

    @property
    def is_configured(self) -> bool:
        return self.model is not None

    def generate(self, lead: LeadLike) -> Personalization:
        if not self.is_configured:
            return self._fallback(lead)
        prompt = self._prompt(lead)
        response = self.model.generate_content(prompt, generation_config={"response_mime_type": "application/json"})
        response_text = getattr(response, "text", "")
        try:
            return Personalization.from_json(response_text)
        except (json.JSONDecodeError, ValueError):
            return self._fallback(lead)

    def _prompt(self, lead: LeadLike) -> str:
        return f"""
Return strict JSON with exactly these keys: company_summary, pain_points, personalized_email.
company_summary: one concise sentence about {lead.company_name}.
pain_points: array of 1-3 likely business pain points grounded in the website.
personalized_email: a complete B2B sales email under {MAX_EMAIL_WORDS} words.

Company: {lead.company_name}
Industry: {lead.industry or 'Unknown'}
Website title: {lead.title or ''}
Meta description: {lead.meta_description or ''}
Website text: {_truncate(lead.visible_text, MAX_PROMPT_WEBSITE_CHARS)}
Value proposition: {self.settings.value_proposition}

Email requirements: mention the company, mention the industry, mention one pain point, mention the value proposition, include a clear CTA, and stay under {MAX_EMAIL_WORDS} words.
""".strip()

    def _fallback(self, lead: LeadLike) -> Personalization:
        industry = lead.industry or "General Business"
        pain = f"turning website interest into consistent qualified sales conversations in {industry.lower()}"
        summary = f"{lead.company_name} appears to operate in {industry}, based on its website messaging and homepage content."
        email = (
            f"Hi {lead.company_name} team,\n\n"
            f"I noticed {lead.company_name} is in the {industry} space. A common challenge for teams like yours is {pain}. "
            f"{self.settings.value_proposition} Would it be worth a 15-minute conversation next week to see whether this could support your growth goals?\n\n"
            f"Best,\n{self.settings.sender_name}"
        )
        return Personalization.from_mapping({
            "company_summary": summary,
            "pain_points": [pain],
            "personalized_email": email,
        })


@dataclass(frozen=True)
class DemoLead:
    id: int | None
    company_name: str
    industry: str | None
    title: str | None
    meta_description: str | None
    visible_text: str | None


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate Gemini sales personalization for a demo or supplied company.")
    parser.add_argument("--company", default="Acme Automation", help="Company name")
    parser.add_argument("--industry", default="SaaS", help="Industry")
    parser.add_argument("--title", default="Acme Automation Platform", help="Website title")
    parser.add_argument("--description", default="Workflow automation for revenue teams.", help="Meta description")
    parser.add_argument("--text", default="Acme provides cloud software, APIs, and workflow automation for sales teams.", help="Website text")
    args = parser.parse_args()
    lead = DemoLead(None, args.company, args.industry, args.title, args.description, args.text)
    personalization = GeminiService().generate(lead)
    print(json.dumps(asdict(personalization), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
