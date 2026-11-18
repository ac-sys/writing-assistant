"""User-editable style rules.

Rules live in a JSON file (default: data/style_rules.json, override with WA_RULES_FILE).
Each rule is a dict with common keys:
    id, name, type, enabled, applies_to (["rewrite","feedback"]), description, category
Rule types and their extra keys:
    replace          pattern, regex (bool), case_sensitive (bool), whole_word (bool),
                     alternatives (list[str], one picked at random; "" deletes), message,
                     tones (optional list: only apply in these rewrite tones)
    ban              phrases (list[str]), message, action ("flag" | "remove")
    sentence_length  max_words, warn_words, min_variation (coefficient of variation),
                     target_min, target_max
    contractions     mode ("use" | "avoid" | "off")
    tone             instruction (str), tones (list; empty = all tones)
    check            pattern (regex), message, suggestion, category, case_sensitive
See README "Writing style rules" for examples.
"""
import copy
import json
import os
import random
import re
import threading
import uuid
from pathlib import Path

RULE_TYPES = ("replace", "ban", "sentence_length", "contractions", "tone", "check")
_LOCK = threading.Lock()


def rules_path() -> Path:
    p = os.environ.get("WA_RULES_FILE")
    if p:
        return Path(p)
    base = Path(os.environ.get("WA_DATA", Path(__file__).resolve().parent.parent / "data"))
    return base / "style_rules.json"


def _r(id, name, alternatives, pattern=None, category="ai_stock", message="", regex=False, whole_word=True):
    return {"id": id, "name": name, "type": "replace", "enabled": True,
            "applies_to": ["rewrite", "feedback"], "category": category,
            "pattern": pattern or name, "regex": regex, "case_sensitive": False,
            "whole_word": whole_word, "alternatives": alternatives, "message": message}


