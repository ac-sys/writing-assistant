# Writing Assistant (self-hosted editing aid)

Rewrites stiff, wordy or robotic prose (including AI-drafted text) into clear, natural, varied English, and
gives line-by-line style feedback. Runs on an ordinary Windows PC (CPU only) and works offline once the
model has downloaded. Your own **style rules** steer both the rewrite and the feedback.

It is an **editing aid**. It has no AI-detector scoring, no "beat the detector" loop and no hidden-character
tricks. Always read the result before you use it, and follow your institution's rules on disclosing AI and
editing tools.

## What's new in v1.1
- **Readability check.** After each model rewrite the app compares Flesch reading ease and average sentence
  length with your original. If the draft is harder to read (reading ease more than 3 points lower, or longer
  sentences without a clear reading-ease gain), it retries up to 2 times with a stronger "plain, short words
  and sentences" instruction at a lower temperature, then keeps the most readable valid version. The Rewrite tab
  shows a before/after readability table.
- **Plain-words pass.** Complex words are swapped for plain ones from an editable list
  (`data/plain_words.json`, also editable under **Style rules → Plain words**), and very long sentences are split
  at safe points (semicolons, ", but", ", so", ", and" + a new subject). Quotes and citations are never touched.
- **Better prompts for the small local model.** It now gets few-shot examples, a "plain words, but keep precise
  terms" instruction, a register line per tone, and lower temperatures for the friendly and simple tones.
  Sentences that hold a direct quotation or two or more figures are kept out of the model (rules and plain
  words only), so quotes and statistics stay exact. A dropped bracketed citation such as `(Moyo, 2023)` is put back.
- **New feedback checks:** paragraph flow (too short or long paragraphs, missing topic sentence, abrupt
  transitions), weak or missing conclusion, and a **citation checker for APA 7 and Harvard**.
- **Easy Groq setup:** a preset in Settings, and the app reads a `GROQ_API_KEY` environment variable.
- Replace rules can be limited to certain tones (`"tones": ["academic","formal"]`). New defaults turn informal
  words such as "stuff", "tech" and "lots of" into formal ones in the academic and formal tones.
- The reference list (anything under a "References", "Reference list" or "Bibliography" heading) is never rewritten.

## Features
**Rewrite**
- Paste text or upload **DOCX, PDF or TXT**.
- Tone: academic, formal, friendly, simple. Strength: light edit or full rewrite. Keep British English toggle.
- Side-by-side word diff (deletions red, insertions green), editable result, copy, download as .docx,
  "Get feedback on result" button.
- **Facts are guarded.** Citations such as `(Moyo, 2023)`, `Banda et al. (2021)` and `[3]`, URLs, e-mails and
  every number must survive, or that part is rejected and the next engine is tried. Sentences that contain a
  direct quotation are not sent to the model, so the quoted words never change.
- Engines, in order: (1) an optional OpenAI-compatible API (OpenAI, xAI Grok, Groq, Ollama...),
  (2) the local model, (3) a rules-only pass. If one fails, the next is used automatically.

**Feedback**
- Stock phrases, wordy phrases, filler, clichés (all driven by your editable rules).
- Repetition: repeated words close together, repeated 3-word phrases, sentences that all start the same way.
- Rhythm: very uniform sentence lengths, runs of same-length sentences, long sentences.
- Passive voice (and heavy passive overall), connective overuse ("Moreover, Furthermore..."), lists-of-three
  overuse, very long paragraphs, missing paragraph breaks, many one-sentence paragraphs.
- Paragraph flow: paragraphs that are too long (over 200 words or 9 sentences) or too short (one short
  sentence in the middle of the text), a missing topic sentence (the paragraph opens with "This/It/However..."
  or the first sentence shares no key words with the rest), and abrupt transitions (the next paragraph shares no
  key words with the previous one and has no linking word).
- Conclusion: very short, ending on a question, missing (no summing-up signal and little link to the opening),
  or bringing in new cited evidence.
