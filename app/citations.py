"""Citation checker for APA 7 and Harvard (Cite Them Right style).

Checks: in-text citation format, reference-list entry format and order, in-text citations with no matching
reference, and references never cited. Heuristic: it reads common author-date patterns, not every edge case.
"""
import re
import unicodedata

REF_HEADING = re.compile(r"^\s*(references?|reference list|bibliography|works cited|sources)\s*:?\s*$", re.I | re.M)
YEAR = r"(?:(?:19|20)\d{2}[a-z]?|n\.d\.?)"
SURNAME = r"(?:(?:van|von|de|du|da|le|la|al|el|di)\s+)?[A-Z][A-Za-z'\u2019\u00C0-\u017F-]+"
# parenthetical group: (...) containing at least one year
PAREN = re.compile(r"\(([^()]*?" + YEAR + r"[^()]*?)\)")
# narrative: Smith (2020), Smith and Jones (2020), Smith et al. (2020), Smith & Jones (2020)
NARR = re.compile(r"\b(" + SURNAME + r"(?:\s*(?:,|and|&)\s*" + SURNAME + r")*(?:\s+et\.?\s*al\.?)?)\s+\((" + YEAR +
                  r")(?:,\s*(?:pp?\.?|page)\s*[\d\u2013-]+)?\)")
STOP_NAMES = {"In", "The", "This", "As", "By", "From", "Since", "During", "Table", "Figure", "Chapter", "Section",
              "Before", "After", "Until", "January", "February", "March", "April", "May", "June", "July", "August",
              "September", "October", "November", "December", "Act", "Report", "Census"}


def _norm(name):
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z]", "", name)


def split_references(text):
    """Return (body_text, body_end, list of (start, end, entry)) using the last references heading."""
    heads = list(REF_HEADING.finditer(text))
    if not heads:
        return text, len(text), []
    h = heads[-1]
    entries = []
    for m in re.finditer(r"[^\n]+", text[h.end():]):
        line = m.group().strip()
        if line:
            a = h.end() + m.start() + (len(m.group()) - len(m.group().lstrip()))
            entries.append((a, a + len(line), line))
    return text[:h.start()], h.start(), entries


def _parse_cite_group(inner):
    """'Smith & Jones, 2020, p. 4; Moyo, 2021' -> list of dicts."""
    out = []
    for part in inner.split(";"):
        part = part.strip()
        part = re.sub(r"^(?:e\.g\.,?|see(?: also)?|cf\.)\s+", "", part, flags=re.I)
        ym = re.search(YEAR, part)
        if not ym:
            continue
        authors = part[:ym.start()].strip().rstrip(",").strip()
        if not authors or not re.match(r"[A-Z]", authors):
            continue
        out.append({"authors": authors, "year": ym.group(0).rstrip("."), "raw": part,
                    "comma": part[:ym.start()].rstrip().endswith(","), "rest": part[ym.end():]})
    return out


def find_in_text(body):
    cites = []
    for m in PAREN.finditer(body):
        for c in _parse_cite_group(m.group(1)):
            c.update(kind="parenthetical", start=m.start(), end=m.end(), text=m.group(0))
            cites.append(c)
    for m in NARR.finditer(body):
        first = m.group(1).split()[0]
        if first in STOP_NAMES:
            continue
        cites.append({"authors": m.group(1), "year": m.group(2).rstrip("."), "kind": "narrative", "start": m.start(),
                      "end": m.end(), "text": m.group(0), "comma": False, "rest": ""})
    # drop parenthetical matches that are really the year part of a narrative citation
    narr_spans = [(c["start"], c["end"]) for c in cites if c["kind"] == "narrative"]
    cites = [c for c in cites if c["kind"] == "narrative" or not any(a <= c["start"] and c["end"] <= b for a, b in narr_spans)]
    return sorted(cites, key=lambda c: c["start"])


def _first_author(authors):
    a = re.split(r"\s*(?:,|&|\band\b|\bet\.?\s*al)", authors)[0].strip()
    return _norm(a.split()[-1] if a.split() and a.split()[0].lower() not in ("van", "von", "de", "du", "da") else a)


def _n_authors(authors):
    if re.search(r"et\.?\s*al", authors):
        return 3
    return len([x for x in re.split(r"\s*(?:,|&|\band\b)\s*", authors) if x.strip()])


