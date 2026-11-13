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
    r"\*\*(?=\S)(.+?)(?<=\S)\*\*|__(?=\S)(.+?)(?<=\S)__|"
    r"(?<!\w)\*(?=\S)([^*\n]+?)(?<=\S)\*(?!\w)|"
    r"(?<!\w)_(?=\S)([^_\n]+?)(?<=\S)_(?!\w)"
)
_LABEL = re.compile(
    rf"^(?:#{{1,6}}\s+)?(?:\*\*)?{QualityAgent.SERVICE_SECTION_PATTERN}"
    r"(?:\*\*)?\s*(?::\s*|$)", re.I,
)


def _inline(source: str, depth: int = 0) -> tuple[str, str]:
    if depth > 8:
        raise ValueError("Markdown nesting is too deep")
    plain, rendered = [], []
    end = 0
    for match in _INLINE.finditer(source):
        if match.group(3) is not None and match.start() and source[match.start() - 1] == "!":
            raise ValueError("Inline Markdown images are unsupported")
        literal = source[end:match.start()]
        if QualityAgent._MARKDOWN.search(literal):
            raise ValueError("Unsupported Markdown in publication")
        plain.append(literal)
        rendered.append(escape(literal, quote=False))
        escaped, code, label, url, bold, underbold, italic, underitalic = match.groups()
        if escaped is not None or code is not None:
            text = escaped if escaped is not None else code
            html = escape(text, quote=False)
            if code is not None:
                html = f"<code>{html}</code>"
        else:
            text, html = _inline(label or bold or underbold or italic or underitalic, depth + 1)
            if url is not None:
                if not urlsplit(url).hostname:
                    raise ValueError("Invalid Markdown link")
                html = f'<a href="{escape(url, quote=True)}">{html}</a>'
                # Keep the destination when caption budgeting requires plain text.
                text = f"{text} ({url})"
            else:
                tag = "b" if bold or underbold else "i"
                html = f"<{tag}>{html}</{tag}>"
        plain.append(text)
        rendered.append(html)
        end = match.end()
    literal = source[end:]
    if QualityAgent._MARKDOWN.search(literal):
        raise ValueError("Unsupported Markdown in publication")
    plain.append(literal)
    rendered.append(escape(literal, quote=False))
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
        heading = bool(re.match(r"^#{1,6}\s+", line))
        line = re.sub(r"^#{1,6}\s+", "", line)
        plain, html = _inline(line)
        if heading:
            html = "<b>" + html.replace("<b>", "").replace("</b>", "") + "</b>"
        lines.append((plain, html))
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    if not lines:
        raise ValueError("Empty content")
    # A headline is always bold; inline bold is redundant inside that wrapper.
    plain, html = lines[0]
    lines[0] = (plain, "<b>" + html.replace("<b>", "").replace("</b>", "") + "</b>")
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