- Citations (choose Auto-detect, APA 7, Harvard or Off): in-text format ("&" vs "and", comma before the year,
  "et al." rules, page format "p. 4"), reference-list format ("(2021)." for APA, "(2021) Title" and
  "Available at: ... (Accessed: ...)" for Harvard, DOI as https://doi.org/..., A-Z order, missing year), in-text
  citations with no matching reference, and references never cited. These are heuristics: check edge cases
  against your style guide.
- Readability: Flesch Reading Ease, Flesch-Kincaid grade, Gunning Fog, average sentence length, length
  variation, lexical variety (MATTR), reading time.
- Inline colour highlights. Hover for the explanation and fix, and click a fix button to apply it.

## Local model
Default: **Qwen2.5-1.5B-Instruct** (Apache-2.0, about 3 GB download, about 6-8 GB RAM). On an 8-core CPU,
150 words take about 15-25 seconds. A faster **Qwen2.5-0.5B-Instruct** (about 1 GB) can be picked in Settings.
Small local models are good at tidy-ups but weaker at deep rewrites: a "full rewrite" can blur a nuance or
over-simplify in the friendly and simple tones. "Light edit" with the academic or formal tone is the safest
local setting. For the best quality, use Groq (see below).

Measured on `samples/ai_sample.txt` with the local 1.5B model (v1.1, reading ease, higher = easier; original 31.8):
academic light 50.7, academic full 48.7, formal full 51.6, friendly full 57.2, simple full 62.3
(v1.0 reached 19.9–27.0 on the same text, i.e. it got harder to read). Full log: `samples/v11_run.txt`.

## Windows setup (one time)
Needs **Python 3.10-3.12** from python.org (tick "Add python.exe to PATH") and internet for the first setup.
1. Unzip `writing_assistant.zip`, for example to `C:\WritingAssistant`.
2. Double-click **`setup_windows.bat`**. It creates `.venv`, installs everything and downloads the model.
   You can also do it by hand in Command Prompt:
   ```
   cd C:\WritingAssistant
   python -m venv .venv
   .venv\Scripts\activate
   pip install torch --index-url https://download.pytorch.org/whl/cpu
   pip install -r requirements.txt
   python download_model.py          (or: python download_model.py --fast)
   ```
## Run
Double-click **`run_windows.bat`**, or:
```
cd C:\WritingAssistant
.venv\Scripts\activate
uvicorn app.main:app --host 127.0.0.1 --port 8200
```
Then open http://localhost:8200. Stop it with Ctrl+C. The first rewrite takes longer while the model loads.

## Optional online model (recommended: Groq, free tier)
**Easiest way (Groq):** get a free key at https://console.groq.com/keys, open Settings, choose the
**Groq** preset (base URL `https://api.groq.com/openai/v1`, model `llama-3.3-70b-versatile`), paste the key, tick
"Use online model", click **Save** and then **Test connection**.
**Or with an environment variable:** in Command Prompt run `setx GROQ_API_KEY "gsk_your_key"`, open a new
Command Prompt and start the app. If no key is saved in Settings, the app uses the Groq key automatically
(Settings shows "Using the GROQ_API_KEY environment variable"). A key saved in Settings, or an explicit
"Use online model" untick, takes priority.

Other services: Settings → "Use online model". Base URL examples: `https://api.openai.com/v1` (model `gpt-4o-mini`),
`https://api.x.ai/v1` (a Grok model), `https://api.groq.com/openai/v1` (e.g. `llama-3.3-70b-versatile`),
`http://localhost:11434/v1` for Ollama. Click **Test connection**. The key is saved in `data/settings.json`
on your PC, and your text goes to that provider. Environment variables `WA_API_BASE`, `WA_API_KEY`,
`WA_API_MODEL`, `WA_USE_API=1` and `WA_LOCAL_MODEL` override the settings.

## Writing style rules
Rules live in **`data/style_rules.json`** (created with sensible defaults on first run). Edit them in the
**Style rules** tab (add, edit, delete, enable/disable, search, import, export, restore defaults, and a live
preview), or edit the JSON file directly while the app is stopped. `docs/example_rules.json` has one example
of every type. Import it with "Import: merge".

Common keys for every rule:
| key | meaning |
|---|---|
| `id` | unique name (re-using an id replaces that rule) |
| `name` | label shown in the UI |
| `type` | `replace`, `ban`, `sentence_length`, `contractions`, `tone`, `check` |
| `enabled` | `true` / `false` |
| `applies_to` | `["rewrite"]`, `["feedback"]` or both |
| `category` | feedback colour group: `ai_stock`, `wordy`, `filler`, `cliche`, `style`, `custom`... |
| `message` | explanation shown in feedback |

Rule types:
- **replace**: `pattern` (text, or a regex if `"regex": true`), `alternatives` (list; **one is picked at
  random** each time; `""` deletes the match), `whole_word` (default true), `case_sensitive` (default false),
  optional `tones` (e.g. `["academic","formal"]`; the rule then only applies to rewrites in those tones).
  Regex alternatives can use `\1`, `\2` for captured groups. In a rewrite, replacements run after the model
  and never touch quotes or citations. In feedback, each match is flagged with the alternatives as one-click fixes.
  ```json
  {"id":"a-lot-of","name":"a lot of","type":"replace","pattern":"a lot of","alternatives":["many","plenty of"]}
  ```
- **ban**: `phrases` (list), `action` `"flag"` (feedback only, and the model is told to avoid them) or
  `"remove"` (also deleted from the rewrite output).
- **sentence_length**: `warn_words`, `max_words`, `min_variation` (sentence-length variation; lower means
  more uniform, and 0.35-0.5 is typical of lively prose), `target_min`, `target_max` (sent to the model).
- **contractions**: `mode` `"use"`, `"avoid"` or `"off"`. With "off", the friendly tone uses contractions and
  the academic and formal tones avoid them.
- **tone**: `instruction` (extra guidance sent to the rewrite model) and `tones` (e.g. `["academic"]`;
  empty = all tones).
- **check**: `pattern` (regex), `message`, `suggestion`, `min_count` (flag only if it occurs at least this many
  times), `case_sensitive`. Feedback only.

**Plain words list** (`data/plain_words.json`): a simple `{"complex": "plain"}` map used by the plain-words pass
after each rewrite. Edit it under Style rules → Plain words (one `complex = plain` per line) or in the file.
List each word form separately (`utilise`, `utilised`, `utilising`). Turn the pass off with the
"Plain-words pass" box on the Rewrite tab.

Tip: use the **Try the replace rules** box to test a new rule instantly before running a full rewrite.

## Tests
```
.venv\Scripts\activate
python -m pytest -q                                   # fast tests, no model needed
set RUN_MODEL_TESTS=1 && python -m pytest -q tests/test_model.py   # real local model (slow)
```

## API (for scripts)
`POST /api/rewrite {text,tone,strength,british,plain_words,readability_check}` (the result includes `readability.before/after`);
`POST /api/feedback {text,citation_style: auto|apa|harvard|off}`; `GET/PUT /api/plainwords`, `POST /api/plainwords/reset`;
`POST /api/readability {text}`; rewrite returns a `job_id`, poll it with `GET /api/jobs/{id}`; `POST /api/feedback {text}`;
`POST /api/extract` (file); `POST /api/export/docx {text}`; `GET/POST/PUT /api/rules`, `DELETE /api/rules/{id}`,
`POST /api/rules/{id}/toggle`, `GET /api/rules/export`, `POST /api/rules/import?mode=merge|replace`,
`POST /api/rules/reset`, `POST /api/rules/test`; `GET/POST /api/settings`, `POST /api/settings/test`.

## Files
`app/` (FastAPI backend: `rewrite.py`, `feedback.py`, `rules.py`, `protect.py`, `spelling.py`), `static/index.html`
(UI), `app/citations.py` (APA/Harvard checker), `app/plain.py` (plain words + sentence splitting),
`app/default_plain_words.json`, `data/` (your rules, plain words and settings, created on first run), `samples/`, `docs/`, `tests/`.
