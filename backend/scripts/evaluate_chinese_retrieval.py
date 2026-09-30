#!/usr/bin/env python3
"""Evaluate a captured run or query the authenticated frontend search API."""

import argparse
import json
import os
import time
from pathlib import Path
from urllib.parse import urlsplit

import requests
from pydantic import TypeAdapter

from onyx.evals.chinese_retrieval.metrics import evaluate_rankings
from onyx.evals.chinese_retrieval.models import EvaluationCorpus


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--rankings", type=Path, help="Captured {query_id: [corpus_doc_id]} JSON"
    )
    source.add_argument(
        "--base-url", help="Frontend origin, for example http://localhost:3000"
    )
    parser.add_argument(
        "--document-map", type=Path, help="{corpus_doc_id: indexed_document_id} JSON"
    )
    parser.add_argument(
        "--cookie-file", type=Path, help="File containing the Cookie header value"
    )
    parser.add_argument("--hybrid-alpha", type=float, default=0.0)
    parser.add_argument("--k", type=int, nargs="+", default=[1, 5, 10])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.k or any(cutoff <= 0 for cutoff in args.k):
        parser.error("--k values must be positive")
    if not 0 <= args.hybrid_alpha <= 1:
        parser.error("--hybrid-alpha must be between 0 and 1")
    corpus = EvaluationCorpus.model_validate_json(args.corpus.read_text())
    started = time.monotonic()
    if args.rankings:
        rankings = TypeAdapter(dict[str, list[str]]).validate_json(
            args.rankings.read_text(), strict=True
        )
        mode = "captured"
    else:
        if not args.document_map:
            parser.error(
                "Live evaluation requires --document-map after indexing the corpus"
            )
        frontend_url = urlsplit(args.base_url)
        if (
            frontend_url.scheme not in {"http", "https"}
            or not frontend_url.netloc
            or frontend_url.username
            or frontend_url.password
            or frontend_url.query
            or frontend_url.fragment
            or frontend_url.path not in {"", "/"}
        ):
            parser.error("--base-url must be an HTTP or HTTPS frontend origin")
        document_map = TypeAdapter(dict[str, str]).validate_json(
            args.document_map.read_text(), strict=True
        )
        expected_ids = {
            document_id
            for query in corpus.queries
            for document_id in query.relevant_document_ids
        }
        if not expected_ids.issubset(document_map):
            parser.error("Document map must contain every relevant corpus document")
        if len(set(document_map.values())) != len(document_map):
            parser.error(
                "Each corpus document must map to a different indexed document"
            )
        reverse_map = {
            indexed_id: corpus_id for corpus_id, indexed_id in document_map.items()
        }
        headers = {"Content-Type": "application/json"}
        if args.cookie_file:
            headers["Cookie"] = args.cookie_file.read_text().strip()
        elif api_key := os.environ.get("ONYX_API_KEY"):
            headers["Authorization"] = f"Bearer {api_key}"
        else:
            parser.error("Set ONYX_API_KEY or provide --cookie-file")
        rankings = {}
        for query in corpus.queries:
            response = requests.post(
                args.base_url.rstrip("/") + "/api/orgmesh/search",
                json={
                    "query": query.query,
                    "limit": max(args.k),
                    "hybrid_alpha": args.hybrid_alpha,
                },
                headers=headers,
                timeout=120,
                allow_redirects=False,
            )
            response.raise_for_status()
            if response.is_redirect:
                raise RuntimeError(
                    "Search returned a redirect; check frontend origin and authentication"
                )
            payload = response.json()
            if payload.get("error"):
                raise RuntimeError(
                    f"Search failed for query {query.id}: {payload['error']}"
                )
            rankings[query.id] = [
                reverse_map.get(document["document_id"], document["document_id"])
                for document in payload["results"]
            ]
        mode = "live_frontend_api"
    metrics = evaluate_rankings(corpus.queries, rankings, args.k)
    report = {
        "mode": mode,
        "corpus": str(args.corpus),
        "hybrid_alpha": args.hybrid_alpha if args.base_url else None,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "metrics": metrics.model_dump(mode="json"),
        "rankings": rankings,
        "mrr_depth": max(
            (len(set(ranking)) for ranking in rankings.values()), default=0
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report["metrics"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
