"""Tests for v1.1: readability loop, plain-words pass, sentence splitting, prompts, flow/conclusion/citation
checks, Groq preset and GROQ_API_KEY."""
import json

import pytest
from fastapi.testclient import TestClient

from app import config, plain as P, rewrite as RW, rules as R
from app.citations import check as cite_check, split_references
from app.feedback import analyse
from app.protect import protect


# ---------------------------------------------------------------- plain words / splitting
def test_simplify_case_articles_and_placeholders():
    out, ch = P.simplify("Utilise numerous tools; an approximately {{0}} additional {{1}}.", {"utilise": "use", "numerous": "many", "approximately": "about", "additional": "extra"})
    assert out == "Use many tools; an about {{0}} extra {{1}}." or out.startswith("Use many tools; about")
    assert len(ch) == 4
    out, _ = P.simplify("We need a additional step.", {"additional": "extra"})
    assert out == "We need an extra step."
    out, _ = P.simplify("This is a utilisation.", {"utilisation": "use"})
    assert "{{" not in out


def test_simplify_multiword_and_default_list(tmp_data):
    w = P.load_words()
    assert (tmp_data / "plain_words.json").exists() and w["utilise"] == "use"
    out, _ = P.simplify("In order to obtain data prior to the test, the majority of staff helped.")
    assert out == "To get data before the test, most staff helped."


def test_plain_words_save_reset_and_validation():
    P.save_words({"commence": "start"})
    assert P.load_words() == {"commence": "start"}
    with pytest.raises(ValueError):
        P.save_words({"x": 3})
    assert len(P.reset_words()) > 50


def test_split_long_sentences_safe_points():
    t = ("The study measured attendance, grades and engagement across three faculties over two years, and the "
         "results showed that blended courses had higher completion rates than face-to-face ones.")
    out, ch = P.split_long_sentences(t, 25)
    assert out == ("The study measured attendance, grades and engagement across three faculties over two years. "
                   "The results showed that blended courses had higher completion rates than face-to-face ones.")
    t2 = "Learners need devices that are cheap and reliable for daily study at home; many families in rural districts cannot afford them at all yet."
    assert P.split_long_sentences(t2, 20)[0].count(". ") == 1


def test_split_does_not_break_lists_or_short_sentences():
    t = "We bought apples, oranges and pears from the market near the station in town, and bananas, grapes and melons from the shop last week."
    assert P.split_long_sentences(t, 15)[0] == t
    assert P.split_long_sentences("Short, and sweet.", 2)[0] == "Short, and sweet."


# ---------------------------------------------------------------- prompts
def test_prompt_has_few_shot_and_plain_instruction():
    rules = R.default_rules()
    msgs = RW.build_prompt("Text here.", "academic", "full", True, rules, 0)
    assert [m["role"] for m in msgs] == ["system", "user", "assistant", "user", "assistant", "user"]
    assert "plain, everyday words" in msgs[0]["content"]
    assert "EASIER to read" not in msgs[0]["content"]
    msgs = RW.build_prompt("Text here.", "academic", "full", True, rules, 0, plain={"avg": 12})
    assert "EASIER to read" in msgs[0]["content"] and "about 12 words" in msgs[0]["content"]
    # few-shot outputs keep their numbers/citations (they teach the model to)
    for src, out in RW.FEW_SHOT:
        assert set(__import__("re").findall(r"\d+%?|\([^)]*\d{4}\)", src)) <= set(__import__("re").findall(r"\d+%?|\([^)]*\d{4}\)", out))


def test_lower_temperature_for_plain_tones():
    assert RW.temperature("full", "simple") < RW.temperature("full", "friendly") < RW.temperature("full", "academic")
    assert RW.temperature("light", "simple") <= 0.2


def test_repair_citations_reinserts_dropped_parenthetical():
    src = "Students use tools. A 2022 survey found that 68% used them weekly (Moyo, 2023)."
    out = "Students rely on tools. A 2022 survey showed 68% used them every week."
    fixed = RW.repair_citations(src, out, protect(src)[1])
    assert fixed.endswith("every week (Moyo, 2023).")


