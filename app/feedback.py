"""Rule-based writing feedback: style rules + built-in checks + readability.

Every issue: {start, end, category, severity, title, message, suggestion, replacements, rule}
Offsets are character offsets into the text that was analysed.
This is an editing aid. It does not estimate whether text was written by AI.
"""
import re
import statistics
from collections import Counter, defaultdict

from . import rules as R
from .textutils import split_sentences, paragraphs, words, count_syllables, WORD_RE
from . import citations as C

CATEGORY_LABELS = {
    "ai_stock": "Stock phrase",
    "wordy": "Wordy",
    "filler": "Filler",
    "cliche": "Cliché",
    "repetition": "Repetition",
    "rhythm": "Sentence rhythm",
    "passive": "Passive voice",
    "long": "Long sentence",
    "structure": "Structure",
    "style": "Style",
    "custom": "Custom rule",
    "flow": "Paragraph flow",
    "conclusion": "Conclusion",
    "citation": "Citations",
}
CATEGORY_HELP = {
    "flow": "How paragraphs are built and linked: each should open with a topic sentence, develop one idea, and connect to the one before.",
    "conclusion": "Whether the text ends by drawing its points together instead of stopping or adding new material.",
    "citation": "In-text citations and the reference list, checked against APA 7 or Harvard (Cite Them Right). Heuristic: confirm against your style guide.",
}
OPENERS_DANGLING = re.compile(r"^(?:this|these|it|they|also|and|but|however|moreover|furthermore|additionally|for example|"
                              r"for instance|such|in addition|similarly|likewise|then)\b", re.I)
TRANSITION_START = re.compile(r"^(?:however|moreover|furthermore|additionally|in addition|similarly|likewise|by contrast|"
                              r"in contrast|on the other hand|also|another|next|finally|first|second|third|then|as a result|"
                              r"therefore|thus|consequently|in turn|beyond|despite|although|while|yet|because|for example|"
                              r"for instance|this|these|such|in conclusion|to conclude|overall|in summary|to sum up)\b", re.I)
CONCLUSION_MARK = re.compile(r"\b(?:in conclusion|to conclude|overall|in summary|to sum up|in short|taken together|"
                             r"ultimately|therefore|thus|this (?:essay|paper|report|study) (?:has )?(?:shown|argued|found))\b", re.I)

STOP = set("""a an the and or but if then so of to in on at by for with from as is are was were be been being it its
this that these those there here which who whom whose what when where why how i you he she we they me him her us them my
your his our their not no nor can could will would shall should may might must do does did have has had than too very
also just into about over under more most less such only own same other some any each both all few many much one two""".split())

IRREGULAR_PP = set("""been born begun bitten blown broken brought built bought caught chosen come cut dealt done drawn driven
eaten fallen felt fought found forgotten forgiven frozen given gone grown held hidden hit hurt kept known laid led left lent
let lost made meant met paid put read ridden risen run said seen sold sent set shaken shown shut sung sat slept spoken spent
stood stolen struck sworn taken taught torn told thought thrown understood woken worn won written""".split())
PASSIVE_RE = re.compile(
    r"\b(am|is|are|was|were|be|been|being|get|gets|got|gotten)\s+(?:(?:not|also|often|usually|widely|then|being|generally|still|commonly|largely|typically)\s+){0,2}([a-z]+)\b",
    re.IGNORECASE)
TRANSITIONS = {"furthermore", "moreover", "additionally", "however", "therefore", "thus", "consequently",
               "overall", "ultimately", "notably", "importantly", "hence", "in addition", "in conclusion"}


def _is_participle(w):
    w = w.lower()
    if w in IRREGULAR_PP:
        return True
    return len(w) > 3 and w.endswith("ed") and w not in {"need", "feed", "seed", "speed", "bed", "red", "shed", "led", "indeed", "hundred"}


