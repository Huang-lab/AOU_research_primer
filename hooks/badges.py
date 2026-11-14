"""Add sticker-style badges under each Reference and Guide page title, derived from the page's own text.

Badges are computed at build time, so they always match the page: the tier and CDR lines the page states,
and how many Pitfall callouts it contains. A page that states nothing gets only the pitfall badge.
"""

import re

TITLE = re.compile(r"^# .+$", re.M)
TIER = re.compile(r"^\*\*Tier:\*\*\s*(.+)$", re.M)
CDR = re.compile(r"^\*\*CDR versions?( validated)?:\*\*\s*(.+)$", re.M)
PITFALL = re.compile(r"^!!! pitfall\b", re.M)


def _tier_label(text):
    t = text.lower()
    if t.startswith("n/a"):
        return "Any tier"
    registered, controlled = "registered" in t, "controlled" in t
    if registered and controlled:
        return "Registered + Controlled"
    if controlled:
        return "Controlled Tier"
    if registered:
        return "Registered Tier"
    return None


def _badge(kind, icon, label):
    return f'<span class="aou-badge aou-badge--{kind}">:{icon}: {label}</span>'


def on_page_markdown(markdown, page, **kwargs):
    if not page.file.src_uri.startswith(("reference/", "guides/")):
        return markdown
    title = TITLE.search(markdown)
    if not title:
        return markdown

    badges = []
    tier = TIER.search(markdown)
    if tier and (label := _tier_label(tier.group(1))):
        badges.append(_badge("tier", "material-shield-account-outline", label))
    cdr = CDR.search(markdown)
    if cdr:
        versions = re.split(r"[(,]", cdr.group(2), maxsplit=1)[0].strip()
        if cdr.group(1):
            badges.append(_badge("validated", "material-check-decagram-outline", f"Validated on {versions}"))
        else:
            badges.append(_badge("cdr", "material-database-outline", f"CDR: {versions}"))
    pitfalls = len(PITFALL.findall(markdown))
    if pitfalls:
        badges.append(_badge("pitfall", "material-alert-outline", f"{pitfalls} pitfall{'s' if pitfalls != 1 else ''}"))

    if not badges:
        return markdown
    block = "\n\n" + " ".join(badges) + "\n{ .aou-badges }\n"
    return markdown[: title.end()] + block + markdown[title.end():]
