from __future__ import annotations

import json
import re

import google.generativeai as genai
from loguru import logger
from pydantic import BaseModel, Field, ValidationError, field_validator

from sales_engine.models import Lead
from sales_engine.utils import get_settings, truncate


class Personalization(BaseModel):
    company_summary: str = Field(min_length=20)
    pain_points: list[str] = Field(min_length=1, max_length=5)
    personalized_email: str = Field(min_length=40)

    @field_validator("personalized_email")
    @classmethod
    def email_under_150_words(cls, value: str) -> str:
        words = re.findall(r"\b\w+\b", value)
        if len(words) > 150:
            return " ".join(value.split()[:150])
        return value


class GeminiService:
    def __init__(self) -> None:
        self.settings = get_settings()
        if self.settings.gemini_api_key:
            genai.configure(api_key=self.settings.gemini_api_key)
            self.model = genai.GenerativeModel(self.settings.gemini_model)
        else:
            self.model = None

    def generate(self, lead: Lead) -> Personalization:
        if not self.model:
            logger.warning("GEMINI_API_KEY missing; using deterministic local personalization for lead {}", lead.id)
            return self._fallback(lead)
        prompt = self._prompt(lead)
        response = self.model.generate_content(prompt, generation_config={"response_mime_type": "application/json"})
        try:
            return Personalization.model_validate_json(response.text)
        except (ValidationError, json.JSONDecodeError) as exc:
            logger.error("Gemini response validation failed: {}", exc)
            return self._fallback(lead)

    def _prompt(self, lead: Lead) -> str:
        return f"""
Return strict JSON with keys company_summary, pain_points (array), personalized_email.
Create concise B2B sales personalization for {lead.company_name}.
Industry: {lead.industry or 'Unknown'}.
Website title: {lead.title or ''}
Meta description: {lead.meta_description or ''}
Website text: {truncate(lead.visible_text, 4000)}
Value proposition: {self.settings.value_proposition}
Email rules: mention company, industry, one pain point, the value proposition, include a CTA, maximum 150 words.
""".strip()

    def _fallback(self, lead: Lead) -> Personalization:
        industry = lead.industry or "General Business"
        pain = f"turning website interest into consistent qualified sales conversations in {industry.lower()}"
        summary = f"{lead.company_name} appears to operate in {industry}, based on its website messaging and homepage content."
        email = (
            f"Hi {lead.company_name} team,\n\n"
            f"I noticed {lead.company_name} is in the {industry} space. A common challenge for teams like yours is {pain}. "
            f"{self.settings.value_proposition} Would it be worth a 15-minute conversation next week to see whether this could support your growth goals?\n\n"
            f"Best,\n{self.settings.sender_name}"
        )
        return Personalization(company_summary=summary, pain_points=[pain], personalized_email=truncate(email, 1200))
