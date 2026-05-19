# ingestion/collect/

Corpus acquisition and manifest validation. The "is my corpus actually here" stage of the pipeline.

## What lives here

- **`schema.py`** — Pydantic models for `sources.yaml`. Strict validation rules: lowercase-snake filenames, valid SHA-256 hex, year ranges, the relevance-status enum, uniqueness of folder numbers and act IDs.
- **`verify_corpus.py`** — The validator. Reads `sources.yaml`, checks every declared file exists at its expected path, computes (or verifies) SHA-256 hashes, detects orphan files in `data/` that aren't in the manifest, and reports a typed summary.

The actual corpus collection is **manual** — you download judgments and acts yourself, following the playbook below. There is no automated scraper. Reasons in `../../design.md` and earlier conversation: small static corpus, Indian Kanoon TOS, reproducibility.

## Methodology

### Why this approach

We're building a focused robbery RAG system. The corpus needs three things to be defensible:

1. **Authoritative sources.** Statutes from indiacode.nic.in (the official government repository). Judgments from Indian Kanoon (the de facto standard for Indian case-law research).
2. **Curated but not cherry-picked.** Filter Indian Kanoon by `"robbery" + "conviction"` across Supreme Court and major High Courts. Use Indian Kanoon's "Most Cited" sort to surface the doctrinally important cases first. Aim for 30-50 judgments after relevance classification.
3. **Auditable.** Every source is listed in `sources.yaml` with citation, court, year, URL, and a SHA-256 hash. Anyone cloning the repo can reproduce the corpus exactly.

### What we're NOT doing

- No automated scraping. Indian Kanoon's TOS objects to bulk pulls; manual research downloads are explicitly permitted.
- No "all robbery cases ever." Filtered, classified, and capped at ~50.
- No editorial cherry-picking to confirm a thesis. The Gemini relevance classifier in Batch 1.2 provides a documented filter, and rejected cases stay in `sources.yaml` as an audit trail.
- No live ingestion. The corpus is committed to git; ChromaDB is built once locally and baked into the Docker image.

### Quality controls

- **Spot-check** of 5-10 sections against indiankanoon.org and prsindia.org for statute parsing accuracy.
- **Filename normalization** enforced by `scripts/normalize_filenames.py` and `verify_corpus.py`.
- **Pairing rule** — each judgment folder must have exactly one HTML and one PDF with matching base names.
- **Hash pinning** — once verified, SHA-256 hashes live in `sources.yaml`. Future runs detect drift.
- **Human review** of the eval set (see `eval/REVIEW_NOTES.md` in Batch 1.5).

## Download Playbook

You'll do this once. Budget: ~2-3 focused hours.

### Step 1: Download the bare acts (10 minutes)

Three PDFs, direct from indiacode.nic.in. Run from the repo root:

```bash
cd data
curl -L -o bns_2023.pdf  "https://www.indiacode.nic.in/bitstream/123456789/20062/1/a2023-45.pdf"
curl -L -o ipc_1860.pdf  "https://www.indiacode.nic.in/bitstream/123456789/4219/1/THE-INDIAN-PENAL-CODE-1860.pdf"
curl -L -o bnss_2023.pdf "https://www.indiacode.nic.in/bitstream/123456789/20340/1/bnss,_2023.pdf"
cd ..
```

If indiacode is slow, the fallback URL for BNSS is the Ministry of Home Affairs copy: `https://www.mha.gov.in/sites/default/files/2024-04/250884_2_english_01042024.pdf`.

### Step 2: Search Indian Kanoon (30 minutes of setup)

1. Open https://indiankanoon.org
2. Search: `"robbery" "conviction"`
3. Open the left sidebar filters:
   - Court: check **Supreme Court of India** and a few major High Courts (Delhi, Bombay, Madras, Calcutta, Allahabad)
   - Sort by: **Most cited** (this is the single most useful filter)
4. Optionally narrow by year if the result count is overwhelming

### Step 3: Download cases one at a time (90-120 minutes)

For each case you want to include:

1. Open the case page in a new tab
2. **Read the first paragraph and the holding.** The two-question test:
   - Is this _primarily_ about robbery (or dacoity)?
   - Did the court decide a robbery question?
     If the answer to either is no, close the tab and move on. (The relevance classifier in Batch 1.2 will catch some of these later, but a quick human screen here saves classifier cycles and improves quality.)