def parse_reference(entry):
    m = re.search(r"\(?(" + YEAR + r")\)?", entry)
    year = m.group(1).rstrip(".") if m else None
    lead = entry[:m.start()] if m else entry
    surname = re.match(r"\s*((?:(?:van|von|de|du|da|le|la)\s+)?[A-Z][A-Za-z'\u2019\u00C0-\u017F-]+)", lead)
    return {"first": _norm(surname.group(1).split()[-1]) if surname else None, "year": year, "lead": lead}


def guess_style(text, cites, refs):
    score = 0
    for c in cites:
        if c["kind"] == "parenthetical" and "&" in c["authors"]:
            score += 1
        if c["kind"] == "parenthetical" and re.search(r"\band\b", c["authors"]):
            score -= 1
    for _, _, e in refs:
        if re.search(r"\(" + YEAR + r"\)\.", e):
            score += 1
        elif re.search(r"\(" + YEAR + r"\)\s+[A-Z'\u2018\"]", e):
            score -= 1
        if "Available at:" in e or "[Online]" in e:
            score -= 2
    return "apa" if score >= 0 else "harvard"


def check(text, style="auto"):
    """Return (issues, info). issues use the same shape as feedback issues (without labels)."""
    body, body_end, refs = split_references(text)
    cites = find_in_text(body)
    style = style if style in ("apa", "harvard") else guess_style(text, cites, refs)
    name = "APA 7" if style == "apa" else "Harvard"
    issues = []

    def add(a, b, title, msg, sugg, sev="warning"):
        issues.append({"start": a, "end": b, "category": "citation", "severity": sev, "title": title,
                       "message": msg, "suggestion": sugg, "replacements": [], "rule": f"citations-{style}"})

    # ---- in-text format
    for c in cites:
        au, raw = c["authors"], c["text"]
        if re.search(r"et\.\s*al|et al(?!\.)", au):
            add(c["start"], c["end"], "Write 'et al.'", f"'{raw}': the abbreviation is 'et al.' (no full stop after 'et', one after 'al').",
                "Use 'et al.'")
        if c["kind"] == "parenthetical":
            if style == "apa":
                if re.search(r"\band\b", au):
                    add(c["start"], c["end"], "APA: use '&' inside brackets", f"'{raw}': APA 7 uses '&' between authors in parenthetical citations.",
                        "e.g. (Moyo & Banda, 2021)")
                if not c["comma"]:
                    add(c["start"], c["end"], "APA: comma before the year", f"'{raw}': APA 7 puts a comma between author and year.",
                        "e.g. (Moyo, 2021)")
            else:
                if "&" in au:
                    add(c["start"], c["end"], "Harvard: use 'and'", f"'{raw}': Harvard (Cite Them Right) writes 'and' between authors.",
                        "e.g. (Moyo and Banda, 2021)")
            if re.search(r",\s*(?:page|pg\.?)\s*\d", c["rest"]) or re.search(r",\s*p\s+\d", c["rest"]):
                add(c["start"], c["end"], "Page number format", f"'{raw}': write pages as 'p. 4' or 'pp. 4\u20136'.", "e.g. (Moyo, 2021, p. 4)")
        else:
            if "&" in au:
                add(c["start"], c["end"], "Use 'and' in running text", f"'{raw}': in narrative citations both APA and Harvard write 'and', not '&'.",
                    "e.g. Moyo and Banda (2021)")
        if style == "apa" and _n_authors(au) >= 3 and not re.search(r"et\.?\s*al", au):
            add(c["start"], c["end"], "APA: use 'et al.' for 3+ authors", f"'{raw}': APA 7 shortens three or more authors to the first author + 'et al.' from the first citation.",
                "e.g. (Moyo et al., 2021)")
        if style == "harvard" and _n_authors(au) >= 4 and not re.search(r"et\.?\s*al", au):
            add(c["start"], c["end"], "Harvard: use 'et al.' for 4+ authors", f"'{raw}': Harvard shortens four or more authors to 'et al.'.",
                "e.g. (Moyo et al., 2021)")

    # ---- reference list
    parsed = []
    for a, b, e in refs:
        p = parse_reference(e)
        p.update(start=a, end=b, entry=e)
        parsed.append(p)
        if not p["year"]:
            add(a, b, "Reference has no year", "No publication year found. Use 'n.d.' if there is none.", "Add (2021) or (n.d.)")
            continue
        if not re.match(r"\s*[A-Z][A-Za-z'\u2019-]+(?:\s+[A-Z][A-Za-z'\u2019-]+)*,\s*(?:[A-Z]\.|[A-Z][a-z]+)", e) and not re.match(r"\s*[A-Z][\w&.,' -]{2,80}\.?\s*\(", e):
            add(a, b, "Author format", "Start with the author's surname, then initials (e.g. 'Moyo, T.').", "Moyo, T. (2021) ...", "info")
        if style == "apa":
            if not re.search(r"\(" + YEAR + r"\)\.", e):
                add(a, b, "APA: (Year). after authors", "APA 7 puts the year in brackets followed by a full stop: 'Moyo, T. (2021). Title...'.",
                    "Moyo, T. (2021). Title. Publisher.")
            if re.search(r"\bdoi:\s*10\.|\bDOI:\s*10\.|(?<!https://)(?<!http://)(?<!doi\.org/)\b10\.\d{4,}/", e) and "doi.org/" not in e:
                add(a, b, "APA: DOI as a link", "APA 7 writes DOIs as https://doi.org/10.xxxx.", "https://doi.org/10....", "info")
            if re.search(r"Available at:|\[Online\]|Accessed", e):
                add(a, b, "APA: no 'Available at'", "'Available at:' and access dates are Harvard conventions; APA 7 just gives the URL.", "Remove 'Available at:'", "info")
            if re.search(r"[A-Z]\.\s*(?:and)\s+[A-Z][a-z]+,", e):
                add(a, b, "APA: '&' before last author", "APA 7 reference lists use ', &' before the final author.", "Moyo, T., & Banda, R. (2021).", "info")
        else:
            if re.search(r"\(" + YEAR + r"\)\.", e):
                add(a, b, "Harvard: no full stop after (Year)", "Cite Them Right Harvard writes 'Moyo, T. (2021) Title...' with no full stop after the year.",
                    "Moyo, T. (2021) Title. Place: Publisher.", "info")
            if re.search(r"https?://", e) and "Available at" not in e and "doi.org" not in e:
                add(a, b, "Harvard: 'Available at:' and access date", "Web sources in Harvard need 'Available at: URL (Accessed: date)'.",
                    "Available at: https://... (Accessed: 5 May 2026).", "info")
            if re.search(r",\s*&\s*[A-Z]", e):
                add(a, b, "Harvard: use 'and'", "Harvard reference lists use 'and' between the last two authors, not '&'.", "Moyo, T. and Banda, R. (2021)", "info")
    firsts = [p["first"] for p in parsed if p["first"]]
    if firsts and firsts != sorted(firsts):
        a, b = parsed[0]["start"], parsed[0]["end"]
        add(a, b, "Reference list not in A\u2013Z order", "Both APA and Harvard list references alphabetically by first author's surname.",
            "Sort the list by surname.")

    # ---- cross-check
    keys = {(p["first"], p["year"]) for p in parsed if p["first"] and p["year"]}
    if refs:
        for c in cites:
            k = (_first_author(c["authors"]), c["year"])
            if k not in keys:
                near = [p for p in parsed if p["first"] == k[0]]
                hint = f" A reference by this author has year {near[0]['year']}." if near else ""
                add(c["start"], c["end"], "Citation not in reference list", f"'{c['text']}' has no matching entry in the reference list.{hint}",
                    "Add the full reference, or fix the author/year so they match.")
        cited = {(_first_author(c["authors"]), c["year"]) for c in cites}
        for p in parsed:
            if p["first"] and p["year"] and (p["first"], p["year"]) not in cited:
                add(p["start"], p["end"], "Reference never cited", "This entry is not cited anywhere in the text.",
                    "Cite it in the text or remove it from the list.", "info")
    elif cites:
        a = cites[0]
        add(a["start"], a["end"], "No reference list found", f"{len(cites)} in-text citation(s) but no 'References' heading.",
            "Add a reference list under a heading called 'References' (APA) or 'Reference list' (Harvard).")
    info = {"style": style, "style_name": name, "in_text": len(cites), "references": len(refs)}
    return issues, info
