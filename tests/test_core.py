import io
import random
import re

from app import rules as R
from app.feedback import analyse, readability
from app.protect import protect, restore, numbers_ok, placeholders_ok
from app.rewrite import rewrite, build_prompt, clean_output, _looks_ok
from app.spelling import to_british
from app.textutils import split_sentences, extract_text, count_syllables
from app.diff import word_diff


def test_sentence_split_offsets_and_abbreviations():
    t = "Dr. Moyo spoke first. Results (e.g. Table 2) improved. Banda et al. agreed!\nNew para here."
    s = split_sentences(t)
    assert [x[2] for x in s] == ["Dr. Moyo spoke first.", "Results (e.g. Table 2) improved.", "Banda et al. agreed!", "New para here."]
    for a, b, txt in s:
        assert t[a:b] == txt


def test_syllables():
    assert count_syllables("cat") == 1 and count_syllables("education") >= 4


def test_protect_roundtrip_quotes_citations_urls():
    t = 'As Moyo (2021) argues, "access is key" (Banda et al., 2019, p. 4); see https://cut.ac.zw and [3, 4].'
    ph, saved = protect(t)
    kinds = sorted(s["kind"] for s in saved)
    assert kinds.count("citation") == 3 and "quote" in kinds and "url" in kinds
    assert "access is key" not in ph
    assert restore(ph, saved) == t


def test_number_and_placeholder_guards():
    assert numbers_ok("68% of 1,200 students {{0}}", "Of 1,200 students, 68% {{0}}")
    assert not numbers_ok("68% of 1,200 students", "70% of 1,200 students")
    assert not placeholders_ok("a {{0}} b {{1}}", "a {{0}} b")
    assert _looks_ok("one two three four five {{0}}", "one two three four five {{0}}") is None
    assert "citation" in _looks_ok("one two three four {{0}}", "one two three four")


def test_british_spelling():
    assert to_british("We organized the color center and analyzed behavior.") == "We organised the colour centre and analysed behaviour."
    assert to_british("size prize seize citizen") == "size prize seize citizen"


def test_default_rules_valid_and_file_created(tmp_data):
    rules = R.load_rules()
    assert (tmp_data / "style_rules.json").exists()
    assert {r["type"] for r in rules} == set(R.RULE_TYPES)
    for r in rules:
        R.validate_rule(r)


def test_replace_rule_random_alternatives_and_case():
    rule = {"id": "t", "name": "t", "type": "replace", "pattern": "utilize", "alternatives": ["use", "employ"],
            "applies_to": ["rewrite"]}
    seen = set()
    for seed in range(20):
        out, ch = R.apply_replacements("Utilize it and utilize them.", [rule], rng=random.Random(seed))
        seen.add(out)
        assert out.startswith(("Use", "Employ"))
    assert len(seen) > 1  # alternatives are picked at random


def test_regex_replace_and_delete_tidies_text():
    rule = {"id": "x", "name": "x", "type": "replace", "regex": True, "whole_word": False,
            "pattern": r"it is important to note that,?\s*", "alternatives": [""], "applies_to": ["rewrite"]}
    out, _ = R.apply_replacements("Also, it is important to note that rain fell. it is important to note that sun shone.", [rule])
    assert out == "Also, rain fell. Sun shone."


def test_replace_skips_protected_placeholders():
    rule = {"id": "x", "name": "x", "type": "replace", "pattern": "delve into", "alternatives": ["examine"], "applies_to": ["rewrite"]}
    ph, saved = protect('He said "we delve into data" and we delve into it.')
    out, _ = R.apply_replacements(ph, [rule])
    assert restore(out, saved) == 'He said "we delve into data" and we examine it.'


def test_ban_rule_remove_and_flag():
    ban = {"id": "b", "name": "b", "type": "ban", "phrases": ["very"], "action": "remove", "applies_to": ["rewrite", "feedback"]}
    out, _ = R.apply_replacements("It was very good.", [ban])
    assert out == "It was good."
    fb = analyse("It was very good.", [ban])
    assert any(i["rule"] == "b" for i in fb["issues"])


def test_contractions():
    assert R.contract("It is not true that we are late.") == "It isn't true that we're late."
    assert R.expand("It's true we don't know.") == "It is true we do not know."
    rules = [{"id": "c", "type": "contractions", "mode": "off", "applies_to": ["rewrite"], "enabled": True}]
    assert R.contraction_mode(rules, "friendly") == "use"
    assert R.contraction_mode(rules, "academic") == "avoid"
    rules[0]["mode"] = "avoid"
    assert R.contraction_mode(rules, "friendly") == "avoid"


def test_tone_rules_reach_prompt():
    rules = [{"id": "t1", "type": "tone", "tones": ["friendly"], "instruction": "Use the word 'folks'.", "applies_to": ["rewrite"], "enabled": True},
             {"id": "t2", "type": "tone", "tones": [], "instruction": "GLOBAL-RULE", "applies_to": ["rewrite"], "enabled": True},
             {"id": "t3", "type": "tone", "tones": [], "instruction": "DISABLED", "applies_to": ["rewrite"], "enabled": False},
             {"id": "b", "type": "ban", "phrases": ["synergy"], "applies_to": ["rewrite"], "enabled": True}]
    sysmsg = build_prompt("x {{0}}", "friendly", "full", True, rules, 1)[0]["content"]
    assert "folks" in sysmsg and "GLOBAL-RULE" in sysmsg and "DISABLED" not in sysmsg
    assert "synergy" in sysmsg and "{{0}}" in sysmsg and "British" in sysmsg
    assert "folks" not in build_prompt("x", "academic", "light", False, rules, 0)[0]["content"]


