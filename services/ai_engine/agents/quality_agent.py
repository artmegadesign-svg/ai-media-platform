"""Deterministic checks for the existing short-news generation flow."""

import re


class QualityAgent:
    MIN_VISIBLE_LENGTH = 700
    MAX_VISIBLE_LENGTH = 900
    SERVICE_SECTION_PATTERN = r"(?:HOOK|INSIGHT|VALUE|CONCLUSION)"
    _MARKER = re.compile(rf"(?im)^\s*(?:\#{{1,6}}\s+)?(?:\*\*)?{SERVICE_SECTION_PATTERN}(?:\*\*)?\s*(?::|$)")
    _MARKDOWN = re.compile(
        r"\*\*|`|__[^\n]+__|!?\[[^\n]*\]\([^\n]*\)|"
        r"(?<!\w)[*_][^\n*_]+[*_](?!\w)|(?m:^\s*(?:\#{1,6}|[-*+]|>)\s+)"
    )
    _HTML = re.compile(r"</?[A-Za-z][^>\n]*>")
    _ASSISTANT = re.compile(
        r"(?:^|(?<=[.!?])\s+)[ \t]*(?:[-—–]\s*)?(?:"
        r"если\s+(?:вы\s+)?хотите|"
        r"если\s+нужно\s*[,—–-]?\s*(?:я\s+)?могу|"
        r"при\s+(?:желании|необходимости)\s*[,—–-]?\s*(?:я\s+)?могу|"
        r"буду\s+рад(?:а)?\s+помочь|дайте\s+знать|готов(?:а)?\s+(?:подготовить|помочь|предложить)|"
        r"могу\s+(?:предложить|подготовить|составить|помочь)|"
        r"(?:конечно[,!]\s*)?(?:вот|ниже)\s+(?:[—–-]\s*)?(?:краткая|короткая|готовая|новость|текст)|"
        r"if\s+you(?: would|'d|’d)?\s+(?:like|want|need)|"
        r"i\s+(?:can|could|would be happy)|let\s+me\s+know|would\s+you\s+like|as\s+an\s+ai|"
        r"(?:sure[,!]\s*)?here(?:'s| is)\s+(?:the|a|your)\s+(?:news|post|article|translation)"
        r")\b", re.I | re.M,
    )

    @classmethod
    def surface_issues(cls, content: str) -> list[str]:
        """Shared fail-closed check; no rewriting and no provider-specific length rule."""
        if not isinstance(content, str) or not content.strip():
            return ["Empty content"]
        issues = []
        if cls._MARKER.search(content):
            issues.append("Service section marker")
        if cls._MARKDOWN.search(content) or cls._HTML.search(content):
            issues.append("Raw markup in publication text")
        if cls._ASSISTANT.search(content):
            issues.append("AI assistant phrase")
        return issues

    @staticmethod
    def visible_length(content: str) -> int:
        return len(" ".join(content.split()))

    def check(self, content: str) -> dict:
        issues = self.surface_issues(content)
        if isinstance(content, str) and content.strip():
            length = self.visible_length(content)
            if length < self.MIN_VISIBLE_LENGTH:
                issues.append("Content too short (minimum 700 visible characters)")
            if length > self.MAX_VISIBLE_LENGTH:
                issues.append("Content too long (maximum 900 visible characters)")
            lines = [line.strip() for line in content.splitlines() if line.strip()]
            if len(lines) < 2:
                issues.append("Headline and news body are required")
            if lines and len(lines[0]) > 140:
                issues.append("Headline too long")
        return {"score": max(0, 100 - 20 * len(issues)), "approved": not issues, "issues": issues}
