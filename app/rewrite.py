"""Rewrite engine: chunking, prompting, safety checks and post-processing.

Backends, in order:
  1. OpenAI-compatible API (only if enabled in Settings and a key is set)
  2. Local CPU model via transformers (default: Qwen2.5-1.5B-Instruct), works offline once downloaded
  3. Rules-only pass (your style rules + spelling/contractions), always available
If a backend fails or breaks a quote/citation/number, the next one is used for that chunk.
"""
import logging
import os
import random
import re
import threading
import time

from . import config, rules as R
from .protect import protect, restore, placeholders_ok, numbers_ok, numbers, PH_RE
from .spelling import to_british
from .plain import simplify, split_long_sentences
from .feedback import readability
from .textutils import paragraphs, split_sentences, words

log = logging.getLogger("wa.rewrite")
TONES = {
    "academic": "an academic reader (university essay or report): precise, measured and formal, but not stiff",
    "formal": "a professional reader (business or official writing): clear, polite and direct",
    "friendly": "a general adult reader: warm, conversational and easy to follow (adult register, no slang such as 'kids' or 'stuff')",
    "simple": "a busy adult reader who wants plain English: short words, short sentences, no jargon (adult register, not childish)",
}
STRENGTH = {
    "light": ("Make a light edit. Keep the structure and most of the wording. Fix only stiff, wordy, repetitive "
              "or robotic phrasing, and smooth the flow.", 0.3),
    "full": ("Rewrite freely in fresh wording. You may reorder clauses, merge or split sentences and change the "
             "rhythm, but keep the paragraph's meaning and every point it makes.", 0.6),
}
# Lower temperatures for the plain-language tones: small models drift into fancy wording when sampling hot.
TEMPERATURE = {
    ("light", "academic"): 0.3, ("light", "formal"): 0.3, ("light", "friendly"): 0.25, ("light", "simple"): 0.2,
    ("full", "academic"): 0.6, ("full", "formal"): 0.55, ("full", "friendly"): 0.45, ("full", "simple"): 0.3,
}
REGISTER_LINE = {
    "academic": "Keep an academic register: plain words, but no slang, no contractions and no clipped words (never 'tech', 'stuff', 'kids', 'lots of', 'higher ed').",
    "formal": "Keep a professional register: plain words, but no slang or clipped words (never 'tech', 'stuff', 'kids', 'lots of').",
    "friendly": "Keep it suitable for adult readers: relaxed but not childish, no slang such as 'kids' or 'stuff'.",
    "simple": "Keep it suitable for adult readers: simple but not childish.",
}
PLAIN_LINE = ("Use plain, everyday words: prefer short words (use 'use' not 'utilise', 'help' not 'facilitate', "
              "'show' not 'demonstrate', 'improve' not 'enhance'). Turn abstract nouns into verbs "
              "('the implementation of X' -> 'putting X in place'). Plain does not mean vague: keep precise subject "
              "terms exactly (e.g. 'digital tools', 'online platforms', 'digital literacy', 'lecturers') and keep who "
              "does what. Cut empty stock openers such as 'In today's world'.")
# Few-shot examples: show the small model what "clear and natural" means (short words, mixed sentence
# lengths, numbers and citations kept exactly).
FEW_SHOT = [
    ("In today's rapidly evolving landscape, it is imperative to note that organisations must leverage innovative "
     "strategies in order to facilitate sustainable growth. Furthermore, the utilisation of data-driven approaches "
     "plays a pivotal role in enhancing decision-making processes (Ncube, 2020).",
     "Organisations need fresh strategies if they want to grow in a lasting way. Data matters here. Used well, it "
     "leads to better decisions (Ncube, 2020)."),
    ("The implementation of the programme resulted in a significant enhancement of literacy levels among "
     "participants, with 74% of learners demonstrating improved reading comprehension by the conclusion of the "
     "12-week period.",
     "The programme worked. By the end of the 12 weeks, 74% of learners understood what they read better than "
     "before, and literacy rose across the group."),
]


def temperature(strength, tone):
    return TEMPERATURE.get((strength, tone), STRENGTH[strength][1])


