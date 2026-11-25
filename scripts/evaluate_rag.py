from __future__ import annotations

import argparse
import asyncio
import json
import re
import statistics
import time
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import httpx

CHINESE_DIGITS = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}
CHINESE_UNITS = {"十": 10, "百": 100, "千": 1000, "万": 10000}
NUMBER_WITH_UNIT_PATTERN = re.compile(
    r"(?P<number>[零〇一二三四五六七八九十百千万两]+)"
    r"(?P<unit>个?工作日内?|个?小时|学时|个月|年|天|日|周|次|级|项|条|人|分|元|万元|%|％)"
)
ARABIC_NUMBER_WITH_UNIT_PATTERN = re.compile(
    r"(?P<number>\d+(?:\.\d+)?)"
    r"(?P<unit>个?工作日内?|个?小时|学时|个月|年|天|日|周|次|级|项|条|人|分|元|万元|%|％)"
)


def chinese_number_to_int(value: str) -> int:
    total = 0
    section = 0
    number = 0
    for character in value:
        if character in CHINESE_DIGITS:
            number = CHINESE_DIGITS[character]
            continue
        unit = CHINESE_UNITS[character]
        if unit == 10000:
            section = (section + number) * unit
            total += section
            section = 0
        else:
            section += (number or 1) * unit
        number = 0
    return total + section + number


def normalize_numbers(value: str) -> str:
    def replace(match: re.Match[str]) -> str:
        number = chinese_number_to_int(match.group("number"))
        unit = match.group("unit").replace("工作日内", "工作日")
        unit = unit.replace("个工作日", "工作日")
        return f"{number}{unit}"

    def replace_arabic(match: re.Match[str]) -> str:
        unit = match.group("unit").replace("工作日内", "工作日")
        unit = unit.replace("个工作日", "工作日")
        return f"{match.group('number')}{unit}"

    value = NUMBER_WITH_UNIT_PATTERN.sub(replace, value)
    return ARABIC_NUMBER_WITH_UNIT_PATTERN.sub(replace_arabic, value)


def compact_text(value: str) -> str:
    value = re.sub(r"\[E\d+\]", "", value)
    value = normalize_numbers(value)
    value = value.replace("％", "%")
    value = re.sub(r"[*`_#>|]", "", value)
    return re.sub(r"[^\w\u4e00-\u9fff%]+", "", value).lower()


def keyword_hits(answer: str, keywords: list[str]) -> list[str]:
    normalized_answer = compact_text(answer)
    return [keyword for keyword in keywords if compact_text(keyword) in normalized_answer]


def mean(values: list[float]) -> float:
    return statistics.fmean(values) if values else 0.0


def failure_reason(response_data: dict[str, Any]) -> str:
    reason = str(response_data.get("abstain_reason", "")).strip()
    if reason:
        return reason
    if not response_data.get("citations"):
        return "missing_citation"
    return ""


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(round((len(ordered) - 1) * fraction), len(ordered) - 1)
    return ordered[index]


async def evaluate_question(
    client: httpx.AsyncClient,
    item: dict[str, Any],
    semaphore: asyncio.Semaphore,
    retries: int,
) -> dict[str, Any]:
    queued_at = time.perf_counter()
    response_data: dict[str, Any] | None = None
    error: str | None = None

    async with semaphore:
        started = time.perf_counter()
        for attempt in range(retries + 1):
            try:
                response = await client.post(
                    "/api/chat",
                    json={"message": item["question"], "conversation_id": None},
                )
                response.raise_for_status()
                response_data = response.json()
                break
            except (httpx.HTTPError, ValueError) as exc:
                error = str(exc)
                if attempt < retries:
                    await asyncio.sleep(1.5 * (attempt + 1))

    latency_ms = round((time.perf_counter() - started) * 1000)
    queue_ms = round((started - queued_at) * 1000)
    if response_data is None:
        return {
            "id": item["id"],
            "type": item["type"],
            "difficulty": item["difficulty"],
            "question": item["question"],
            "expected_answer": item["answer"],
            "expected_docs": item["source_docs"],
            "expected_clauses": item["source_clauses"],
            "keywords": item["keywords"],
            "status": "error",
            "error": error,
            "queue_ms": queue_ms,
            "latency_ms": latency_ms,
        }

    answer = response_data.get("answer", "")
    citations = response_data.get("citations", [])
    citation_titles = [citation.get("title", "") for citation in citations]
    matched_docs = [title for title in item["source_docs"] if title in citation_titles]
    matched_keywords = keyword_hits(answer, item["keywords"])
    highlighted_citations = sum(
        any(
            isinstance(span.get("bbox"), list) and len(span["bbox"]) == 4
            for span in citation.get("source_spans", [])
        )
        for citation in citations
    )
    pages = [
        page
        for citation in citations
        for page in (citation.get("page_start"), citation.get("page_end"))
        if isinstance(page, int)
    ]
    retrieval_queries = response_data.get("retrieval_queries", [])
    missing_retrieval_queries = response_data.get("missing_retrieval_queries", [])
    if not isinstance(retrieval_queries, list):
        retrieval_queries = []
    if not isinstance(missing_retrieval_queries, list):
        missing_retrieval_queries = []
    subquery_evidence_rate = (
        (len(retrieval_queries) - len(missing_retrieval_queries))
        / len(retrieval_queries)
        if retrieval_queries
        else 0.0
    )

    return {
        "id": item["id"],
        "type": item["type"],
        "difficulty": item["difficulty"],
        "question": item["question"],
        "expected_answer": item["answer"],
        "actual_answer": answer,
        "expected_docs": item["source_docs"],
        "expected_clauses": item["source_clauses"],
        "keywords": item["keywords"],
        "matched_keywords": matched_keywords,
        "keyword_recall": len(matched_keywords) / len(item["keywords"]),
        "citation_titles": citation_titles,
        "matched_docs": matched_docs,
        "citation_doc_recall": len(matched_docs) / len(item["source_docs"]),
        "all_expected_docs_cited": len(matched_docs) == len(item["source_docs"]),
        "citation_count": len(citations),
        "highlighted_citations": highlighted_citations,
        "all_citations_highlighted": bool(citations) and highlighted_citations == len(citations),
        "pages": pages,
        "page_range": [min(pages), max(pages)] if pages else None,
        "evidence_sufficient": bool(response_data.get("evidence_sufficient")),
        "abstained": not bool(response_data.get("evidence_sufficient")),
        "failure_reason": failure_reason(response_data),
        "retrieval_queries": retrieval_queries,
        "missing_retrieval_queries": missing_retrieval_queries,
        "subquery_evidence_rate": subquery_evidence_rate,
        "invalid_evidence_ids": response_data.get("invalid_evidence_ids", []),
        "repair_attempts": int(response_data.get("repair_attempts", 0)),
        "retrieval_round": response_data.get("retrieval_round"),
        "answer_similarity": SequenceMatcher(
            None,
            compact_text(item["answer"]),
            compact_text(answer),
        ).ratio(),
        "trace": response_data.get("trace", []),
        "queue_ms": queue_ms,
        "latency_ms": latency_ms,
        "status": "ok",
    }


