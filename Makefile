# Top-level Makefile.
#
# All real targets live in `ingestion/Makefile`; this file forwards to it.
# That keeps the ingestion pipeline self-contained (you can `cd ingestion &&
# make ingest` if you want) while letting `make <target>` from the repo
# root also work.
#
# When Batch 3+ adds backend/frontend Makefiles, this file will forward to
# them too (e.g. `make backend-test`).

.DEFAULT_GOAL := help

.PHONY: help install ingest resume verify clean clean-index clean-cache \
        classify normalize chunk embed build-bm25 build-chroma

help:
	@$(MAKE) -C ingestion help

# Forward every ingestion target. New targets in ingestion/Makefile only need
# to be listed in .PHONY above and added to this pattern.
install ingest resume verify clean clean-index clean-cache \
classify normalize chunk embed build-bm25 build-chroma:
	@$(MAKE) -C ingestion $@