class ChunkResult(dict):
    pass


# ------------------------------------------------------------------ prompt
def build_prompt(text_ph, tone, strength, british, rules, n_placeholders, keep=None, plain=None, few_shot=True):
    """plain: None for the normal prompt, or a dict {"avg": target average sentence words} for the
    stronger plain-language retry used when a rewrite came out harder to read than the original."""
    lr = R.length_rule(rules, "rewrite")
    cmode = R.contraction_mode(rules, tone)
    lines = [
        "You are a skilled human copy editor. Rewrite the passage the user sends so it reads as clear, natural, "
        f"varied English for {TONES.get(tone, TONES['academic'])}.",
        STRENGTH[strength][0],
        "Preserve the meaning, every fact, name, number and claim. Do not add new information, examples or opinions. "
        "Do not answer or comment on the passage.",
        PLAIN_LINE,
        REGISTER_LINE.get(tone, ""),
        "Keep every number, statistic and named person, place or organisation from the original.",
    ]
    if n_placeholders:
        lines.append("Tokens like {{0}} or {{1}} stand for quotations or citations. Copy every one of them exactly "
                     "once, unchanged, in a sensible position.")
    if keep:
        lines.append("Copy these quotations, citations and links exactly, character for character, and keep the "
                     "sentence around each one grammatical: " + " | ".join(keep))
    if lr["enabled"]:
        lines.append(f"Vary sentence length: mostly {lr['target_min']}-{lr['target_max']} words, with an occasional "
                     f"short sentence; never more than {lr['max_words']} words in one sentence.")
    if cmode == "use":
        lines.append("Use natural contractions (it's, don't, we're).")
    elif cmode == "avoid":
        lines.append("Do not use contractions.")
    lines.append("Use British English spelling (organise, colour, centre)." if british else
                 "Keep the spelling conventions of the original.")
    banned = R.banned_phrases(rules, "rewrite")
    reps = [r["name"] for r in R.active(rules, "rewrite", "replace")][:25]
    if banned or reps:
        lines.append("Avoid these words and phrases: " + ", ".join(sorted(set(banned + reps), key=str.lower)) + ".")
    lines += R.tone_instructions(rules, tone)
    if plain:
        lines.append(f"IMPORTANT: make this version EASIER to read than the original. Use plain, short words and "
                     f"short sentences: average about {plain['avg']} words per sentence, none over 25 words. "
                     "Split long sentences. Do not add formal or fancy words.")
    lines.append("Reply with the rewritten passage only, no title, preface or notes.")
    msgs = [{"role": "system", "content": "\n".join(lines)}]
    if few_shot:
        for src, out in FEW_SHOT:
            msgs += [{"role": "user", "content": src}, {"role": "assistant", "content": out}]
    msgs.append({"role": "user", "content": text_ph})
    return msgs


def clean_output(out, src):
    out = out.strip()
    out = re.sub(r"^(?:here(?:'s| is)[^:\n]{0,80}:|rewritten (?:text|passage|version):|sure[^:\n]{0,60}:)\s*", "", out, flags=re.I)
    out = re.sub(r"\n+(?:note|notes|explanation)\s*:.*$", "", out, flags=re.I | re.S)
    if out.startswith(("\"", "\u201c")) and out.endswith(("\"", "\u201d")) and not src.strip().startswith(("\"", "\u201c")):
        out = out[1:-1].strip()
    out = re.sub(r"\s*\n\s*", " ", out)  # one chunk = one paragraph
    return out.strip()


