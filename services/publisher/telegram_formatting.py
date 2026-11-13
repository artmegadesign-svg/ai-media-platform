"""Small, deliberately bounded Markdown subset for Telegram's HTML API.

Input is source text, never trusted HTML. Both representations are built from
the same tokens so plain-caption fallback cannot expose Markdown delimiters.
"""

import re
from html import escape
from urllib.parse import urlsplit

from services.ai_engine.agents.quality_agent import QualityAgent


_INLINE = re.compile(
    r"\\([\\`*_\[\]])|`([^`\n]+)`|"
    r"\[([^\]\n]+)\]\((https?://[^\s()]+)\)|"
    r"\*\*(?=\S)(.+?)(?<=\S)\*\*(?!\*)|__(?=\S)(.+?)(?<=\S)__(?!_)|"
    r"(?<!\w)\*(?=\S)([^*\n]+?)(?<=\S)\*(?!\w)|"
    r"(?<!\w)_(?=\S)([^_\n]+?)(?<=\S)_(?!\w)"
)
_LABEL = re.compile(
    rf"^(?:#{{1,6}}\s+)?(?:\*\*)?{QualityAgent.SERVICE_SECTION_PATTERN}"
    r"(?:\*\*)?\s*(?::\s*|$)", re.I,
)
_UNSUPPORTED_INLINE = re.compile(
    r"~~|__|!\[|\[\^|\[[^\]\n]+\]\s*\[|\]\(|<https?://|"
    r"(?<!\w)[*_](?=\S)|(?<=\S)[*_](?!\w)"
)
_UNSUPPORTED_BLOCK = re.compile(
    r"^\s*(?:\d+[.)]\s+|[-*_](?:\s*[-*_]){2,}\s*$|=+\s*$|"
    r"\||:?-{3,}:?(?:\s*\|\s*:?-{3,}:?)+\s*$|"
    r"\[[^\]]+\]:\s|~~~| {4}\S)"
)


def _literal(source: str) -> str:
    if QualityAgent._MARKDOWN.search(source) or _UNSUPPORTED_INLINE.search(source):
        raise ValueError("Unsupported Markdown in publication")
    return escape(source, quote=False)


def _inline(
    source: str, depth: int = 0, *, active: frozenset[str] = frozenset()
) -> tuple[str, str]:
    if depth > 8:
        raise ValueError("Markdown nesting is too deep")
    plain, rendered = [], []
    end = 0
    for match in _INLINE.finditer(source):
        if match.group(3) is not None and match.start() and source[match.start() - 1] == "!":
            raise ValueError("Inline Markdown images are unsupported")
        literal = source[end:match.start()]
        plain.append(literal)
        rendered.append(_literal(literal))
        escaped, code, label, url, bold, underbold, italic, underitalic = match.groups()
        if escaped is not None or code is not None:
            text = escaped if escaped is not None else code
            html = escape(text, quote=False)
            if code is not None:
                if active:
                    raise ValueError("Telegram code cannot be nested in formatting or links")
                html = f"<code>{html}</code>"
        else:
            if label is not None and re.search(r"(?<!\\)\[", label):
                raise ValueError("Nested Markdown links are unsupported")
            tag = "a" if url is not None else ("b" if bold or underbold else "i")
            if tag == "a" and "a" in active:
                raise ValueError("Nested Markdown links are unsupported")
            text, html = _inline(
                label or bold or underbold or italic or underitalic,
                depth + 1, active=active | {tag},
            )
            if url is not None:
                if not urlsplit(url).hostname:
                    raise ValueError("Invalid Markdown link")
                html = f'<a href="{escape(url, quote=True)}">{html}</a>'
                # Keep the destination when caption budgeting requires plain text.
                text = f"{text} ({url})"
            else:
                if tag not in active:
                    html = f"<{tag}>{html}</{tag}>"
        plain.append(text)
        rendered.append(html)
        end = match.end()
    literal = source[end:]
    plain.append(literal)
    rendered.append(_literal(literal))
    return "".join(plain), "".join(rendered)


def render_news(text: str) -> tuple[str, str]:
    if not isinstance(text, str):
        raise ValueError("Empty content")
    lines = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").strip().split("\n"):
        if _LABEL.match(line.strip()):
            line = _LABEL.sub("", line.strip(), count=1)
        if not line.strip():
            lines.append("")
            continue
        if _UNSUPPORTED_BLOCK.search(line):
            raise ValueError("Unsupported Markdown block in publication")
        heading = bool(re.match(r"^ {0,3}#{1,6}\s+", line))
        if heading:
            line = re.sub(r"^ {0,3}#{1,6}\s+", "", line)
            line = re.sub(r"\s+#+\s*$", "", line)
        bold_line = heading or not any(lines)
        plain, html = _inline(line, active=frozenset({"b"}) if bold_line else frozenset())
        if bold_line:
            html = f"<b>{html}</b>"
        lines.append((plain, html))
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    if not lines:
        raise ValueError("Empty content")
    body = lines[1:]
    while body and not body[0]:
        body.pop(0)
    plain = lines[0][0]
    html = lines[0][1]
    if body:
        plain += "\n\n" + "\n".join(item[0] if item else "" for item in body)
        html += "\n\n" + "\n".join(item[1] if item else "" for item in body)
    if QualityAgent._ASSISTANT.search(plain) or QualityAgent._MARKER.search(plain):
        raise ValueError("Publication contains raw or unsuitable content")
    return plain, html
