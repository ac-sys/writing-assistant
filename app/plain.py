"""Plain-language post-processing: swap complex words for plain ones (editable list in data/plain_words.json)
and split very long sentences at safe points. Works on text where quotes/citations are already placeholders."""
import json
import os
import re
import shutil
import threading
from pathlib import Path

from .protect import PH_RE
from .textutils import split_sentences, words

_DEFAULT = Path(__file__).resolve().parent / "default_plain_words.json"
_LOCK = threading.Lock()


def words_path() -> Path:
    base = Path(os.environ.get("WA_DATA", Path(__file__).resolve().parent.parent / "data"))
    return base / "plain_words.json"


def load_words():
    p = words_path()
    with _LOCK:
        if not p.exists():
            p.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(_DEFAULT, p)
        data = json.loads(p.read_text(encoding="utf-8"))
    w = data.get("words", data) if isinstance(data, dict) else {}
    return {k.lower(): v for k, v in w.items() if not k.startswith("_") and v is not None}


def save_words(mapping):
    if not isinstance(mapping, dict):
        raise ValueError("Plain words must be an object of {complex: plain}")
    for k, v in mapping.items():
        if not isinstance(k, str) or not k.strip() or (v is not None and not isinstance(v, str)):
            raise ValueError(f"Bad entry: {k!r}")
    p = words_path()
    data = {"_help": json.loads(_DEFAULT.read_text(encoding="utf-8"))["_help"], "words": mapping}
    with _LOCK:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return load_words()


def reset_words():
    return save_words(json.loads(_DEFAULT.read_text(encoding="utf-8"))["words"])


def _case(src, rep):
    if src.isupper() and len(src) > 1:
        return rep.upper()
    return rep[:1].upper() + rep[1:] if src[:1].isupper() else rep


def simplify(text, mapping=None):
    """Return (text, changes). Placeholders like {{0}} are never touched."""
    mapping = load_words() if mapping is None else mapping
    if not mapping:
        return text, []
    keys = sorted(mapping, key=len, reverse=True)
    rx = re.compile(r"(?<![\w{-])(" + "|".join(re.escape(k).replace(r"\ ", r"\s+") for k in keys) + r")(?![\w}-])", re.IGNORECASE)
    changes = []

    def sub(m):
        key = re.sub(r"\s+", " ", m.group(0).lower())
        rep = mapping.get(key)
        if rep is None:
            return m.group(0)
        rep = _case(m.group(0), rep)
        changes.append({"from": m.group(0), "to": rep, "rule": "plain-words"})
        return rep
    text = rx.sub(sub, text)
    # fix article before a swapped word: "a extra" -> "an extra", "an help" -> "a help"
    text = re.sub(r"\b([Aa])n? (?=[aeiouAEIOU])(?!u[nsr]|one|eu)", lambda m: m.group(1) + "n ", text)
    text = re.sub(r"\b([Aa])n (?=[^aeiouAEIOU\W])(?!hour|honest|honour)", lambda m: m.group(1) + " ", text)
    return text, changes


SUBJECT_START = re.compile(
    r"^(?:it|they|this|these|those|we|he|she|i|you|the|its|their|there|many|most|some|students|lecturers|"
    r"teachers|researchers|such|each|one|both|our|his|her|that)\b", re.IGNORECASE)
_SPLIT_POINTS = [
    (re.compile(r";\s+"), ""),                         # "A; B" -> "A. B"
    (re.compile(r",\s+but\s+"), "But "),
    (re.compile(r",\s+and\s+(?=\S)"), ""),             # only when right side starts with a subject
    (re.compile(r",\s+so\s+"), "So "),
]


def _split_once(sent, min_part=6):
    """Split one sentence at the most central safe point. Returns list of 1 or 2 sentences."""
    n = len(words(sent))
    best = None
    for rx, lead in _SPLIT_POINTS:
        for m in rx.finditer(sent):
            left, right = sent[:m.start()].rstrip(), sent[m.end():].lstrip()
            if PH_RE.search(sent[max(0, m.start() - 1):m.end() + 1]):
                continue
            if left.count("(") != left.count(")") or left.count('"') % 2:
                continue  # inside brackets or a quotation
            if len(words(left)) < min_part or len(words(right)) < min_part:
                continue
            if lead == "" and rx.pattern.startswith(",") and not SUBJECT_START.match(right):
                continue  # ", and" joining a list or verb phrase is not a safe split
            score = abs(len(words(left)) - n / 2)
            if best is None or score < best[0]:
                rlead = lead + right if lead else right[:1].upper() + right[1:]
                left = left.rstrip(",;:") + ("" if left.endswith((".", "!", "?")) else ".")
                best = (score, [left, rlead])
    return best[1] if best else [sent]


def split_long_sentences(text, max_words=30):
    """Split sentences longer than max_words at safe points (semicolons; ', but'; ', and' + new subject; ...)."""
    out, last, changes = [], 0, []
    for a, b, s in split_sentences(text):
        out.append(text[last:a])
        parts = [s]
        for _ in range(2):  # at most two splits per sentence
            new = []
            for p in parts:
                new += _split_once(p) if len(words(p)) > max_words else [p]
            if new == parts:
                break
            parts = new
        if len(parts) > 1:
            changes.append({"from": s, "to": " ".join(parts), "rule": "split-long-sentence"})
        out.append(" ".join(parts))
        last = b
    out.append(text[last:])
    return "".join(out), changes