3. If yes:
   - Pick the next available folder number: `mkdir data/<NN>` (e.g., `data/04`)
   - **Save the HTML:** `File → Save Page As → "Webpage, HTML Only"` into `data/<NN>/`
   - **Save the PDF:** click Indian Kanoon's PDF download button, save into `data/<NN>/`
   - Add a stanza to `sources.yaml` (copy the schema from a worked example, update fields)

### Step 4: Normalize filenames (1 minute)

```bash
python scripts/normalize_filenames.py            # dry run
python scripts/normalize_filenames.py --apply    # actually rename
```

This handles the inevitable browser-saved names like `Phool Kumar vs Delhi Administration on 13 March, 1975.html` and turns them into `phool_kumar_vs_delhi_administration_on_13_march_1975.html`. The script also reports any folder where HTML and PDF base names don't match — if Indian Kanoon's PDF download gave you a numeric ID (`1212588.pdf`), you'll need to rename it manually to match the HTML.

After renaming, update the `html_filename` and `pdf_filename` fields in `sources.yaml` to match.

### Step 5: Verify and compute hashes

```bash
python ingestion/collect/verify_corpus.py --write-hashes
```

This:

- Validates `sources.yaml` against the Pydantic schema (catches typos, invalid enums, malformed citations)
- Confirms every declared file exists
- Confirms HTML and PDF base names pair correctly inside each folder
- Computes SHA-256 hashes for every file and writes them back into `sources.yaml`
- Reports any orphan files (in `data/` but not in the manifest) — these are usually leftover downloads you forgot to delete

On a subsequent run **without** `--write-hashes`, hashes are compared and drift is reported. This is the integrity check for CI / pre-commit.

### Step 6: (Batch 1.2) Run the relevance classifier

Once `verify_corpus.py` is clean:

```bash
python ingestion/classify/run_classifier.py
```

This runs each judgment through Gemini, scores it for relevance, and updates `sources.yaml`. Cases scoring below 0.6 get `relevance_classifier_status: rejected` and don't make it into the index. Cases between 0.6 and 0.8 are flagged `needs-review` for you to manually accept or reject.

## Adding a New Case Later

When you find another case worth including:

1. `mkdir data/<next_NN>`
2. Save HTML and PDF into the folder
3. Add a stanza to `sources.yaml` with `relevance_classifier_status: pending`
4. `python scripts/normalize_filenames.py --apply`
5. `python ingestion/collect/verify_corpus.py --write-hashes`
6. `python ingestion/classify/run_classifier.py` (runs only on pending entries)
7. Bump `corpus_version` in `sources.yaml`
8. Bump `CORPUS_VERSION` in `backend/app/constants.py` (matching string)
9. Rebuild the index: `make ingest` (Batch 2)
10. Commit `data/<NN>/`, the updated `sources.yaml`, and the bumped versions

## Sources Manifest Schema — Quick Reference

Full schema in `schema.py`. The shape:

```yaml
corpus_version: "2026.05.14" # bump on every corpus change
schema_version: "1"

acts:
  - act_id: bns_2023 # lowercase snake, unique
    act_name: "..."
    short_name: "BNS"
    filename: bns_2023.pdf # must be normalized
    source_url: "..."
    retrieved_date: 2026-05-14
    sha256: null # populated by verify_corpus.py --write-hashes

judgments:
  - folder: "01" # zero-padded number, unique, matches data/01/
    case_id: phool_kumar_... # lowercase snake
    case_name: "..."
    citation: "..."
    court: "..."
    year: 1975
    primary_section: "397 IPC"
    other_sections: ["392 IPC"]
    outcome: conviction-upheld # enum: conviction-upheld | conviction-set-aside | bail-granted | bail-denied | other
    indian_kanoon_url: "..."
    indian_kanoon_doc_id: "..." # optional
    html_filename: ... # normalized, .html
    pdf_filename: ... # normalized, .pdf, same base name as html
    retrieved_date: 2026-05-14
    html_sha256: null
    pdf_sha256: null
    relevance_classifier_status: pending # enum: pending | approved | rejected | needs-review
    relevance_score: null # 0.0-1.0, populated by classifier
    classifier_reasoning: null
    manual_review_notes: "..." # optional human notes
```

## Running the Verifier in CI

The backend CI workflow runs `verify_corpus.py` on every push touching `sources.yaml` or `data/`. A failed verifier blocks merge. This protects against silently-broken manifests landing on `main`.

(The actual CI integration ships with Batch 1.2 when ingestion gets its own requirements.txt — until then, the `ingestion-check` job in `.github/workflows/backend-ci.yml` no-ops with a notice.)
