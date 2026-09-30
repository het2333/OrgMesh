# Chinese Retrieval Evaluation

This synthetic corpus has eight documents and twelve questions. It contains no real employee data.
It checks Chinese terms, abbreviations, mixed languages, and questions with multiple relevant documents.
The PDF fixture tests separately check native Chinese text, tables, scans, and mixed PDFs.

## Run a live evaluation

1. Upload `corpus/*.txt` through an admin file connector. Wait for indexing to finish.
2. Create a JSON map from corpus IDs to indexed document IDs. Use file stems as corpus IDs.
3. Save an authenticated Cookie header value in a file outside the repository. Or set `ONYX_API_KEY`.
4. Run the script through the frontend origin. Do not use the backend origin.

```bash
PYTHONPATH=backend .venv/bin/python backend/scripts/evaluate_chinese_retrieval.py \
  --corpus tools/evals/chinese/queries.json \
  --base-url http://localhost:3000 \
  --document-map /tmp/chinese-document-map.json \
  --cookie-file /tmp/onyx-cookie.txt \
  --hybrid-alpha 0 --k 1 5 10 --output /tmp/chinese-baseline.json
```

Run once with glossary expansion disabled. Then save `glossary.json` through the admin settings API.
Run again and compare Recall@1, Recall@5, Recall@10, and MRR.
The script calls the Community `/api/orgmesh/search` endpoint through the frontend. ACL checks stay active; this endpoint does not call a chat model. Alpha 0 uses keyword search; larger values use the configured local embedding model.
It deduplicates document chunks before computing document-level ranks.
Recall is the retrieved share of relevant documents, averaged across questions.
MRR uses the first relevant document within the captured result depth. Missing relevant results score zero.
The script fails on search errors or missing question rankings. It does not create success scores for unavailable services.

To score an existing capture, pass `--rankings` with JSON in `{query_id: [corpus_document_id]}` format.
Captured rankings must use the document IDs from `queries.json`.

## Model recommendations

Use `BAAI/bge-m3` as a multilingual embedding candidate. It supports Chinese and mixed-language documents.
Use `BAAI/bge-reranker-v2-m3` as a multilingual reranking candidate.
Both models need the configured model server and sufficient compute.
Use the existing embedding settings API to create a new index. Reindex before switching embedding dimensions or models.
Use `cjk` as the OpenSearch text analyzer for a Chinese-heavy corpus. Existing index mappings require a new index.
Evaluate the current model first. Compare the candidate models on the same corpus, settings, and account.
These are candidates, not measured quality claims. Local synthetic keyword results are recorded in `plans/chinese-live-results.json`; reranker candidates have not been measured.

## Local PDF OCR

Set `PDF_OCR_ENABLED=true`. Install Tesseract with `chi_sim` and `eng` language data in the backend runtime.
OCR processes only image pages with fewer than 24 native text characters. It preserves existing text.
Automatic layout retries block layout when OCR returns fewer than 24 text characters.
Both attempts share the same page deadline, including rendering.
The hard limits are 20 OCR pages, 50 MiB input, 8 million rendered pixels, and 15 seconds per page.
The document OCR deadline is 90 seconds. The outer PDF extraction deadline also applies.
The `PDF_OCR_MAX_PAGES`, `PDF_OCR_MAX_FILE_BYTES`, `PDF_OCR_MAX_RENDER_PIXELS`,
`PDF_OCR_PAGE_TIMEOUT_SECONDS`, and `PDF_OCR_DOCUMENT_TIMEOUT_SECONDS` variables can lower these limits.
Missing language data, OCR errors, or limits can leave scanned text unavailable. Check extraction logs before indexing scans.
