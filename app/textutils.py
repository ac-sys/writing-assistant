"""Text extraction, normalisation and sentence splitting (with character offsets)."""
import io
import re

SUPPORTED = (".txt", ".md", ".docx", ".pdf")


def extract_text_with_styles(filename: str, data: bytes) -> tuple[str, list[str]]:
    name = (filename or "").lower()
    if name.endswith(".docx"):
        import docx
        d = docx.Document(io.BytesIO(data))
        parts, styles = [], []
        for p in d.paragraphs:
            if p.text.strip():
                parts.append(p.text.strip())
                styles.append(getattr(p.style, "name", "Normal") or "Normal")
        return normalise("\n\n".join(parts)), styles
    return extract_text(filename, data), []


def extract_text(filename: str, data: bytes) -> str:
    name = (filename or "").lower()
    if name.endswith(".pdf"):
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data))
        return normalise("\n\n".join((p.extract_text() or "") for p in reader.pages))
    if name.endswith(".docx"):
        import docx
        d = docx.Document(io.BytesIO(data))
        parts = [p.text for p in d.paragraphs if p.text.strip()]
        return normalise("\n\n".join(parts))
    if name.endswith(".txt") or name.endswith(".md"):
        for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
            try:
                return normalise(data.decode(enc))
            except UnicodeDecodeError:
                continue
    raise ValueError("Unsupported file type. Please use DOCX, PDF or TXT.")


def normalise(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t\f\v\u00a0]+", " ", text)
    text = re.sub(r"(\w)-\n(?=[a-z])", r"\1", text)  # PDF hyphenation
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def paragraphs(text: str):
    """Yield (start, end, paragraph) spans. Blank lines separate paragraphs; a single
    newline also separates them (DOCX/TXT usually have one paragraph per line)."""
    out = []
    for m in re.finditer(r"[^\n]+", text):
        if m.group().strip():
            out.append((m.start(), m.end(), m.group()))
    return out


_ABBREV = {"e.g", "i.e", "etc", "al", "dr", "mr", "mrs", "ms", "prof", "vs", "fig", "no",
           "vol", "pp", "p", "cf", "approx", "dept", "st", "jr", "sr", "inc", "ltd", "co", "ed", "eds"}
_BOUNDARY = re.compile(r"[.!?]+[\"')\]\u201d\u2019]*\s+(?=[\"'(\[\u201c\u2018]?[A-Z0-9])")


def split_sentences(text: str):
    """Return list of (start, end, sentence) with offsets into `text`."""
    out = []
    for p_start, _p_end, para in paragraphs(text):
        last = 0
        for m in _BOUNDARY.finditer(para):
            before = para[last:m.start()]
            word = re.findall(r"([A-Za-z.]+)$", before)
            if word and (word[0].lower().rstrip(".") in _ABBREV or re.fullmatch(r"[A-Z]", word[0].rstrip("."))):
                continue
            end = m.end() - len(m.group()) + len(m.group().rstrip())
            seg = para[last:end]
            if seg.strip():
                lead = len(seg) - len(seg.lstrip())
                out.append((p_start + last + lead, p_start + end, seg.strip()))
            last = m.end()
        seg = para[last:]
        if seg.strip():
            lead = len(seg) - len(seg.lstrip())
            out.append((p_start + last + lead, p_start + last + len(seg.rstrip()), seg.strip()))
    return out


WORD_RE = re.compile(r"[A-Za-z]+(?:['\u2019][A-Za-z]+)*")


def words(text: str):
    return WORD_RE.findall(text)


def count_syllables(word: str) -> int:
    w = word.lower().strip("'\u2019")
    if not w:
        return 0
    if len(w) <= 3:
        return 1
    w = re.sub(r"(?:[^laeiouy]es|ed|[^laeiouy]e)$", "", w)
    w = re.sub(r"^y", "", w)
    n = len(re.findall(r"[aeiouy]{1,2}", w))
    return max(1, n)