# ---------------------------------------------------------------- readability loop (fake model)
HARD = ("The multifaceted operationalisation of institutional technological infrastructures necessitates comprehensive "
        "organisational reconfiguration, notwithstanding considerable implementation complexities, administrative "
        "inefficiencies and substantial financial expenditure requirements across heterogeneous university departments.")
EASY = "Universities must change how they work to use new technology. This is hard and it costs money."
SRC = ("Universities need to change the way they are organised so that they can make good use of new technology, "
       "even though this is difficult and expensive for many departments.")


class FakeModel:
    def __init__(self, outputs):
        self.outputs, self.calls = list(outputs), []

    def generate(self, messages, temperature, max_new_tokens, seed=None):
        self.calls.append((messages, temperature))
        return self.outputs.pop(0) if len(self.outputs) > 1 else self.outputs[0]


@pytest.fixture
def fake(monkeypatch):
    def make(outputs):
        fm = FakeModel(outputs)
        monkeypatch.setenv("WA_NO_MODEL", "0")
        monkeypatch.setattr(RW.LocalModel, "get", classmethod(lambda cls, name: fm))
        return fm
    return make


def test_harder_detection():
    base = RW.metrics(SRC)
    assert RW.harder(RW.metrics(HARD), base)
    assert not RW.harder(RW.metrics(EASY), base)


def test_readability_retry_then_keep_most_readable(fake):
    fm = fake([HARD, EASY])
    r = RW.rewrite(SRC, tone="formal", strength="full", seed=1)
    assert r["text"].startswith("Universities must change")
    assert r["readability"]["retries"] == 1
    assert len(fm.calls) == 2
    assert "EASIER to read" in fm.calls[1][0][0]["content"]
    assert fm.calls[1][1] <= 0.3  # plainer retry runs cooler
    assert r["readability"]["after"]["flesch_reading_ease"] > r["readability"]["before"]["flesch_reading_ease"]


def test_readability_max_two_retries_and_best_kept(fake):
    fm = fake([HARD])  # model keeps returning hard text
    r = RW.rewrite(SRC, tone="academic", strength="full", seed=1, plain_words=False)
    assert len(fm.calls) == 3 and r["readability"]["retries"] == 2
    assert "local" in r["backends"]


def test_readability_check_can_be_disabled(fake):
    fm = fake([HARD])
    RW.rewrite(SRC, strength="full", readability_check=False, plain_words=False)
    assert len(fm.calls) == 1


def test_rewrite_returns_metrics_and_keeps_reference_list():
    t = "We utilize tools in order to learn (Moyo, 2023).\n\nReferences\nMoyo, T. (2023). Utilize this. Harare: Press."
    r = RW.rewrite(t, seed=1)
    assert r["text"].endswith("References\nMoyo, T. (2023). Utilize this. Harare: Press.")
    assert r["text"].startswith("We use tools to learn (Moyo, 2023).")
    rb = r["readability"]
    assert {"before", "after", "retries"} <= set(rb) and rb["before"]["words"] == 8


# ---------------------------------------------------------------- feedback: flow + conclusion
FLOW = """Mobile learning is spreading quickly across Zimbabwean universities. Students now use phones for lectures, notes and quizzes. Lecturers say mobile learning reaches students who cannot come to campus.

However, connectivity is still a problem for mobile learning. Data bundles are expensive and networks drop in rural areas. Many students only connect at night when data is cheaper.

The cafeteria menu changed last term. Prices for rice and beans went up. The queue at lunch is now much longer than before.

This shows that more work is needed. Universities could negotiate zero-rated data for their learning platforms. Government could also expand rural network coverage. Students would then learn more consistently.

Football."""


def _titles(fb, cat):
    return [i["title"] for i in fb["issues"] if i["category"] == cat]


