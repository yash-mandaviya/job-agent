#!/usr/bin/env python3
"""Generate profile/linkedin.json from resume.tex.

resume.tex is the single source of truth for the LinkedIn-style profile the job
agent consumes. This parser extracts the structured data out of the LaTeX and
writes profile/linkedin.json. Run it after editing/compiling the resume — it
also runs automatically via the git pre-commit hook (.githooks/pre-commit).

Fields that do not appear in the resume (e.g. languages, the editorial headline)
are merged in from profile/linkedin.overrides.json so they survive regeneration.

Pure standard library — no third-party deps — so the git hook can run it with a
bare `python3`.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESUME = ROOT / "profile" / "resume.tex"
OUT = ROOT / "profile" / "linkedin.json"
RESUME_MD = ROOT / "profile" / "resume.md"
OVERRIDES = ROOT / "profile" / "linkedin.overrides.json"

MONTHS = {
    "jan": "01", "feb": "02", "mar": "03", "apr": "04", "may": "05", "jun": "06",
    "jul": "07", "aug": "08", "sep": "09", "oct": "10", "nov": "11", "dec": "12",
}

# Brand styling / canonical company names (org guideline: "FundMore.ai").
COMPANY_NORMALIZE = {"fundmore.ai": "FundMore.ai"}


# ---------------------------------------------------------------------------
# LaTeX helpers
# ---------------------------------------------------------------------------

def strip_comments(text: str) -> list[str]:
    """Return lines with full-line LaTeX comments removed (keeps escaped \\%)."""
    out = []
    for line in text.splitlines():
        if line.lstrip().startswith("%"):
            continue
        out.append(line)
    return out


def clean_tex(s: str) -> str:
    """Turn an inline LaTeX fragment into plain text."""
    if s is None:
        return ""
    # \href{url}{text} -> text
    s = re.sub(r"\\href\{[^}]*\}\s*\{([^}]*)\}", r"\1", s)
    # drop common formatting wrappers but keep their content
    s = re.sub(r"\\(?:textbf|textit|emph|texttt|large|Large|Huge)\b\s*", "", s)
    s = s.replace(r"\\", " ")              # line breaks
    s = re.sub(r"\\hfill\b", " ", s)
    # unescape escaped specials
    for esc, ch in ((r"\#", "#"), (r"\&", "&"), (r"\%", "%"), (r"\_", "_"),
                    (r"\$", "$"), (r"\{", "{"), (r"\}", "}")):
        s = s.replace(esc, ch)
    s = s.replace("~", " ")
    s = s.replace("{", "").replace("}", "")
    s = s.strip().strip(",").strip()
    return re.sub(r"\s+", " ", s).strip()


def norm_company(name: str) -> str:
    return COMPANY_NORMALIZE.get(name.strip().lower(), name.strip())


def date_part(part: str) -> str:
    part = part.strip()
    if part.lower() in ("present", "current", "now"):
        return "present"
    m = re.match(r"([A-Za-z]{3,})\.?\s+(\d{4})", part)
    if m:
        mon = MONTHS.get(m.group(1)[:3].lower())
        if mon:
            return f"{m.group(2)}-{mon}"
    y = re.match(r"(\d{4})$", part)
    if y:
        return y.group(1)
    return part


def parse_dates(raw: str) -> tuple[str, str]:
    raw = clean_tex(raw)
    parts = re.split(r"\s*(?:--|-|–|—|to)\s*", raw, maxsplit=1)
    if len(parts) == 2:
        return date_part(parts[0]), date_part(parts[1])
    return date_part(raw), ""


# ---------------------------------------------------------------------------
# Section helpers
# ---------------------------------------------------------------------------

HEADER_RE = re.compile(r"^\\textbf\{(.+?)\}\s*\\hfill\s*\\textit\{(.+?)\}")
PROJECT_RE = re.compile(
    r"^\\textbf\{\\href\{([^}]*)\}\{([^}]*)\}\}\s*\\hfill\s*\\textit\{(.+?)\}"
)
ITEM_RE = re.compile(r"^\s*\\item\s+(.*)$")


def split_sections(lines: list[str]) -> dict[str, list[str]]:
    """Map UPPERCASE section name -> the lines belonging to it."""
    sections: dict[str, list[str]] = {}
    current = "_HEADER_"
    sections[current] = []
    sec_re = re.compile(r"\\section\*?\{(.+?)\}")
    for line in lines:
        m = sec_re.search(line)
        if m:
            current = clean_tex(m.group(1)).upper()
            sections[current] = []
            continue
        sections[current].append(line)
    return sections


def parse_header(lines: list[str]) -> dict:
    text = "\n".join(lines)
    out: dict = {}
    nm = re.search(r"\\textbf\{\\Huge\s+([^}]+)\}", text)
    if nm:
        out["name"] = clean_tex(nm.group(1))
    for url, label in re.findall(r"\\href\{([^}]*)\}\s*\{([^}]*)\}", text):
        url, label = url.strip(), clean_tex(label)
        if url.startswith("tel:"):
            out["phone"] = label
        elif url.startswith("mailto:"):
            out["email"] = label
        elif "github.com" in url:
            out["github"] = url
        elif "linkedin." in url:
            out["linkedin"] = url
        elif "maps" in url or "place" in url:
            out["location"] = label
    return out


def parse_entries(lines: list[str]) -> list[dict]:
    """Parse WORK EXPERIENCE / EDUCATION style entries."""
    entries: list[dict] = []
    cur: dict | None = None
    awaiting_subhead = False
    in_items = False
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        hm = HEADER_RE.match(line)
        if hm:
            if cur:
                entries.append(cur)
            start, end = parse_dates(hm.group(2))
            cur = {"title": clean_tex(hm.group(1)), "start": start, "end": end,
                   "bullets": [], "coursework": [], "_sub": None}
            awaiting_subhead = True
            in_items = False
            continue
        if cur is None:
            continue
        if line.startswith(r"\begin{itemize}"):
            in_items = True
            awaiting_subhead = False
            continue
        if line.startswith(r"\end{itemize}"):
            in_items = False
            continue
        im = ITEM_RE.match(line)
        if im:
            content = im.group(1)
            cw = re.match(r"\\textbf\{Coursework:\}\s*(.*)", content)
            if cw:
                cur["coursework"] = [clean_tex(c) for c in cw.group(1).split(",") if clean_tex(c)]
            else:
                cur["bullets"].append(clean_tex(content))
            continue
        if awaiting_subhead and not line.startswith("\\") or (awaiting_subhead and line.startswith("\\textbf") is False):
            # the org/school line, e.g. "FundMore.ai, Ottawa, Canada \\"
            sub = clean_tex(line)
            if sub:
                cur["_sub"] = sub
                awaiting_subhead = False
            continue
    if cur:
        entries.append(cur)
    return entries


def parse_projects(lines: list[str]) -> list[dict]:
    projects: list[dict] = []
    cur: dict | None = None
    in_items = False
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        pm = PROJECT_RE.match(line)
        if pm:
            if cur:
                projects.append(cur)
            start, end = parse_dates(pm.group(3))
            cur = {"name": clean_tex(pm.group(2)), "url": pm.group(1).strip(),
                   "start": start, "end": end, "tech_stack": [], "bullets": []}
            in_items = False
            continue
        if cur is None:
            continue
        ts = re.match(r"\\textbf\{Tech Stack:\}\s*(.*)", line)
        if ts:
            stack = clean_tex(ts.group(1))
            cur["tech_stack"] = [s.strip() for s in stack.split(",") if s.strip()]
            continue
        if line.startswith(r"\begin{itemize}"):
            in_items = True
            continue
        if line.startswith(r"\end{itemize}"):
            in_items = False
            continue
        im = ITEM_RE.match(line)
        if im:
            cur["bullets"].append(clean_tex(im.group(1)))
    if cur:
        projects.append(cur)
    return projects


def parse_bullets(lines: list[str]) -> list[str]:
    out = []
    for raw in lines:
        im = ITEM_RE.match(raw.strip())
        if im:
            txt = clean_tex(im.group(1))
            if txt:
                out.append(txt)
    return out


def parse_skills(lines: list[str]) -> list[str]:
    skills: list[str] = []
    for raw in lines:
        im = ITEM_RE.match(raw.strip())
        if not im:
            continue
        content = im.group(1)
        content = re.sub(r"\\textbf\{[^}]*\}", "", content)  # drop category label
        for s in clean_tex(content).split(","):
            s = s.strip()
            if s and s not in skills:
                skills.append(s)
    return skills


def parse_certs(lines: list[str]) -> list[str]:
    out = []
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("\\"):
            continue
        name = re.split(r"\\hfill", line)[0]
        name = clean_tex(name)
        if name:
            out.append(name)
    return out


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------

def build_profile() -> dict:
    text = RESUME.read_text(encoding="utf-8")
    lines = strip_comments(text)
    sections = split_sections(lines)

    header = parse_header(sections.get("_HEADER_", []))

    work = parse_entries(sections.get("WORK EXPERIENCE", []))
    positions = []
    for e in work:
        company, _, location = (e["_sub"] or "").partition(",")
        positions.append({
            "company": norm_company(company),
            "title": e["title"],
            "location": location.strip(),
            "start": e["start"],
            "end": e["end"],
            "description": " ".join(e["bullets"]),
        })

    edu_entries = parse_entries(sections.get("EDUCATION", []))
    education = []
    for e in edu_entries:
        school, _, location = (e["_sub"] or "").partition(",")
        item = {
            "school": school.strip(),
            "degree": e["title"],
            "location": location.strip(),
            "start": e["start"],
            "end": e["end"],
        }
        if e["coursework"]:
            item["coursework"] = e["coursework"]
        education.append(item)

    projects = []
    for p in parse_projects(sections.get("PROJECTS", [])):
        projects.append({
            "name": p["name"],
            "url": p["url"],
            "start": p["start"],
            "end": p["end"],
            "tech_stack": p["tech_stack"],
            "description": " ".join(p["bullets"]),
        })

    skills = parse_skills(sections.get("TECHNICAL SKILLS", []))
    summary = " ".join(parse_bullets(sections.get("PROFESSIONAL SUMMARY", [])))
    honors = parse_bullets(sections.get("ACHIEVEMENTS", []))
    certs = parse_certs(sections.get("CERTIFICATIONS", []))

    # Derived defaults (overridable via linkedin.overrides.json)
    headline = ""
    if positions:
        headline = f"{positions[0]['title']} @ {positions[0]['company']}"
    top_skills = skills[:3]

    profile = {
        "name": header.get("name", ""),
        "headline": headline,
        "location": header.get("location", ""),
        "email": header.get("email", ""),
        "phone": header.get("phone", ""),
        "github": header.get("github", ""),
        "linkedin": header.get("linkedin", ""),
        "summary": summary,
        "top_skills": top_skills,
        "positions": positions,
        "education": education,
        "projects": projects,
        "certifications": certs,
        "honors_awards": honors,
        "skills": skills,
    }
    return profile


def deep_merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def main() -> int:
    if not RESUME.exists():
        print(f"resume not found: {RESUME}", file=sys.stderr)
        return 1
    profile = build_profile()
    if OVERRIDES.exists():
        overrides = json.loads(OVERRIDES.read_text(encoding="utf-8"))
        overrides = {k: v for k, v in overrides.items() if not k.startswith("_")}
        profile = deep_merge(profile, overrides)
    OUT.write_text(json.dumps(profile, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # Also render the human-readable Markdown resume from the same structured
    # data so profile/resume.md stays in sync with resume.tex.
    sys.path.insert(0, str(ROOT))
    from src.resume_render import render_resume_md
    RESUME_MD.write_text(render_resume_md(profile) + "\n", encoding="utf-8")

    print(f"wrote {OUT.relative_to(ROOT)} + {RESUME_MD.relative_to(ROOT)} "
          f"({len(profile['positions'])} positions, {len(profile['education'])} education, "
          f"{len(profile['projects'])} projects, {len(profile['skills'])} skills)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