def default_rules():
    stock = "Stock phrase that tools and rushed writers overuse; plainer wording reads more naturally."
    wordy = "Wordy construction; a shorter form says the same thing."
    filler = "Filler that adds length but no meaning."
    cliche = "Cliché; say the specific thing instead."
    R = [
        # --- stock / overused phrasing ---
        _r("delve", "delve into", ["look at", "examine", "explore"], r"delves? into|delving into", regex=True, message=stock),
        _r("important-note", "it is important to note that", [""], r"it(?: is|['\u2019]s) (?:important|worth|vital|crucial|essential|interesting) (?:to (?:note|recogni[sz]e|remember|highlight|mention)|noting) that,?\s*", regex=True, whole_word=False, message=stock),
        _r("fast-paced", "in today's fast-paced world", [""], r"in today['\u2019]s (?:(?:fast-paced|ever-changing|rapidly evolving|digital|modern) )?(?:world|society|landscape|age),?\s*", regex=True, whole_word=False, message=stock),
        _r("crucial-role", "plays a crucial role", ["is central to", "matters a great deal for", "shapes"], r"plays? an? (?:crucial|pivotal|vital|key|significant) role in", regex=True, message=stock),
        _r("testament", "a testament to", ["evidence of", "proof of"], message=stock),
        _r("realm", "in the realm of", ["in"], message=stock),
        _r("tapestry", "rich tapestry", ["mix", "range"], r"(?:rich |intricate |vibrant )?tapestry of", regex=True, message=stock),
        _r("navigate-complex", "navigate the complexities of", ["deal with", "handle", "work through"], r"navigat(?:e|ing) the (?:complexities|intricacies) of", regex=True, message=stock),
        _r("underscore", "underscores", ["shows", "highlights"], r"underscores", regex=True, message=stock),
        _r("leverage", "leverage", ["use", "draw on"], r"leverag(?:e|es|ing)", regex=True, message=stock),
        _r("utilize", "utilize", ["use"], r"utili[sz]e", regex=True, category="wordy", message=wordy),
        _r("utilizes", "utilizes", ["uses"], r"utili[sz]es", regex=True, category="wordy", message=wordy),
        _r("utilizing", "utilizing", ["using"], r"utili[sz]ing", regex=True, category="wordy", message=wordy),
        _r("utilized", "utilized", ["used"], r"utili[sz]ed", regex=True, category="wordy", message=wordy),
        _r("utilization", "utilization", ["use"], r"utili[sz]ation", regex=True, category="wordy", message=wordy),
        _r("facilitate", "facilitate", ["help", "support"], category="wordy", message="Abstract verb; a plainer one is clearer."),
        _r("facilitates", "facilitates", ["helps", "supports"], category="wordy", message="Abstract verb; a plainer one is clearer."),
        _r("facilitating", "facilitating", ["helping", "supporting"], category="wordy", message="Abstract verb; a plainer one is clearer."),
        _r("enhance", "enhance", ["improve", "strengthen"], category="wordy", message="Overused verb; 'improve' is usually clearer."),
        _r("enhanced", "enhanced", ["better", "improved"], r"enhanced", regex=True, category="wordy", message="Overused word; 'better' is usually clearer."),
        _r("enhancing", "enhancing", ["improving", "strengthening"], category="wordy", message="Overused verb; 'improving' is usually clearer."),
        _r("employ", "employ", ["use"], r"employ(?=s? )", regex=True, category="wordy", message="Formal verb; 'use' is plainer."),
        _r("exemplifies", "exemplifies", ["shows", "is an example of"], message=stock),
        _r("game-changing", "game-changing", ["major", "far-reaching"], category="cliche", message=cliche),
        _r("robust", "robust", ["strong", "solid"], message=stock),
        _r("big-step-dup", "significant big step", ["\\1"], r"(?:significant|major|substantial) (big step|major shift)", regex=True, whole_word=True, category="style", message="Doubled intensifier.", ),
        _r("pivotal", "pivotal", ["central", "key"], message=stock),
        _r("additionally", "Additionally,", ["Also,", "On top of that,", ""], r"(?<![\w])additionally,\s*", regex=True, whole_word=False, message="Heavy connective; vary or drop it."),
        _r("myriad", "a myriad of", ["many", "countless"], r"a (?:myriad|plethora|multitude) of", regex=True, message=stock),
        _r("ever-evolving", "ever-evolving landscape", ["changing field", "shifting field"], r"ever-(?:evolving|changing) landscape", regex=True, message=stock),
        _r("embark", "embark on a journey", ["start", "begin"], r"embark(?:s|ed|ing)? on (?:a|an|this|the) (?:journey|quest|mission)", regex=True, message=stock),
        _r("unlock", "unlock the potential", ["make full use of", "get the most from"], r"unlock(?:s|ing)? the (?:full )?potential of", regex=True, message=stock),
        _r("harness", "harness the power of", ["use", "make use of"], r"harness(?:es|ing)? the power of", regex=True, message=stock),
        _r("serves-as", "serves as a", ["is a", "acts as a"], r"serves as a", regex=True, message=stock),
        _r("seamless", "seamlessly", ["smoothly", "easily"], message=stock),
        _r("game-changer", "game-changer", ["major shift", "big step forward"], r"game[- ]changer", regex=True, category="cliche", message=cliche),
        _r("showcase", "showcases", ["shows", "presents"], r"showcases", regex=True, message=stock),
        _r("foster", "foster", ["encourage", "build", "support"], r"foster", regex=True, message=stock),
        _r("in-conclusion", "In conclusion,", ["To sum up,", "Overall,", ""], r"in (?:conclusion|summary),\s*", regex=True, whole_word=False, message="Formulaic closer; often the conclusion reads better without it."),
        _r("moreover", "Moreover,", ["Also,", "What is more,", "Besides,", ""], r"(?<![\w])moreover,\s*", regex=True, whole_word=False, message="Heavy connective; vary or drop it."),
        _r("furthermore", "Furthermore,", ["Also,", "On top of that,", "In addition,", ""], r"(?<![\w])furthermore,\s*", regex=True, whole_word=False, message="Heavy connective; vary or drop it."),
        # --- wordy ---
        _r("in-order-to", "in order to", ["to"], category="wordy", message=wordy),
        _r("due-to-fact", "due to the fact that", ["because"], category="wordy", message=wordy),
        _r("at-this-point", "at this point in time", ["now"], category="wordy", message=wordy),
        _r("in-light-of", "in light of the fact that", ["because", "since"], category="wordy", message=wordy),
        _r("has-ability", "has the ability to", ["can"], r"ha(?:s|ve) the ability to", regex=True, category="wordy", message=wordy),
        _r("a-large-number", "a large number of", ["many"], category="wordy", message=wordy),
        _r("for-the-purpose", "for the purpose of", ["for", "to"], category="wordy", message=wordy),
        # --- filler / clichés ---
        _r("needless", "needless to say", [""], r"needless to say,?\s*", regex=True, whole_word=False, category="filler", message=filler),
        _r("goes-without", "it goes without saying that", [""], r"it goes without saying(?: that)?,?\s*", regex=True, whole_word=False, category="filler", message=filler),
        _r("end-of-day", "at the end of the day", ["ultimately", "in the end"], category="cliche", message=cliche),
        _r("this-day-age", "in this day and age", ["today", "now"], category="cliche", message=cliche),
        _r("first-foremost", "first and foremost", ["first"], category="cliche", message=cliche),
        _r("last-not-least", "last but not least", ["finally"], category="cliche", message=cliche),
        _r("think-outside", "think outside the box", ["think creatively"], category="cliche", message=cliche),
        _r("tip-iceberg", "the tip of the iceberg", ["only part of the problem"], category="cliche", message=cliche),
        dict(_r("informal-stuff", "stuff", ["material", "things"], category="style", message="Informal word for academic or formal writing."), tones=["academic", "formal"]),
        dict(_r("informal-kids", "kids", ["young people", "children"], category="style", message="Informal word for academic or formal writing."), tones=["academic", "formal", "friendly", "simple"]),
        dict(_r("informal-tech", "tech", ["technology"], category="style", message="Clipped word; write it out in academic or formal writing."), tones=["academic", "formal"]),
        dict(_r("informal-lots", "lots of", ["many", "a great deal of"], category="style", message="Informal quantity phrase."), tones=["academic", "formal"]),
        dict(_r("informal-higher-ed", "higher ed", ["higher education"], category="style", message="Clipped phrase."), tones=["academic", "formal"]),
        {"id": "ban-hype", "name": "Hype adjectives", "type": "ban", "enabled": True,
         "applies_to": ["rewrite", "feedback"], "category": "ai_stock", "action": "flag",
         "phrases": ["groundbreaking", "cutting-edge", "revolutionary", "transformative", "paramount",
                     "meticulous", "meticulously", "commendable", "bustling", "multifaceted", "holistic"],
         "message": "Inflated or stock adjective. Use a concrete description or drop it."},
        {"id": "ban-filler-words", "name": "Filler intensifiers", "type": "ban", "enabled": True,
         "applies_to": ["feedback"], "category": "filler", "action": "flag",
         "phrases": ["very", "really", "basically", "actually", "literally", "extremely"],
         "message": "Intensifier that rarely adds meaning. Pick a stronger word or cut it."},
        {"id": "sentence-length", "name": "Sentence length and variety", "type": "sentence_length",
         "enabled": True, "applies_to": ["rewrite", "feedback"], "category": "rhythm",
         "warn_words": 30, "max_words": 40, "min_variation": 0.35, "target_min": 6, "target_max": 28,
         "description": "Flag sentences over warn_words/max_words and text whose sentence lengths barely vary."},
        {"id": "contractions", "name": "Contractions", "type": "contractions", "enabled": True,
         "applies_to": ["rewrite", "feedback"], "category": "style", "mode": "off",
         "description": "mode 'use' = prefer contractions (friendly), 'avoid' = expand them (academic/formal), 'off' = leave as is. Friendly tone uses contractions automatically unless this is set to 'avoid'."},
        {"id": "tone-natural", "name": "Natural voice", "type": "tone", "enabled": True,
         "applies_to": ["rewrite"], "tones": [],
         "instruction": "Write the way a thoughtful person explains things: mix short and longer sentences (include at least one short sentence), prefer short everyday words over long abstract ones (use 'help' not 'facilitate', 'improve' not 'enhance'), use active voice where it fits, and avoid stock phrases and formulaic connectives. The result should be easier to read than the original, not harder."},
        {"id": "tone-academic", "name": "Academic voice", "type": "tone", "enabled": True,
         "applies_to": ["rewrite"], "tones": ["academic"],
         "instruction": "Keep hedging where the original hedges, keep technical terms, and do not add claims or examples that are not in the original."},
        {"id": "check-em-dash", "name": "Em-dash overuse", "type": "check", "enabled": True,
         "applies_to": ["feedback"], "category": "style", "pattern": "\u2014",
         "min_count": 3,
         "message": "Lots of em-dashes make prose feel breathless.",
         "suggestion": "Replace some with commas, colons or full stops."},
        {"id": "check-not-only", "name": "'Not only ... but also'", "type": "check", "enabled": True,
         "applies_to": ["feedback"], "category": "ai_stock", "pattern": r"\bnot only\b[^.]{0,80}\bbut also\b",
         "message": "Formulaic contrast pattern, easy to overuse.",
         "suggestion": "State both points directly, e.g. 'X does A and B.'"},
    ]
    return R