def readability(text):
    sents = split_sentences(text)
    ws = words(text)
    nw, ns = len(ws), max(1, len(sents))
    if nw == 0:
        return {"words": 0, "sentences": 0}
    syl = [count_syllables(w) for w in ws]
    nsyl = sum(syl)
    complex_w = sum(1 for s, w in zip(syl, ws) if s >= 3 and not w[:1].isupper())
    lens = [len(words(s)) for _, _, s in sents] or [nw]
    fre = 206.835 - 1.015 * (nw / ns) - 84.6 * (nsyl / nw)
    fk = 0.39 * (nw / ns) + 11.8 * (nsyl / nw) - 15.59
    fog = 0.4 * ((nw / ns) + 100 * complex_w / nw)
    lower = [w.lower() for w in ws]
    # MATTR-50: moving-average type-token ratio (length-robust lexical variety)
    win = 50
    if len(lower) > win:
        ttrs = [len(set(lower[i:i + win])) / win for i in range(0, len(lower) - win + 1, 5)]
        mattr = sum(ttrs) / len(ttrs)
    else:
        mattr = len(set(lower)) / len(lower)
    mean = statistics.mean(lens)
    sd = statistics.pstdev(lens) if len(lens) > 1 else 0.0
    return {
        "words": nw, "sentences": len(sents), "paragraphs": len(paragraphs(text)),
        "avg_sentence_words": round(mean, 1), "sentence_length_sd": round(sd, 1),
        "sentence_length_variation": round(sd / mean, 2) if mean else 0,
        "shortest_sentence": min(lens), "longest_sentence": max(lens),
        "avg_word_syllables": round(nsyl / nw, 2),
        "flesch_reading_ease": round(fre, 1), "flesch_kincaid_grade": round(fk, 1),
        "gunning_fog": round(fog, 1), "lexical_variety": round(mattr, 2),
        "reading_time_min": round(nw / 230, 1),
        "reading_ease_label": _ease_label(fre),
    }


def _ease_label(fre):
    for lim, lab in ((80, "Very easy"), (70, "Easy"), (60, "Plain English"), (50, "Fairly difficult"),
                     (30, "Difficult (typical academic)"), (-999, "Very difficult")):
        if fre >= lim:
            return lab


def _stems(s):
    return {w.lower()[:5] for w in words(s) if len(w) > 3 and w.lower() not in STOP}


def _is_heading(p):
    return len(words(p)) < 12 and not p.rstrip().endswith((".", "!", "?", ":", ";"))


def flow_checks(text, body_end, add):
    paras = [(a, b, p) for a, b, p in paragraphs(text[:body_end]) if not _is_heading(p)]
    if not paras:
        return
    info = []
    for idx, (a, b, p) in enumerate(paras):
        ss = split_sentences(p)
        nw = len(words(p))
        if nw > 200 or len(ss) > 9:
            add(a, min(b, a + 80), "flow", f"Paragraph too long ({nw} words, {len(ss)} sentences)",
                "Long paragraphs usually hold more than one idea, so the reader loses the thread.",
                "Split it where the topic shifts; aim for 4-8 sentences.", severity="warning", rule="builtin-flow")
        elif len(paras) >= 3 and len(ss) < 2 and nw < 40 and 0 < idx < len(paras) - 1:
            add(a, b, "flow", "Paragraph too short",
                "A one-sentence paragraph in the middle of a text rarely develops its point.",
                "Merge it with a neighbouring paragraph or add support (evidence, example, explanation).", rule="builtin-flow")
        if len(ss) >= 3:
            first = ss[0][2]
            rest = " ".join(x[2] for x in ss[1:])
            reason = None
            if OPENERS_DANGLING.match(first):
                reason = f"it opens with '{first.split()[0].rstrip(',')}', which points back instead of stating the paragraph's point"
            elif not (_stems(first) & _stems(rest)):
                reason = "its first sentence shares no key words with the rest of the paragraph"
            elif re.search(r"\d", first) and re.search(r"\((?:[^()]*\d{4})\)", first) and idx > 0:
                reason = "it opens with data and a citation rather than a claim"
            if reason:
                add(a + ss[0][0], a + ss[0][1], "flow", "Missing topic sentence?",
                    f"This paragraph may lack a clear topic sentence: {reason}.",
                    "Start with one sentence that states what the paragraph argues, then support it.", rule="builtin-flow")
        info.append((a, b, p, ss))
    for (a1, b1, p1, s1), (a2, b2, p2, s2) in zip(info, info[1:]):
        if len(s1) < 2 or len(s2) < 2:
            continue
        first2 = s2[0][2]
        if TRANSITION_START.match(first2):
            continue
        prev = " ".join(x[2] for x in s1[-2:])
        if not (_stems(prev) & _stems(first2)):
            add(a2 + s2[0][0], a2 + s2[0][1], "flow", "Abrupt transition",
                "This paragraph starts a new topic with no link to the previous one.",
                "Add a bridging phrase or sentence that connects it to the paragraph before.", rule="builtin-flow")
    total = len(words(text[:body_end]))
    if len(info) >= 3 and total >= 100:
        a, b, p, ss = info[-1]
        intro = " ".join(x[2] for x in info[0][3])
        overlap = len(_stems(p) & _stems(intro))
        marked = bool(CONCLUSION_MARK.search(p))
        if len(words(p)) < 20 or len(ss) < 2:
            add(a, b, "conclusion", "Weak conclusion: very short",
                "The final paragraph is only one short sentence, so the main points are not drawn together.",
                "Sum up the main argument in 2-4 sentences and say why it matters.", severity="warning", rule="builtin-conclusion")
        elif p.rstrip().endswith("?"):
            add(a, b, "conclusion", "Ends on a question", "Ending on a question can feel unresolved in academic writing.",
                "Close with your answer or main finding.", rule="builtin-conclusion")
        elif not marked and overlap < 2:
            add(a, b, "conclusion", "Missing conclusion?",
                "The last paragraph reads like another body paragraph: no summing-up signal and little link back to the opening.",
                "Add a closing paragraph that restates the main point in new words and draws the threads together.",
                severity="warning", rule="builtin-conclusion")
        elif re.search(r"\((?:[^()]*\d{4})\)", p) and not marked:
            add(a, b, "conclusion", "New evidence in the conclusion",
                "The last paragraph introduces cited material instead of concluding.",
                "Move new evidence into the body; use the end to draw conclusions.", rule="builtin-conclusion")