# ------------------------------------------------------------------ backends
class LocalModel:
    _inst = None
    _lock = threading.Lock()

    def __init__(self, name):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
        torch.set_num_threads(max(1, (os.cpu_count() or 2)))
        self.name = name
        t = time.time()
        self.tok = AutoTokenizer.from_pretrained(name)
        self.model = AutoModelForCausalLM.from_pretrained(name, dtype=torch.float32)
        self.model.eval()
        log.info("loaded %s in %.1fs", name, time.time() - t)

    @classmethod
    def get(cls, name):
        with cls._lock:
            if cls._inst is None or cls._inst.name != name:
                cls._inst = None
                cls._inst = LocalModel(name)
            return cls._inst

    def generate(self, messages, temperature, max_new_tokens, seed=None):
        import torch
        if seed is not None:
            torch.manual_seed(seed)
        enc = self.tok.apply_chat_template(messages, add_generation_prompt=True, return_tensors="pt", return_dict=True)
        kw = dict(max_new_tokens=max_new_tokens, repetition_penalty=1.05)
        if temperature > 0.05:
            kw.update(do_sample=True, temperature=temperature, top_p=0.9)
        else:
            kw.update(do_sample=False)
        with LocalModel._lock, torch.inference_mode():
            out = self.model.generate(**enc, **kw)
        return self.tok.decode(out[0][enc["input_ids"].shape[1]:], skip_special_tokens=True)


def api_generate(settings, messages, temperature, max_tokens):
    import httpx
    base = settings["api_base"].rstrip("/")
    r = httpx.post(f"{base}/chat/completions", timeout=settings.get("api_timeout", 90),
                   headers={"Authorization": f"Bearer {settings['api_key']}"},
                   json={"model": settings["api_model"], "messages": messages,
                         "temperature": temperature, "max_tokens": max_tokens})
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def test_api(settings):
    t = time.time()
    out = api_generate(settings, [{"role": "user", "content": "Reply with the single word: ready"}], 0, 5)
    return {"ok": True, "reply": out.strip()[:40], "seconds": round(time.time() - t, 2)}


# ------------------------------------------------------------------ chunking
def _has_quote(sentence):
    return any(sp["kind"] == "quote" for sp in protect(sentence)[1])


def _data_heavy(sentence):
    """Sentences carrying two or more figures (outside citations) are kept out of the model: small models
    often drop one of the figures, which the number guard would then reject for the whole chunk."""
    return len(numbers(protect(sentence)[0])) >= 2


def chunk_paragraph(p, max_words=130):
    """Split a paragraph into (text, frozen) pieces. Sentences that contain a direct quotation are 'frozen':
    they skip the language model (small models tend to paraphrase quotes) and only get the rule-based pass,
    which never touches the quoted words."""
    sents = [s for _, _, s in split_sentences(p)] or [p]
    out, cur = [], []
    for s in sents:
        if _has_quote(s) or _data_heavy(s):
            if cur:
                out.append((" ".join(cur), False)); cur = []
            out.append((s, True))
            continue
        if cur and len(words(" ".join(cur + [s]))) > max_words:
            out.append((" ".join(cur), False)); cur = []
        cur.append(s)
    if cur:
        out.append((" ".join(cur), False))
    return out


def postprocess(text_ph, rules, tone, british, rng, plain_words=True):
    text_ph, changes = R.apply_replacements(text_ph, rules, rng=rng, protected=PH_RE, tone=tone)
    if plain_words:
        text_ph, ch = simplify(text_ph)
        changes += ch
        lr = R.length_rule(rules, "rewrite")
        if lr["enabled"]:
            text_ph, ch = split_long_sentences(text_ph, max_words=int(lr["warn_words"]))
            changes += ch
    mode = R.contraction_mode(rules, tone)
    if mode == "use":
        text_ph = R.contract(text_ph)
    elif mode == "avoid":
        text_ph = R.expand(text_ph)
    if british:
        text_ph = to_british(text_ph)
    return text_ph, changes


def metrics(text):
    st = readability(text)
    return {"fre": st.get("flesch_reading_ease", 0.0), "avg": st.get("avg_sentence_words", 0.0)}


def harder(m, base, fre_margin=3.0, avg_margin=0.5):
    """True if text with metrics m is harder to read than the original (base)."""
    if m["fre"] < base["fre"] - fre_margin:
        return True
    # longer average sentences count as harder unless reading ease clearly improved anyway
    return m["avg"] > base["avg"] + avg_margin and m["fre"] < base["fre"] + 5