def test_sentence_length_rule_thresholds():
    long = "word " * 35 + "end."
    rules = [{"id": "s", "type": "sentence_length", "warn_words": 30, "max_words": 50, "min_variation": 0.35, "applies_to": ["feedback"], "enabled": True}]
    assert any(i["category"] == "long" for i in analyse(long, rules)["issues"])
    rules[0]["warn_words"] = 40
    assert not any(i["category"] == "long" for i in analyse(long, rules)["issues"])


def test_custom_check_rule():
    rules = [{"id": "c", "type": "check", "pattern": r"\bThis shows\b", "message": "Vague", "suggestion": "Name it",
              "applies_to": ["feedback"], "enabled": True, "category": "custom"}]
    fb = analyse("This shows growth. Data matter.", rules)
    hits = [i for i in fb["issues"] if i["rule"] == "c"]
    assert len(hits) == 1 and hits[0]["start"] == 0


def test_validation_errors():
    import pytest
    for bad in [{"type": "nope"}, {"type": "replace", "pattern": "x", "alternatives": []},
                {"type": "check", "pattern": "("}, {"type": "contractions", "mode": "maybe"},
                {"type": "tone", "instruction": " "}, {"type": "ban", "phrases": "x"}]:
        with pytest.raises(R.RuleError):
            R.validate_rule(bad)


def test_import_export_merge_and_replace():
    n = len(R.load_rules())
    new = {"rules": [{"id": "mine", "name": "mine", "type": "ban", "phrases": ["synergy"]}]}
    R.import_json(R.export_json(new["rules"]), mode="merge")
    assert len(R.load_rules()) == n + 1
    R.import_json(new, mode="replace")
    assert [r["id"] for r in R.load_rules()] == ["mine"]
    assert len(R.reset_rules()) == n


def test_feedback_on_sample(sample):
    fb = analyse(sample)
    cats = fb["counts"]
    for c in ("ai_stock", "wordy", "repetition", "rhythm", "structure"):
        assert cats.get(c), c
    for i in fb["issues"]:
        assert 0 <= i["start"] < i["end"] <= len(sample)
    assert 0 < fb["stats"]["flesch_reading_ease"] < 70
    assert "not a judgement" in fb["note"]


def test_passive_detection():
    fb = analyse("The samples were collected by the team. The report was written quickly.")
    assert sum(1 for i in fb["issues"] if i["category"] == "passive") == 2


def test_readability_basic():
    st = readability("The cat sat. The dog ran far away from home today.")
    assert st["sentences"] == 2 and st["words"] == 11


def test_rules_only_rewrite_preserves_quotes_citations_numbers(sample):
    r = rewrite(sample, tone="academic", strength="light", british=True, seed=3)
    out = r["text"]
    assert r["backends"] == ["rules"]
    assert "(Moyo, 2023)" in out and "Banda et al. (2021)" in out
    assert '"connectivity remains the single biggest barrier to equitable access."' in out
    for n in ("2022", "1,200", "68%"):
        assert n in out
    assert "utilize" not in out and "in order to" not in out and "fast-paced" not in out
    assert out.count("\n\n") == 1  # paragraph structure kept


def test_clean_output_strips_preamble():
    assert clean_output("Here is the rewritten text:\nHello there.", "x") == "Hello there."
    assert clean_output('"Hello there."', "x") == "Hello there."


def test_word_diff():
    d = word_diff("the cat sat", "the dog sat")
    assert ["del", "cat"] in d["left"] and ["ins", "dog"] in d["right"]


def test_extract_docx_and_txt():
    import docx
    doc = docx.Document()
    doc.add_paragraph("First paragraph.")
    doc.add_paragraph("Second paragraph.")
    buf = io.BytesIO()
    doc.save(buf)
    assert extract_text("a.docx", buf.getvalue()) == "First paragraph.\n\nSecond paragraph."
    assert extract_text("a.txt", "Hi  there\r\n".encode()) == "Hi there"


def test_no_evasion_features_in_codebase():
    """Guard: the app must stay an editing aid (no detector loops, invisible characters or bypass modes)."""
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    code = "".join(p.read_text(encoding="utf-8") for p in list((root / "app").glob("*.py")) + [root / "static" / "index.html"])
    low = code.lower()
    for bad in ("undetectable", "bypass", "turnitin", "gptzero", "zerogpt", "ai score", "detector score"):
        assert bad not in low, bad
    for ch in ("\u200b", "\u200c", "\u200d", "\u2060", "\ufeff"):
        assert ch not in code


def test_capitalise_after_closing_quote_and_keep_eg():
    assert R.tidy('as they note, "access matters." technology helps.') == 'As they note, "access matters." Technology helps.'
    assert R.tidy("tools (e.g. phones) help.") == "Tools (e.g. phones) help."


def test_quote_sentences_are_frozen():
    from app.rewrite import chunk_paragraph
    parts = chunk_paragraph('First idea here. As Banda notes, "access is key." Last idea here.')
    assert parts == [("First idea here.", False), ('As Banda notes, "access is key."', True), ("Last idea here.", False)]


def test_regex_backreference_and_example_rules_file():
    import json
    from pathlib import Path
    data = json.loads((Path(__file__).resolve().parent.parent / "docs" / "example_rules.json").read_text(encoding="utf-8"))
    rules = [R.validate_rule(r) for r in data["rules"]]
    rule = [r for r in rules if r["id"] == "regex-in-terms-of"]
    out, _ = R.apply_replacements("We failed in terms of cost.", rule, rng=random.Random(0))
    assert out in ("We failed for cost.", "We failed regarding cost.")