def group_summary(results: list[dict[str, Any]], field: str) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for result in results:
        grouped[str(result[field])].append(result)

    summaries = []
    for name, items in sorted(grouped.items()):
        ok_items = [item for item in items if item["status"] == "ok"]
        summaries.append(
            {
                "name": name,
                "count": len(items),
                "errors": len(items) - len(ok_items),
                "keyword_recall": mean([item["keyword_recall"] for item in ok_items]),
                "citation_doc_recall": mean(
                    [item["citation_doc_recall"] for item in ok_items]
                ),
                "evidence_rate": mean(
                    [float(item["evidence_sufficient"]) for item in ok_items]
                ),
            }
        )
    return summaries


def build_summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    ok_results = [result for result in results if result["status"] == "ok"]
    total_keywords = sum(len(result["keywords"]) for result in ok_results)
    matched_keywords = sum(len(result["matched_keywords"]) for result in ok_results)
    latencies = [result["latency_ms"] for result in ok_results]
    repaired_results = [
        result for result in ok_results if result["repair_attempts"] > 0
    ]
    multi_intent_results = [
        result for result in ok_results if len(result["retrieval_queries"]) > 1
    ]
    abstain_reasons = Counter(
        result["failure_reason"]
        for result in ok_results
        if result["abstained"] and result["failure_reason"]
    )

    return {
        "total": len(results),
        "completed": len(ok_results),
        "errors": len(results) - len(ok_results),
        "keyword_recall_macro": mean(
            [result["keyword_recall"] for result in ok_results]
        ),
        "keyword_recall_weighted": (
            matched_keywords / total_keywords if total_keywords else 0.0
        ),
        "citation_doc_recall_macro": mean(
            [result["citation_doc_recall"] for result in ok_results]
        ),
        "citation_present_rate": mean(
            [float(result["citation_count"] > 0) for result in ok_results]
        ),
        "all_expected_docs_cited_rate": mean(
            [float(result["all_expected_docs_cited"]) for result in ok_results]
        ),
        "evidence_sufficient_rate": mean(
            [float(result["evidence_sufficient"]) for result in ok_results]
        ),
        "invalid_citation_rate": mean(
            [float(bool(result["invalid_evidence_ids"])) for result in ok_results]
        ),
        "repair_success_rate": mean(
            [float(result["citation_count"] > 0) for result in repaired_results]
        ),
        "multi_intent_evidence_rate": mean(
            [result["subquery_evidence_rate"] for result in multi_intent_results]
        ),
        "multi_intent_question_count": len(multi_intent_results),
        "abstain_reason_distribution": dict(sorted(abstain_reasons.items())),
        "all_citations_highlighted_rate": mean(
            [float(result["all_citations_highlighted"]) for result in ok_results]
        ),
        "answer_similarity_mean": mean(
            [result["answer_similarity"] for result in ok_results]
        ),
        "latency_ms_mean": mean(latencies),
        "latency_ms_p50": percentile(latencies, 0.50),
        "latency_ms_p95": percentile(latencies, 0.95),
        "by_type": group_summary(ok_results, "type"),
        "by_difficulty": group_summary(ok_results, "difficulty"),
    }


async def run(args: argparse.Namespace) -> dict[str, Any]:
    dataset = json.loads(args.dataset.read_text(encoding="utf-8"))
    questions = dataset["questions"]
    limits = httpx.Limits(
        max_connections=args.concurrency,
        max_keepalive_connections=args.concurrency,
    )
    timeout = httpx.Timeout(args.timeout)
    semaphore = asyncio.Semaphore(args.concurrency)

    async with httpx.AsyncClient(
        base_url=args.base_url,
        timeout=timeout,
        limits=limits,
    ) as client:
        health = await client.get("/api/health")
        health.raise_for_status()
        tasks = [
            evaluate_question(client, question, semaphore, args.retries)
            for question in questions
        ]
        results = await asyncio.gather(*tasks)

    return {
        "dataset": dataset["dataset"],
        "base_url": args.base_url,
        "health": health.json(),
        "summary": build_summary(results),
        "results": results,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate the RAG chat API.")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--output", type=Path, default=Path("rag_eval_report.json"))
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument("--retries", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=180.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = asyncio.run(run(args))
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    summary = report["summary"]
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"report={args.output.resolve()}")


if __name__ == "__main__":
    main()