# ------------------------------------------------------------------ storage
def load_rules():
    p = rules_path()
    with _LOCK:
        if not p.exists():
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps({"version": 1, "rules": default_rules()}, indent=2, ensure_ascii=False), encoding="utf-8")
        data = json.loads(p.read_text(encoding="utf-8"))
    rules = data["rules"] if isinstance(data, dict) else data
    return [normalise_rule(r) for r in rules]


def save_rules(rules):
    clean = [validate_rule(r) for r in rules]
    p = rules_path()
    with _LOCK:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps({"version": 1, "rules": clean}, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(p)
    return clean


def reset_rules():
    return save_rules(default_rules())


def normalise_rule(r):
    r = dict(r)
    r.setdefault("id", uuid.uuid4().hex[:8])
    r.setdefault("name", r["id"])
    r.setdefault("enabled", True)
    r.setdefault("applies_to", ["rewrite", "feedback"])
    r.setdefault("category", "custom")
    return r


class RuleError(ValueError):
    pass


def validate_rule(r):
    if not isinstance(r, dict):
        raise RuleError("Each rule must be an object")
    r = normalise_rule(r)
    t = r.get("type")
    if t not in RULE_TYPES:
        raise RuleError(f"Rule '{r['name']}': type must be one of {', '.join(RULE_TYPES)}")
    if not set(r["applies_to"]) <= {"rewrite", "feedback"}:
        raise RuleError(f"Rule '{r['name']}': applies_to may only contain 'rewrite' and 'feedback'")
    if t == "replace":
        if not r.get("pattern"):
            raise RuleError(f"Rule '{r['name']}': replace rules need a pattern")
        alts = r.get("alternatives")
        if not isinstance(alts, list) or not alts:
            raise RuleError(f"Rule '{r['name']}': give at least one alternative (\"\" deletes the match)")
        _compile_replace(r)
    elif t == "ban":
        if not isinstance(r.get("phrases"), list) or not r["phrases"]:
            raise RuleError(f"Rule '{r['name']}': ban rules need a list of phrases")
        if r.get("action", "flag") not in ("flag", "remove"):
            raise RuleError(f"Rule '{r['name']}': action must be 'flag' or 'remove'")
    elif t == "contractions":
        if r.get("mode", "off") not in ("use", "avoid", "off"):
            raise RuleError(f"Rule '{r['name']}': mode must be use, avoid or off")
    elif t == "tone":
        if not str(r.get("instruction", "")).strip():
            raise RuleError(f"Rule '{r['name']}': tone rules need an instruction")
    elif t == "check":
        try:
            re.compile(r.get("pattern", ""))
        except re.error as e:
            raise RuleError(f"Rule '{r['name']}': invalid regex: {e}")
        if not r.get("pattern"):
            raise RuleError(f"Rule '{r['name']}': check rules need a pattern")
    elif t == "sentence_length":
        for k in ("warn_words", "max_words", "target_min", "target_max"):
            if k in r and not isinstance(r[k], (int, float)):
                raise RuleError(f"Rule '{r['name']}': {k} must be a number")
    return r


# ------------------------------------------------------------------ helpers
def active(rules, where, rtype=None):
    return [r for r in rules if r.get("enabled", True) and where in r.get("applies_to", [])
            and (rtype is None or r.get("type") == rtype)]


def _compile_replace(r):
    pat = r["pattern"] if r.get("regex") else re.escape(r["pattern"])
    if r.get("whole_word", True):
        pat = r"(?<![\w-])(?:" + pat + r")(?![\w-])"
    flags = 0 if r.get("case_sensitive") else re.IGNORECASE
    try:
        return re.compile(pat, flags)
    except re.error as e:
        raise RuleError(f"Rule '{r.get('name')}': invalid regex: {e}")


def compiled_replace(r):
    return _compile_replace(r)


def ban_regex(phrase):
    return re.compile(r"(?<![\w-])" + re.escape(phrase) + r"(?![\w-])", re.IGNORECASE)


def _match_case(src, rep):
    if not rep:
        return rep
    if src[:1].isupper():
        return rep[:1].upper() + rep[1:]
    return rep


def apply_replacements(text, rules, rng=None, protected=None, tone=None):
    """Apply enabled replace rules (and ban rules with action=remove) to text.
    `protected` is a regex; matches inside it (placeholders) are never touched.
    Returns (new_text, list_of_changes)."""
    rng = rng or random.Random()
    changes = []
    for r in active(rules, "rewrite", "replace"):
        if tone and r.get("tones") and tone not in r["tones"]:
            continue  # rule limited to other tones
        rx = compiled_replace(r)

        def sub(m, r=r):
            if protected and protected.search(m.group(0)):
                return m.group(0)
            alt = rng.choice(r["alternatives"])
            alt = re.sub(r"\\(\d)", lambda g: m.group(int(g.group(1))) or "", alt) if r.get("regex") else alt
            rep = _match_case(m.group(0), alt)
            trail = m.group(0)[len(m.group(0).rstrip()):]
            if rep and trail and not rep.endswith((" ", "\n")):
                rep += trail
            changes.append({"rule": r["id"], "from": m.group(0), "to": rep})
            return rep
        text = rx.sub(sub, text)
    for r in active(rules, "rewrite", "ban"):
        if r.get("action") != "remove":
            continue
        for ph in r["phrases"]:
            def rm(m, r=r):
                changes.append({"rule": r["id"], "from": m.group(0), "to": ""})
                return ""
            text = ban_regex(ph).sub(rm, text)
    return tidy(text), changes


_ABBR_END = re.compile(r"(?:\b(?:e\.g|i\.e|etc|al|cf|vs|approx|p|pp|no|fig)\.)$", re.IGNORECASE)


def _capitalise_starts(text):
    def fix(m):
        pre = text[:m.start(2)].rstrip()
        if m.group(1).strip() == "." or m.group(1).startswith("."):
            if _ABBR_END.search(pre):
                return m.group(0)
        return m.group(1) + m.group(2).upper()
    return re.sub(r"(^|[.!?][\"'\u201d\u2019)]*\s+|\n)([a-z])", fix, text)


def tidy(text):
    """Fix spacing/capitalisation left behind by deletions."""
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r" +([,.;:!?])", r"\1", text)
    text = re.sub(r",\s*,", ",", text)
    text = _capitalise_starts(text)
    text = re.sub(r"(^|\n) +", r"\1", text)
    return text


