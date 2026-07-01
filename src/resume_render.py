"""Render a Markdown resume from the structured linkedin profile dict.

linkedin.json is generated from resume.tex (the single source of truth), so
deriving the resume text from it keeps the candidate profile consistent instead
of relying on a separately-maintained resume.md.

Pure standard library — safe to import from the dependency-light generator
script that runs in the git pre-commit hook.
"""
from __future__ import annotations


def _fmt_range(start: str, end: str) -> str:
    start = start or ""
    end = end or ""
    if start and end:
        return f"{start} – {end}"
    return start or end


def render_resume_md(d: dict) -> str:
    if not d:
        return ""
    lines: list[str] = [f"# {d.get('name', '')}".rstrip()]
    if d.get("headline"):
        lines.append(d["headline"])
    contact = [v for v in (d.get("location"), d.get("email"), d.get("phone"),
                           d.get("github"), d.get("linkedin")) if v]
    if contact:
        lines.append(" · ".join(contact))

    if d.get("summary"):
        lines += ["", "## Summary", "", d["summary"]]

    if d.get("positions"):
        lines += ["", "## Experience"]
        for p in d["positions"]:
            lines.append(f"### {p.get('title', '')} — {p.get('company', '')} ({_fmt_range(p.get('start',''), p.get('end',''))})")
            if p.get("location"):
                lines.append(p["location"])
            if p.get("description"):
                lines.append(p["description"])
            lines.append("")

    if d.get("projects"):
        lines += ["## Projects"]
        for p in d["projects"]:
            lines.append(f"### {p.get('name', '')} ({_fmt_range(p.get('start',''), p.get('end',''))})")
            if p.get("tech_stack"):
                lines.append(f"Tech: {', '.join(p['tech_stack'])}")
            if p.get("description"):
                lines.append(p["description"])
            lines.append("")

    if d.get("education"):
        lines += ["## Education"]
        for e in d["education"]:
            lines.append(f"### {e.get('degree', '')} — {e.get('school', '')} ({_fmt_range(e.get('start',''), e.get('end',''))})")
            if e.get("location"):
                lines.append(e["location"])
            if e.get("coursework"):
                lines.append(f"Coursework: {', '.join(e['coursework'])}")
            lines.append("")

    if d.get("skills"):
        lines += ["## Skills", "", ", ".join(d["skills"]), ""]
    if d.get("certifications"):
        lines += ["## Certifications"] + [f"- {c}" for c in d["certifications"]] + [""]
    if d.get("honors_awards"):
        lines += ["## Honors & Awards"] + [f"- {h}" for h in d["honors_awards"]] + [""]
    if d.get("languages"):
        lines += ["## Languages"] + [f"- {l.get('language','')} — {l.get('level','')}" for l in d["languages"]]

    return "\n".join(lines).strip()