def _looks_ok(src_ph, out_ph):
    if not out_ph.strip():
        return "empty output"
    if len(PH_RE.findall(out_ph)) < len(PH_RE.findall(src_ph)):
        return "a quote or citation was changed"
    if not numbers_ok(src_ph, out_ph):
        return "a number was changed"
    ratio = len(words(out_ph)) / max(1, len(words(src_ph)))
    if ratio < 0.45 or ratio > 1.8:
        return f"length changed too much ({ratio:.2f}x)"
    return None


def _spans_ok(spans, out):
    for sp in spans:
        if out.count(sp["text"]) < 1:
            return f"changed or dropped: {sp['text'][:60]}"
    return None


def _content(s):
    return {w.lower() for w in words(s) if len(w) > 3}


def repair_citations(src, out, saved):
    """Small models often drop a parenthetical citation such as (Moyo, 2023) or [3] at the end of a sentence.
    Put it back at the end of the output sentence that best matches the source sentence it came from.
    Only bracketed citations are repaired; quotes and narrative citations are never re-inserted."""
    src_sents = split_sentences(src)
    for sp in saved:
        t = sp["text"]
        if sp["kind"] != "citation" or not t.startswith(("(", "[")) or t in out:
            continue
        pos = src.find(t)
        home = next((s for a, b, s in src_sents if a <= pos < b), None)
        if not home:
            continue
        target = _content(home.replace(t, ""))
        outs = split_sentences(out)
        if not outs:
            continue
        best = max(outs, key=lambda x: len(target & _content(x[2])) / (1 + len(_content(x[2]))))
        if not target & _content(best[2]):
            continue
        a, b, sent = best
        body = sent.rstrip()
        end = len(body) - len(body.rstrip(".!?"))
        fixed = body[:len(body) - end].rstrip() + " " + t + body[len(body) - end:]
        out = out[:a] + fixed + out[b:]
    return out


def rewrite_chunk(chunk, tone, strength, british, rules, settings, rng, seed=None, plain_words=True,
                  readability_check=True):
    """The model sees the real text (quotes and citations included, so it keeps the grammar around them);
    afterwards every quote/citation/URL must still be present verbatim and every number must survive.
    Readability check: if a rewrite is harder to read than the original, retry (max 2) with a stronger
    plain-language instruction, then keep the most readable valid version."""
    src_ph, saved = protect(chunk)
    keep = [s["text"] for s in saved]
    base = metrics(chunk)
    T = temperature(strength, tone)
    max_new = int(len(words(chunk)) * 2.2) + 60
    notes, backends = [], []
    if settings.get("use_api") and settings.get("api_key"):
        backends.append(("api", lambda m, t: api_generate(settings, m, t, max_new)))
    if not config.no_model():
        name = settings["local_model"]
        backends.append(("local", lambda m, t: LocalModel.get(name).generate(m, t, max_new, seed)))
    cands = []
    for backend, gen in backends:
        plain, tries, failed = None, 0, False
        while tries < 3:
            if plain:
                t = min(T, 0.3) if tries == 1 else 0.0
            else:
                t = T if tries == 0 else 0.0  # greedy retry after an invalid output
            msgs = build_prompt(chunk, tone, strength, british, rules, 0, keep=keep, plain=plain)
            try:
                raw = gen(msgs, t)
            except Exception as e:  # network/model errors -> next backend
                notes.append(f"{backend} failed: {type(e).__name__}: {str(e)[:120]}")
                failed = True
                break
            tries += 1
            out = repair_citations(chunk, clean_output(raw, chunk), saved)
            problem = _spans_ok(saved, out)
            out_ph, out_saved = protect(out)
            problem = problem or _looks_ok(src_ph, out_ph)
            if problem:
                notes.append(f"{backend} output rejected ({problem}); retrying")
                continue
            out_ph, changes = postprocess(out_ph, rules, tone, british, rng, plain_words)
            text = restore(out_ph, out_saved)
            m = metrics(text)
            cands.append({"text": text, "backend": backend, "changes": changes, "m": m, "try": tries,
                          "plain_retry": bool(plain)})
            if not readability_check or not harder(m, base):
                break
            notes.append(f"Rewrite was harder to read (reading ease {m['fre']} vs {base['fre']}, "
                         f"avg sentence {m['avg']} vs {base['avg']} words); retried with plainer wording")
            plain = {"avg": max(8, min(18, int(base["avg"]) - 2))}
        if cands:
            break
    if cands:
        best = max(cands, key=lambda c: (c["m"]["fre"], -c["m"]["avg"])) if readability_check else cands[-1]
        return ChunkResult(text=best["text"], backend=best["backend"], notes=notes, rule_changes=best["changes"],
                           attempts=len(cands), readability_retries=sum(c["plain_retry"] for c in cands),
                           before=base, after=best["m"])
    out_ph, changes = postprocess(src_ph, rules, tone, british, rng, plain_words)
    text = restore(out_ph, saved)
    return ChunkResult(text=text, backend="rules", notes=notes, rule_changes=changes, attempts=0,
                       readability_retries=0, before=base, after=metrics(text))


