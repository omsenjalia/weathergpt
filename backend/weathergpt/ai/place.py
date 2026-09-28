"""Find the place a question is about ("rain in Pune tomorrow", "Ahmedabad ma varsad", "दिल्ली में मौसम")."""

from __future__ import annotations

import re
from typing import Optional

from weathergpt import geo

STOP = {
    "weather", "temperature", "temp", "forecast", "rain", "raining", "today", "tomorrow", "tonight", "now", "current",
    "week", "weekend", "morning", "evening", "night", "the", "is", "it", "will", "be", "there", "what", "whats",
    "what's", "how", "hot", "cold", "going", "to", "a", "an", "of", "any", "chance", "air", "quality", "aqi", "alert",
    "alerts", "warning", "mausam", "baarish", "barish", "kaisa", "kya", "hai", "aaj", "kal", "kem", "che", "chhe",
    "varsad", "please", "me", "tell", "about", "like", "next", "days", "day", "hours", "should", "i", "my", "for",
    "in", "at", "near", "around", "and", "or", "with", "farm", "crop", "spray", "irrigate", "irrigation", "wind",
    "humidity", "uv", "sunrise", "sunset", "pollution", "storm", "thunderstorm", "heat", "wave", "cyclone",
}
_EN = re.compile(r"\b(?:in|at|for|near|around|of)\s+([a-z][a-z .'-]{1,40})", re.I)
_INDIC_LATIN = re.compile(r"([a-z][a-z .'-]{1,40}?)\s+(?:ma|maa|me|mein|mai|nu|na|ni|ka|ki|ke|par|mathi)\b", re.I)
_DEVANAGARI = re.compile(r"([ऀ-ॿ]{2,}(?:\s[ऀ-ॿ]{2,})?)\s*(?:में|का|की|के|मध्ये|चा|ची)")
_GUJARATI = re.compile(r"([઀-૿]{2,}?)(?:માં|નું|ના|ની|\s+માં)")


def _clean(candidate: str) -> Optional[str]:
    words = [w for w in re.split(r"\s+", candidate.strip(" .,'-")) if w and w.lower() not in STOP]
    text = " ".join(words).strip()
    return text if len(text) >= 3 else None


def candidates(question: str) -> list[str]:
    q = (question or "").strip()
    found: list[str] = []
    for pattern in (_EN, _INDIC_LATIN, _DEVANAGARI, _GUJARATI):
        for m in pattern.finditer(q):
            c = _clean(m.group(1))
            if c and c.lower() not in (x.lower() for x in found):
                found.append(c)
    return found[:3]


def resolve(question: str) -> Optional[dict]:
    """Geocode the first candidate place named in ``question``; None when none is named or found."""
    for name in candidates(question):
        hit = geo.geocode(name)
        if hit:
            return hit
    return None
