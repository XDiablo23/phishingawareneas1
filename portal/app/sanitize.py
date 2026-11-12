"""
Minimal allowlist HTML sanitizer for admin-authored lesson / policy content.

Portal admins are trusted (verified against PhishAwareness), but content they
paste is later rendered into other employees' browsers, so - defence in depth -
we allowlist a small set of formatting tags and drop everything else: scripts,
iframes, style, event-handler attributes, and javascript: links. Text is HTML-
escaped. Parsing is done with the stdlib HTMLParser (not regex), so it is not
trivially bypassed by odd markup.
"""
from __future__ import annotations

from html import escape
from html.parser import HTMLParser

_ALLOWED = {
    "h1", "h2", "h3", "h4", "h5", "p", "br", "hr", "ul", "ol", "li",
    "b", "strong", "i", "em", "u", "s", "a", "code", "pre", "blockquote",
    "span", "div", "table", "thead", "tbody", "tr", "td", "th", "caption",
    "small",
}
_SELF_CLOSING = {"br", "hr"}


def _safe_href(v: str | None) -> str | None:
    v = (v or "").strip()
    low = v.lower()
    if low.startswith(("http://", "https://", "mailto:")) or v.startswith("/"):
        return v
    return None


class _Sanitizer(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag not in _ALLOWED:
            return
        if tag in _SELF_CLOSING:
            self.out.append(f"<{tag}>")
            return
        if tag == "a":
            href = None
            for k, v in attrs:
                if k.lower() == "href":
                    href = _safe_href(v)
            if href:
                self.out.append(
                    f'<a href="{escape(href, quote=True)}" '
                    'rel="noopener noreferrer" target="_blank">')
            else:
                self.out.append("<a>")
        else:
            self.out.append(f"<{tag}>")

    def handle_startendtag(self, tag, attrs):
        if tag in _ALLOWED:
            self.out.append(f"<{tag}>")

    def handle_endtag(self, tag):
        if tag in _ALLOWED and tag not in _SELF_CLOSING:
            self.out.append(f"</{tag}>")

    def handle_data(self, data):
        self.out.append(escape(data))


def sanitize_html(html: str, max_len: int = 100_000) -> str:
    if not html:
        return ""
    p = _Sanitizer()
    try:
        p.feed(html[:max_len])
        p.close()
    except Exception:
        return escape(html[:max_len])
    return "".join(p.out)