def _metric_summary(st):
    keys = ("flesch_reading_ease", "flesch_kincaid_grade", "gunning_fog", "avg_sentence_words",
            "sentence_length_variation", "longest_sentence", "words", "sentences", "reading_ease_label")
    return {k: st.get(k) for k in keys}


def rewrite(text, tone="academic", strength="light", british=True, rules=None, progress=None, seed=None,
            plain_words=True, readability_check=True):
    tone = tone if tone in TONES else "academic"
    strength = strength if strength in STRENGTH else "light"
    rules = R.load_rules() if rules is None else rules
    settings = config.load()
    rng = random.Random(seed)
    from .citations import split_references
    _, body_end, _refs = split_references(text)
    tail = text[body_end:].strip()  # reference list is kept exactly as written
    text = text[:body_end].rstrip()
    paras = [p for _, _, p in paragraphs(text)]
    plan = [(i, c, fz) for i, p in enumerate(paras) for c, fz in chunk_paragraph(p)]
    out_paras = [[] for _ in paras]
    used, notes, changes = [], [], []
    retries = 0
    t0 = time.time()
    for k, (i, c, frozen) in enumerate(plan):
        if progress:
            progress(k / max(1, len(plan)), f"Rewriting part {k + 1} of {len(plan)}")
        if not words(c) or (len(words(c)) < 4 and not c.rstrip().endswith((".", "!", "?"))):
            out_paras[i].append(c)  # headings / tiny lines kept as they are
            continue
        if frozen:
            ph, saved = protect(c)
            ph, ch = postprocess(ph, rules, tone, british, rng, plain_words)
            res = ChunkResult(text=restore(ph, saved), backend="rules", notes=[], rule_changes=ch)
            notes.append("Sentences with a direct quotation or several figures were kept as written (style rules and plain words only), so quotes and statistics stay exact.")
        else:
            res = rewrite_chunk(c, tone, strength, british, rules, settings, rng, seed, plain_words, readability_check)
            retries += res.get("readability_retries", 0)
        out_paras[i].append(res["text"])
        used.append(res["backend"])
        notes += res["notes"]
        changes += res["rule_changes"]
    if progress:
        progress(1.0, "Done")
    result = "\n\n".join(" ".join(p) for p in out_paras)
    if tail:
        notes.append("The reference list was left unchanged.")
    before, after = _metric_summary(readability(text)), _metric_summary(readability(result))
    full = result + ("\n\n" + tail if tail else "")
    return {"text": full, "backends": sorted(set(used)), "chunks": len(plan), "notes": sorted(set(notes), key=notes.index),
            "rule_changes": changes, "seconds": round(time.time() - t0, 1),
            "readability": {"before": before, "after": after, "retries": retries,
                            "easier": (after["flesch_reading_ease"] or 0) >= (before["flesch_reading_ease"] or 0)},
            "options": {"tone": tone, "strength": strength, "british": british, "plain_words": plain_words,
                        "readability_check": readability_check},
            "model": settings["local_model"] if "local" in used else (settings["api_model"] if "api" in used else "rules only"),
            "label": "Edited with Writing Assistant (editing aid). Review before submitting."}