def analyse(text, rules=None, citation_style="auto"):
    rules = R.load_rules() if rules is None else rules
    issues = []
    _, body_end, _refs = C.split_references(text)
    sents = [x for x in split_sentences(text) if x[0] < body_end]

    def add(start, end, category, title, message, suggestion="", replacements=None, severity="info", rule=None):
        issues.append({"start": start, "end": end, "category": category,
                       "category_label": CATEGORY_LABELS.get(category, category.title()),
                       "severity": severity, "title": title, "message": message,
                       "suggestion": suggestion, "replacements": replacements or [], "rule": rule})

    # 1. replace rules -> phrase issues with suggested replacements
    for r in R.active(rules, "feedback", "replace"):
        rx = R.compiled_replace(r)
        for m in rx.finditer(text):
            alts = [a for a in r["alternatives"]]
            sugg = "Delete it." if alts == [""] else "Try: " + ", ".join(f"'{a}'" if a else "(delete)" for a in alts)
            add(m.start(), m.end(), r.get("category", "custom"), f"'{m.group(0).strip()}'",
                r.get("message") or r.get("description") or "Matches a style rule.", sugg,
                [R._match_case(m.group(0), a) for a in alts], "warning", r["id"])
    # 2. ban rules
    for r in R.active(rules, "feedback", "ban"):
        for ph in r["phrases"]:
            for m in R.ban_regex(ph).finditer(text):
                add(m.start(), m.end(), r.get("category", "custom"), f"'{m.group(0)}'",
                    r.get("message", "Banned word or phrase."), "Rephrase without it.", [""], "warning", r["id"])
    # 3. custom checks
    for r in R.active(rules, "feedback", "check"):
        flags = 0 if r.get("case_sensitive") else re.IGNORECASE
        ms = list(re.finditer(r["pattern"], text, flags))
        if len(ms) >= int(r.get("min_count", 1)):
            for m in ms:
                add(m.start(), m.end(), r.get("category", "custom"), r.get("name", "Custom check"),
                    r.get("message", "Matches a custom check."), r.get("suggestion", ""), None, "info", r["id"])

    # 4. sentence length (rule-driven thresholds)
    lr = R.length_rule(rules, "feedback")
    lens = [len(words(s)) for _, _, s in sents]
    if lr["enabled"]:
        for (a, b, s), n in zip(sents, lens):
            if n > lr["max_words"]:
                add(a, b, "long", f"Very long sentence ({n} words)",
                    f"Over {lr['max_words']} words; readers lose the thread.",
                    "Split it at a conjunction or semicolon into two or three sentences.", severity="warning", rule="sentence-length")
            elif n > lr["warn_words"]:
                add(a, b, "long", f"Long sentence ({n} words)", f"Over {lr['warn_words']} words.",
                    "Consider splitting it or cutting a clause.", rule="sentence-length")
        # uniform rhythm: whole text and runs
        if len(lens) >= 5:
            mean = statistics.mean(lens)
            cv = statistics.pstdev(lens) / mean if mean else 0
            if cv < lr["min_variation"]:
                add(sents[0][0], sents[-1][1], "rhythm", "Sentence lengths are very uniform",
                    f"Most sentences are about {round(mean)} words (variation {cv:.2f}, target ≥ {lr['min_variation']}). "
                    "Evenly sized sentences make prose feel flat and mechanical.",
                    "Mix in a few short sentences for emphasis and let one or two run longer.", severity="warning", rule="sentence-length")
        run = 1
        for i in range(1, len(lens)):
            same_para = "\n" not in text[sents[i - 1][1]:sents[i][0]]
            if same_para and abs(lens[i] - lens[i - 1]) <= 3 and lens[i] >= 8:
                run += 1
                if run == 4:
                    add(sents[i - 3][0], sents[i][1], "rhythm", "Four similar-length sentences in a row",
                        "A run of sentences of the same length and shape reads monotonously.",
                        "Combine two of them, or add a short sentence.", rule="sentence-length")
            else:
                run = 1

    # 5. passive voice
    passive_sents = 0
    for a, b, s in sents:
        found = False
        for m in PASSIVE_RE.finditer(s):
            if _is_participle(m.group(2)):
                found = True
                add(a + m.start(), a + m.end(), "passive", "Passive voice",
                    "Passive constructions hide who did what and add words.",
                    "If the actor matters, name it: 'the team measured X' instead of 'X was measured'.", rule="builtin-passive")
        passive_sents += found
    if sents and passive_sents / len(sents) > 0.3 and len(sents) >= 4:
        add(sents[0][0], sents[0][1], "passive", "Heavy use of passive voice",
            f"{passive_sents} of {len(sents)} sentences use the passive.",
            "Rewrite some in the active voice; keep passive where the actor is unknown or unimportant.",
            severity="warning", rule="builtin-passive")

    # 6. repetition: openers, words, phrases
    openers = defaultdict(list)
    for a, b, s in sents:
        w = words(s)
        if w:
            openers[w[0].lower()].append((a, a + len(w[0]) + s.find(w[0])))
    for op, spots in openers.items():
        if len(spots) >= 3 and len(spots) / max(1, len(sents)) >= 0.25 and op not in {"i"}:
            for a, e in spots:
                add(a, e, "repetition", f"Many sentences start with '{op.title()}'",
                    f"{len(spots)} sentences open the same way.", "Vary how sentences begin.", rule="builtin-repetition")
    trans = [(a, s) for a, b, s in sents if s.split(",")[0].strip().lower() in TRANSITIONS and "," in s[:20]]
    if len(trans) >= 3 and len(trans) / max(1, len(sents)) > 0.2:
        for a, s in trans:
            w = s.split(",")[0]
            add(a, a + len(w), "structure", "Connective overuse",
                f"{len(trans)} sentences open with a connective like 'Moreover,' or 'Additionally,'.",
                "Let the logic carry the link; drop most of these.", rule="builtin-structure")
    toks = [(m.group(0).lower(), m.start(), m.end()) for m in WORD_RE.finditer(text)]
    win = 60
    flagged = set()
    for i, (w, s0, e0) in enumerate(toks):
        if w in STOP or len(w) < 5 or w in flagged:
            continue
        near = [t for t in toks[i + 1:i + win] if t[0] == w]
        if len(near) >= 2:
            flagged.add(w)
            for t in [(w, s0, e0)] + near:
                add(t[1], t[2], "repetition", f"'{w}' repeated",
                    f"'{w}' appears {len(near) + 1} times within about {win} words.",
                    "Use a pronoun, a synonym, or restructure.", rule="builtin-repetition")
    ngrams = Counter()
    pos = defaultdict(list)
    for i in range(len(toks) - 2):
        g = tuple(t[0] for t in toks[i:i + 3])
        if sum(1 for x in g if x not in STOP) >= 2:
            ngrams[g] += 1
            pos[g].append((toks[i][1], toks[i + 2][2]))
    for g, c in ngrams.items():
        if c >= 3:
            for a, e in pos[g]:
                add(a, e, "repetition", f"Repeated phrase '{' '.join(g)}'", f"Used {c} times.",
                    "Say it once, then refer back to it more briefly.", rule="builtin-repetition")

    # 7. structure
    paras = paragraphs(text)
    if len(paras) == 1 and len(words(text)) > 250:
        add(0, min(len(text), 60), "structure", "No paragraph breaks",
            "The whole text is a single paragraph.", "Break it into paragraphs of 3-6 sentences.", severity="warning", rule="builtin-structure")
    singles = [p for p in paras if len(split_sentences(p[2])) == 1 and len(words(p[2])) > 8]
    if len(paras) >= 4 and len(singles) / len(paras) > 0.5:
        add(singles[0][0], singles[0][1], "structure", "Many one-sentence paragraphs",
            f"{len(singles)} of {len(paras)} paragraphs are a single sentence.",
            "Group related sentences and develop each point.", rule="builtin-structure")
    triads = list(re.finditer(r"\b\w+(?: \w+)?, \w+(?: \w+)?,? and \w+(?: \w+)?\b", text))
    if len(triads) >= 4 and len(triads) / max(1, len(sents)) > 0.3:
        for m in triads:
            add(m.start(), m.end(), "style", "Lists of three everywhere",
                "Frequent 'X, Y and Z' triplets make the writing sound formulaic.",
                "Keep the ones that matter; give two items or one strong example elsewhere.", rule="builtin-structure")

    # contractions rule in feedback
    for r in R.active(rules, "feedback", "contractions"):
        if r.get("mode") == "avoid":
            for m in re.finditer(r"\b[A-Za-z]+[\u2019'](?:t|re|ll|ve|m|d)\b", text):
                add(m.start(), m.end(), "style", "Contraction", "Your rules say to avoid contractions.",
                    "Write it out in full.", [R.expand(m.group(0))], rule=r["id"])

    flow_checks(text, body_end, add)
    cit_info = {"style": None, "in_text": 0, "references": 0}
    if citation_style != "off":
        cit_issues, cit_info = C.check(text, citation_style)
        for i in cit_issues:
            add(i["start"], i["end"], "citation", i["title"], i["message"], i["suggestion"], severity=i["severity"], rule=i["rule"])
    # style checks should not fire inside the reference list
    issues = [i for i in issues if i["start"] < body_end or i["category"] == "citation"]
    issues.sort(key=lambda x: (x["start"], -x["end"]))
    stats = readability(text[:body_end])
    counts = Counter(i["category"] for i in issues)
    summary = _summary(stats, counts)
    if cit_info.get("in_text") or cit_info.get("references"):
        summary.append(f"Citations checked as {cit_info['style_name']}: {cit_info['in_text']} in-text, "
                       f"{cit_info['references']} reference(s), {counts.get('citation', 0)} issue(s).")
    return {"issues": issues, "stats": stats, "counts": dict(counts), "summary": summary,
            "categories": CATEGORY_LABELS, "category_help": CATEGORY_HELP, "citations": cit_info,
            "note": "Editing aid: these are style suggestions, not a judgement on who wrote the text."}


def _summary(st, counts):
    out = []
    if not st.get("words"):
        return ["Paste some text to get feedback."]
    out.append(f"Reading ease {st['flesch_reading_ease']} ({st['reading_ease_label']}), grade level {st['flesch_kincaid_grade']}.")
    if st["sentences"] >= 5 and st["sentence_length_variation"] < 0.35:
        out.append("Sentence lengths are very even; vary them for a more natural rhythm.")
    stock = counts.get("ai_stock", 0) + counts.get("cliche", 0) + counts.get("filler", 0) + counts.get("wordy", 0)
    if stock:
        out.append(f"{stock} stock, wordy or filler phrase(s) could be plainer.")
    if counts.get("passive"):
        out.append(f"{counts['passive']} passive construction(s).")
    if counts.get("long"):
        out.append(f"{counts['long']} long sentence(s).")
    if counts.get("repetition"):
        out.append(f"{counts['repetition']} repetition flag(s).")
    if len(out) == 1:
        out.append("No major style problems found.")
    return out