# ------------------------------------------------------------------ contractions
CONTRACTIONS = {
    "do not": "don't", "does not": "doesn't", "did not": "didn't", "is not": "isn't",
    "are not": "aren't", "was not": "wasn't", "were not": "weren't", "cannot": "can't",
    "could not": "couldn't", "would not": "wouldn't", "should not": "shouldn't",
    "will not": "won't", "have not": "haven't", "has not": "hasn't", "had not": "hadn't",
    "it is": "it's", "that is": "that's", "there is": "there's", "we are": "we're",
    "they are": "they're", "you are": "you're", "I am": "I'm", "we will": "we'll",
    "they will": "they'll", "it will": "it'll", "we have": "we've", "they have": "they've",
    "let us": "let's",
}
EXPANSIONS = {v: k for k, v in CONTRACTIONS.items()}
EXPANSIONS.update({"it's": "it is", "won't": "will not", "can't": "cannot", "I'd": "I would",
                   "we'd": "we would", "they'd": "they would", "you'll": "you will", "he's": "he is",
                   "she's": "she is", "what's": "what is", "who's": "who is", "here's": "here is"})


def _case_like(src, rep):
    return rep[:1].upper() + rep[1:] if src[:1].isupper() else rep


def contract(text):
    for full, short in CONTRACTIONS.items():
        # skip "it is" before a past participle-free check is overkill; keep simple, avoid "that is," (i.e.)
        rx = re.compile(r"(?<![\w'])" + full.replace(" ", r"\s+") + r"(?![\w'])" + (r"(?!,)" if full == "that is" else ""), re.IGNORECASE)
        text = rx.sub(lambda m: _case_like(m.group(0), short), text)
    return text


