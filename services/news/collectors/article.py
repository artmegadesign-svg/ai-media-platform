"""Conservative plain-text extraction from an already fetched official page.

No network, scripts, CSS execution or image permission decisions. Source text
remains untrusted evidence for the existing ContentPipeline, never instructions.
"""

from dataclasses import dataclass, field
from html import unescape
from html.parser import HTMLParser
import re


MAX_CONTENT_CHARS = 12_000
_MAX_HTML_CHARS = 2 * 1024 * 1024  # Same upper bound as the collector response.
_BLOCKS = {"p", "h1", "h2", "h3", "h4", "li", "blockquote"}
_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
_SKIP = {
    "script", "style", "noscript", "template", "svg", "canvas", "iframe",
    "nav", "footer", "header", "aside", "form", "button", "dialog",
}
_CHROME = re.compile(
    r"(?:^|[\W_])(?:nav|navigation|menu|footer|sidebar|related|recommended|"
    r"recommendations|cookie|cookies|consent|subscribe|subscription|newsletter|"
    r"advert|advertisement|advertising|ad|ads|promo|social|share|breadcrumb|"
    r"hidden|sr-only|visually-hidden|"
    r"modal|paywall|instructions?|prompt)(?:$|[\W_])", re.I,
)
_BOILERPLATE = re.compile(
    r"^(?:subscribe\b|sign up\b|we use cookies\b|accept (?:all )?cookies\b|"
    r"manage (?:cookies|consent)\b|all rights reserved\b|read more\s*$|"
    r"related (?:articles|stories)\s*$)", re.I,
)


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


@dataclass
class _Node:
    tag: str
    attrs: dict[str, str | None] = field(default_factory=dict)
    children: list = field(default_factory=list)
    closed: bool = False

    def excluded(self) -> bool:
        attrs = self.attrs
        style = re.sub(r"\s+", "", attrs.get("style") or "").lower()
        return (
            self.tag in _SKIP or "hidden" in attrs or "inert" in attrs
            or (self.tag == "details" and "open" not in attrs)
            or (attrs.get("aria-hidden") or "").lower() == "true"
            or "display:none" in style or "visibility:hidden" in style
            or (attrs.get("role") or "").lower() in {
                "navigation", "contentinfo", "complementary", "dialog", "banner",
            }
            or bool(_CHROME.search(f"{attrs.get('id') or ''} {attrs.get('class') or ''}"))
        )


class _Parser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _Node("root")
        self.stack = [self.root]
        self.count = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.rsplit(":", 1)[-1]  # Atom XHTML fragments may carry namespaces.
        # Common optional end tags in HTML; do not merge adjacent paragraphs.
        if tag in {"p", "li"} and self.stack[-1].tag == tag:
            self.handle_endtag(tag)
        self.count += 1
        if self.count > 30_000 or len(self.stack) > 256:
            raise ValueError("Article markup exceeds extraction budget")
        node = _Node(tag, dict(attrs))
        self.stack[-1].children.append(node)
        if tag not in _VOID:
            self.stack.append(node)
        else:
            node.closed = True

    def handle_startendtag(self, tag, attrs):
        tag = tag.rsplit(":", 1)[-1]
        self.handle_starttag(tag, attrs)
        if tag not in _VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        tag = tag.rsplit(":", 1)[-1]
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                self.stack[index].closed = True
                del self.stack[index:]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def _parse(html: str) -> _Node:
    if len(html) > _MAX_HTML_CHARS:
        raise ValueError("Article HTML exceeds extraction budget")
    parser = _Parser()
    parser.feed(html)
    parser.close()
    return parser.root


def _nodes(root):
    pending = [root]
    while pending:
        node = pending.pop()
        if node.excluded():
            continue
        yield node
        pending.extend(child for child in reversed(node.children) if isinstance(child, _Node))


def _text(root):
    parts = []
    pending = [root]
    while pending:
        node = pending.pop()
        if isinstance(node, str):
            parts.append(node)
        elif not node.excluded():
            # Separate structural blocks, preserve inline spelling/punctuation.
            if node.tag in _BLOCKS or node.tag in {"br", "div"}:
                parts.append(" ")
            if node.tag in _BLOCKS or node.tag == "div":
                pending.append(" ")
            pending.extend(reversed(node.children))
    return _clean("".join(parts))


def _blocks(root, *, loose=False):
    pending = [root]
    fragments = []
    while pending:
        node = pending.pop()
        if isinstance(node, str):
            if loose:
                fragments.append(node)
            continue
        if node.excluded():
            continue
        if node.tag in _BLOCKS:
            if fragments:
                yield "", _clean("".join(fragments))
                fragments.clear()
            yield node.tag, _text(node)
        else:
            if loose and node.tag in {"div", "br"}:
                fragments.append(" ")
                pending.append(" ")
            pending.extend(reversed(node.children))
    if fragments:
        yield "", _clean("".join(fragments))


def clean_rss(fragment: str, title: str = "") -> str | None:
    """Clean markup/hidden chrome even when no usable release page is available."""
    try:
        root = _parse(unescape(fragment))
        text = _unique_text(_blocks(root, loose=True), title)
        if len(text) > MAX_CONTENT_CHARS:
            text = text[:MAX_CONTENT_CHARS].rsplit(" ", 1)[0]
        return text or None
    except ValueError:
        return None


def _unique_text(blocks, title):
    seen = {_clean(title).casefold()}
    result = []
    for _, text in blocks:
        key = text.casefold()
        if not text or key in seen or _BOILERPLATE.search(text):
            continue
        seen.add(key)
        result.append(text)
    return "\n\n".join(result)


def extract_article(html: str, title: str) -> str | None:
    """Require a single explicit content region; never scrape the whole body."""
    try:
        nodes = list(_nodes(_parse(html)))
        articles = [node for node in nodes if node.tag == "article"]
        mains = [node for node in nodes if node.tag == "main"]
        if len(articles) > 1:
            return None  # A listing, not one reliably identified article.
        bodies = [node for node in nodes
                  if "articleBody" in (node.attrs.get("itemprop") or "").split()]
        regions = articles or mains or bodies
        if len(regions) != 1 or not regions[0].closed:
            return None
        region = regions[0]
        bodies = [node for node in _nodes(region)
                  if "articleBody" in (node.attrs.get("itemprop") or "").split()]
        if len(bodies) > 1:
            return None
        region = bodies[0] if bodies else region
        if not region.closed:
            return None
        blocks = list(_blocks(region))
        if region.tag == "main" and not any(
            tag == "h1" and text.casefold() == _clean(title).casefold()
            for tag, text in blocks
        ):
            return None  # Generic main layouts are not necessarily article bodies.
        # Headings/cards alone do not establish substantive article text.
        if not any(tag in {"p", "blockquote"} and len(text) >= 40 for tag, text in blocks):
            return None
        text = _unique_text(blocks, title)
        selected = []
        used = 0
        for block in text.split("\n\n"):
            size = len(block) + (2 if selected else 0)
            if used + size > MAX_CONTENT_CHARS:
                break  # Retain complete blocks, never a cut number/sentence.
            selected.append(block)
            used += size
        return "\n\n".join(selected) if used >= 80 else None
    except ValueError:
        return None
