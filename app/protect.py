"""Protect quotes, citations, URLs and other must-not-change spans with placeholders."""
import re

PH_RE = re.compile(r"\{\{(\d+)\}\}")
_PATTERNS = [
    ("quote", re.compile(r"\u201c[^\u201d\n]{1,600}\u201d")),
    ("quote", re.compile(r"(?<![\w])\"[^\"\n]{1,600}\"")),
    ("quote", re.compile(r"(?<![\w])\u2018[^\u2019\n]{3,400}\u2019(?![\w])")),
    ("url", re.compile(r"https?://\S+|www\.\S+")),
    ("email", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")),
    # Author (2020) / Author et al. (2020)
    ("citation", re.compile(r"\b[A-Z][A-Za-z'\u2019-]+(?:\s+(?:et al\.|and|&)\s*[A-Z]?[A-Za-z'\u2019.-]*)?\s+\((?:19|20)\d{2}[a-z]?(?:,\s*pp?\.\s*[\d\u2013-]+)?\)")),
    # (Author, 2020) (Author et al., 2019, p. 4) (Smith & Jones 2018; Moyo, 2021a) (WHO, 2020)
    ("citation", re.compile(r"\((?:[^()\n]{0,160}?(?:19|20)\d{2}[a-z]?(?:,\s*pp?\.\s*[\d\u2013-]+)?)(?:;[^()\n]{0,160}?(?:19|20)\d{2}[a-z]?(?:,\s*pp?\.\s*[\d\u2013-]+)?)*\)")),
    ("citation", re.compile(r"\[\d+(?:[\u2013,\s-]+\d+)*\]")),
]
NUM_RE = re.compile(r"(?<![\w{])\d+(?:[.,]\d+)*%?")


def protect(text):
    """Return (text_with_placeholders, list_of_original_spans)."""
    spans = []
    taken = []
    for kind, rx in _PATTERNS:
        for m in rx.finditer(text):
            a, b = m.span()
            if any(a < y and x < b for x, y in taken):
                continue
            taken.append((a, b))
            spans.append((a, b, kind, m.group(0)))
    spans.sort()
    out, saved, last = [], [], 0
    for a, b, kind, s in spans:
        out.append(text[last:a])
        out.append("{{%d}}" % len(saved))
        saved.append({"kind": kind, "text": s})
        last = b
    out.append(text[last:])
    return "".join(out), saved


def restore(text, saved):
    return PH_RE.sub(lambda m: saved[int(m.group(1))]["text"] if int(m.group(1)) < len(saved) else m.group(0), text)


def placeholders_ok(original_ph, new_ph):
    a = sorted(PH_RE.findall(original_ph))
    b = sorted(PH_RE.findall(new_ph))
    return a == b


def numbers(text):
    return sorted(NUM_RE.findall(PH_RE.sub(" ", text)))


def numbers_ok(original_ph, new_ph):
    """All numbers in the original must still appear (the rewrite may not invent or drop figures)."""
    a, b = numbers(original_ph), numbers(new_ph)
    from collections import Counter
    ca, cb = Counter(a), Counter(b)
    return all(cb[k] >= v for k, v in ca.items()) and all(k in ca for k in cb)