def expand(text):
    def rep(m):
        w = m.group(0)
        key = w.replace("\u2019", "'")
        full = EXPANSIONS.get(key) or EXPANSIONS.get(key.lower())
        if not full:
            return w
        return _case_like(w, full)
    return re.sub(r"\b[A-Za-z]+[\u2019'](?:t|s|re|ll|ve|m|d)\b", rep, text)


def contraction_mode(rules, tone):
    rs = active(rules, "rewrite", "contractions")
    mode = rs[-1].get("mode", "off") if rs else "off"
    if mode == "off" and tone == "friendly":
        return "use"
    if mode == "off" and tone in ("academic", "formal"):
        return "avoid"
    return mode


def tone_instructions(rules, tone):
    out = []
    for r in active(rules, "rewrite", "tone"):
        tones = r.get("tones") or []
        if not tones or tone in tones:
            out.append(r["instruction"].strip())
    return out


def length_rule(rules, where="feedback"):
    rs = active(rules, where, "sentence_length")
    base = {"warn_words": 30, "max_words": 40, "min_variation": 0.35, "target_min": 6, "target_max": 28}
    if rs:
        base.update({k: v for k, v in rs[-1].items() if k in base})
        base["enabled"] = True
    else:
        base["enabled"] = False
    return base


def banned_phrases(rules, where):
    out = []
    for r in active(rules, where, "ban"):
        out.extend(r["phrases"])
    return out


def export_json(rules):
    return json.dumps({"version": 1, "rules": rules}, indent=2, ensure_ascii=False)


def import_json(payload, mode="merge"):
    data = json.loads(payload) if isinstance(payload, (str, bytes)) else payload
    incoming = data["rules"] if isinstance(data, dict) else data
    incoming = [validate_rule(r) for r in incoming]
    if mode == "replace":
        return save_rules(incoming)
    current = {r["id"]: r for r in load_rules()}
    for r in incoming:
        current[r["id"]] = r
    return save_rules(list(current.values()))