def test_flow_checks():
    fb = analyse(FLOW, citation_style="off")
    flow = _titles(fb, "flow")
    assert "Abrupt transition" in flow
    assert "Missing topic sentence?" in flow  # paragraph opening with "This shows..."
    long_p = " ".join(["Students use the platform every day for coursework and reading."] * 12)
    assert any(t.startswith("Paragraph too long") for t in _titles(analyse(long_p + "\n\nEnd here now.", citation_style="off"), "flow"))
    short = "First paragraph has two sentences. It is fine.\n\nLonely line in the middle here.\n\nLast paragraph has two sentences. It closes."
    assert "Paragraph too short" in _titles(analyse(short, citation_style="off"), "flow")


def test_conclusion_checks():
    fb = analyse(FLOW, citation_style="off")
    assert "Weak conclusion: very short" in _titles(fb, "conclusion")
    good = FLOW.replace("Football.", "In conclusion, mobile learning in Zimbabwean universities can work. Cheaper data and better rural networks would let students learn anywhere.")
    assert not _titles(analyse(good, citation_style="off"), "conclusion")
    body = FLOW.rsplit("\n\n", 1)[0]
    missing = body + "\n\nThe library opened a new wing with 200 seats. It has air conditioning, new lights for evening study and a quiet room for group work on weekends."
    assert "Missing conclusion?" in _titles(analyse(missing, citation_style="off"), "conclusion")


# ---------------------------------------------------------------- citations
APA_DOC = """Mobile learning helps students (Moyo, 2023). As Banda et al. (2021) note, access matters (Ncube and Dube, 2019, page 4). Chari & Sithole (2020) disagree (Smith 2018).

References
Banda, R., Moyo, T. and Phiri, K. (2021). Connectivity in Africa. Journal of ICT, 4(2), 1-10. doi:10.1234/abc
Moyo, T. (2023). Students and tools. Harare: UZ Press.
Chari, L. (2020) Old book. London: X.
Zulu, P. (2017). Unused paper. Journal of Things."""


def test_apa_checks():
    issues, info = cite_check(APA_DOC, "apa")
    t = [i["title"] for i in issues]
    assert info["in_text"] == 5 and info["references"] == 4
    for want in ("APA: use '&' inside brackets", "Page number format", "Use 'and' in running text", "APA: comma before the year",
                 "APA: DOI as a link", "APA: '&' before last author", "APA: (Year). after authors", "Reference list not in A\u2013Z order",
                 "Citation not in reference list", "Reference never cited"):
        assert want in t, want
    unmatched = [APA_DOC[i["start"]:i["end"]] for i in issues if i["title"] == "Citation not in reference list"]
    assert sorted(unmatched) == ["(Ncube and Dube, 2019, page 4)", "(Smith 2018)"]
    never = [i for i in issues if i["title"] == "Reference never cited"]
    assert len(never) == 1 and APA_DOC[never[0]["start"]:].startswith("Zulu")


HARVARD_DOC = """Access is uneven (Moyo and Banda, 2021). Costs matter (Dube & Ncube, 2019).

Reference list
Dube, S. and Ncube, P. (2019) Data costs in Zimbabwe. Harare: Sapes.
Moyo, T. and Banda, R. (2021) Rural access. Available at: https://example.org/rural (Accessed: 3 May 2026).
Phiri, K. (2020) Online notes. https://example.org/notes"""


def test_harvard_checks_and_auto_detect():
    issues, info = cite_check(HARVARD_DOC, "auto")
    assert info["style"] == "harvard"
    t = [i["title"] for i in issues]
    assert "Harvard: use 'and'" in t
    assert "Harvard: 'Available at:' and access date" in t
    assert "Reference never cited" in t
    assert "Citation not in reference list" not in t
    assert "Harvard: no full stop after (Year)" not in t


def test_no_reference_list_flag_and_clean_doc():
    issues, _ = cite_check("Phones help (Moyo, 2023).", "apa")
    assert [i["title"] for i in issues] == ["No reference list found"]
    clean = "Phones help (Moyo, 2023).\n\nReferences\nMoyo, T. (2023). Phones and learning. Harare: UZ Press."
    assert cite_check(clean, "apa")[0] == []


