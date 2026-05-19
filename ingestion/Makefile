# Ingestion pipeline Makefile.
#
# Wraps the Python orchestrator and individual steps for convenience.
# All targets are safe to re-run; the orchestrator skips up-to-date steps.
#
# Repo paths containing spaces (e.g. "RAG Crime") work because every use of
# $(ROOT) is double-quoted. Make does NOT auto-quote variables in recipes;
# `cd $(ROOT)` would split on the space. `cd "$(ROOT)"` does the right thing.

PY := python3
ROOT := $(shell git rev-parse --show-toplevel 2>/dev/null || pwd)

.PHONY: help install ingest verify clean clean-index clean-cache classify normalize chunk embed build-bm25 build-chroma resume

help:
	@echo "Targets:"
	@echo "  install        Install pinned Python deps for the ingestion pipeline"
	@echo "  ingest         Run the full pipeline (skips up-to-date steps)"
	@echo "  resume         Re-run after a quota stop; same as 'ingest'"
	@echo "  verify         Run only the verify_index sanity checks"
	@echo "  classify       Run only the relevance classifier"
	@echo "  normalize      Run only the act+judgment normalization"
	@echo "  chunk          Run only the chunker"
	@echo "  embed          Run only the embedder (calls Gemini)"
	@echo "  build-bm25     Build only the BM25 index"
	@echo "  build-chroma   Build only the Chroma index (requires embeddings)"
	@echo "  clean-index    Remove built indices (chroma_db, bm25_index)"
	@echo "  clean-cache    Remove the embedding cache (forces re-embed)"
	@echo "  clean          clean-index + clean-cache + chunks.jsonl + normalized.jsonl"

install:
	cd "$(ROOT)" && $(PY) -m pip install -r ingestion/requirements.txt

ingest:
	cd "$(ROOT)" && $(PY) -m ingestion.run_ingestion

resume: ingest

verify:
	cd "$(ROOT)" && $(PY) -m ingestion.index.verify_index

classify:
	cd "$(ROOT)" && $(PY) -m ingestion.classify.run_classifier

normalize:
	cd "$(ROOT)" && $(PY) -m ingestion.normalize.parse_judgments

chunk:
	cd "$(ROOT)" && $(PY) -m ingestion.chunk.run_chunking

embed:
	cd "$(ROOT)" && $(PY) -m ingestion.embed.embed_chunks

build-bm25:
	cd "$(ROOT)" && $(PY) -m ingestion.index.build_bm25

build-chroma:
	cd "$(ROOT)" && $(PY) -m ingestion.index.build_chroma --reset

clean-index:
	rm -rf "$(ROOT)/ingestion/data/chroma_db"
	rm -rf "$(ROOT)/ingestion/data/bm25_index"
	rm -f "$(ROOT)/ingestion/data/bm25_chunk_ids.jsonl"

clean-cache:
	rm -f "$(ROOT)/ingestion/data/embedding_cache.sqlite"
	rm -f "$(ROOT)/ingestion/data/embeddings.jsonl"

clean: clean-index clean-cache
	rm -f "$(ROOT)/ingestion/data/chunks.jsonl"
	rm -f "$(ROOT)/ingestion/data/normalized.jsonl"