def test_feedback_includes_citations_and_skips_reference_list_for_style():
    fb = analyse(APA_DOC, citation_style="apa")
    assert fb["counts"]["citation"] >= 8 and fb["citations"]["style_name"] == "APA 7"
    body_end = split_references(APA_DOC)[1]
    assert all(i["start"] < body_end for i in fb["issues"] if i["category"] != "citation")
    assert "citation" in fb["category_help"]
    assert not analyse(APA_DOC, citation_style="off")["counts"].get("citation")


# ---------------------------------------------------------------- Groq preset / env
def test_groq_env_key_used_when_no_key_saved(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    s = config.load()
    assert s["api_key"] == "gsk_test" and s["key_source"] == "GROQ_API_KEY" and s["use_api"] is True
    assert s["api_base"] == "https://api.groq.com/openai/v1" and s["api_model"] == "llama-3.3-70b-versatile"
    pub = config.public(s)
    assert pub["api_key"] == "********" and pub["groq_env"] is True
    config.save({"use_api": False})
    assert config.load()["use_api"] is False  # an explicit choice wins
    config.save({"api_key": "sk-own", "api_base": "https://api.openai.com/v1", "api_model": "gpt-4o-mini"})
    assert config.load()["api_key"] == "sk-own"  # a saved key wins over the env var


def test_groq_preset_save():
    s = config.save({"preset": "groq", "api_key": "gsk_x", "use_api": True})
    assert s["api_base"] == "https://api.groq.com/openai/v1" and s["api_model"] == "llama-3.3-70b-versatile"
    assert "groq" in config.public()["presets"]


# ---------------------------------------------------------------- API
def test_api_plainwords_feedback_style_and_rewrite_metrics():
    from app.main import app
    c = TestClient(app)
    w = c.get("/api/plainwords").json()["words"]
    assert w["utilise"] == "use"
    assert c.put("/api/plainwords", json={"words": {"commence": "start"}}).json()["words"] == {"commence": "start"}
    assert c.put("/api/plainwords", json={"words": {"x": 1}}).status_code == 400
    assert len(c.post("/api/plainwords/reset", json={}).json()["words"]) > 50
    fb = c.post("/api/feedback", json={"text": HARVARD_DOC, "citation_style": "harvard"}).json()
    assert fb["citations"]["style"] == "harvard"
    assert c.post("/api/readability", json={"text": "The cat sat. The dog ran."}).json()["sentences"] == 2
    import time
    jid = c.post("/api/rewrite", json={"text": SRC, "plain_words": True, "readability_check": True}).json()["job_id"]
    for _ in range(100):
        j = c.get(f"/api/jobs/{jid}").json()
        if j["status"] == "done":
            break
        time.sleep(0.05)
    assert "readability" in j["result"] and j["result"]["options"]["plain_words"] is True
    s = c.post("/api/settings", json={"preset": "groq", "api_key": "k"}).json()
    assert s["api_base"].startswith("https://api.groq.com")


def test_tone_scoped_replace_rules():
    rules = R.default_rules()
    out, _ = R.apply_replacements("Students use lots of tech stuff.", rules, tone="academic", rng=__import__("random").Random(0))
    assert "tech" not in out.split() and "stuff" not in out and "lots of" not in out
    out, _ = R.apply_replacements("Students use lots of tech stuff.", rules, tone="friendly")
    assert out == "Students use lots of tech stuff."


def test_data_heavy_and_quote_sentences_are_kept_out_of_model():
    parts = RW.chunk_paragraph("Phones help. A 2022 survey of 1,200 students found 68% used them (Moyo, 2023). Data is costly.")
    assert parts[1] == ("A 2022 survey of 1,200 students found 68% used them (Moyo, 2023).", True)
    assert parts[0] == ("Phones help.", False) and parts[2] == ("Data is costly.", False)


def test_much_higher_reading_ease_is_not_called_harder():
    base = {"fre": 40.0, "avg": 10.0}
    assert not RW.harder({"fre": 90.0, "avg": 12.0}, base)
    assert RW.harder({"fre": 42.0, "avg": 12.0}, base)
    assert RW.harder({"fre": 30.0, "avg": 8.0}, base)
