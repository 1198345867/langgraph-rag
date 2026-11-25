"""按失败维度导出评测报告中的 Bad Case，便于逐条归因与回流。

只读评测报告 JSON，不需要 Elasticsearch 与外部 API。
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

DIMENSIONS = ["接口错误", "拒答", "未给出引用", "漏关键词", "漏引用文档"]


def classify(result: dict[str, Any]) -> list[str]:
    """返回该题命中的失败维度，一题可能同时命中多个。"""
    if result["status"] != "ok":
        return ["接口错误"]
    dimensions: list[str] = []
    if result["abstained"]:
        dimensions.append("拒答")
    if result["citation_count"] == 0:
        dimensions.append("未给出引用")
    if result["keyword_recall"] < 1:
        dimensions.append("漏关键词")
    if result["citation_doc_recall"] < 1:
        dimensions.append("漏引用文档")
    return dimensions


def truncate(value: str, limit: int = 160) -> str:
    value = " ".join(str(value).split())
    return value if len(value) <= limit else f"{value[:limit]}..."


def cell(value: str) -> str:
    return truncate(value).replace("|", "\\|")


def missing_keywords(result: dict[str, Any]) -> str:
    matched = set(result.get("matched_keywords", []))
    return "、".join(keyword for keyword in result["keywords"] if keyword not in matched)


def missing_docs(result: dict[str, Any]) -> str:
    matched = set(result.get("matched_docs", []))
    return "、".join(doc for doc in result["expected_docs"] if doc not in matched)


def detail(result: dict[str, Any], dimension: str) -> str:
    if dimension == "接口错误":
        return result.get("error") or "未知错误"
    if dimension == "拒答":
        return result.get("failure_reason") or "未知原因"
    if dimension == "未给出引用":
        return "引用数为 0"
    if dimension == "漏关键词":
        return missing_keywords(result) or "无"
    return missing_docs(result) or "无"


def build(report: dict[str, Any], report_name: str) -> str:
    results: list[dict[str, Any]] = report["results"]
    total = len(results)
    failed = [result for result in results if classify(result)]

    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for result in failed:
        for dimension in classify(result):
            groups[dimension].append(result)

    lines = [
        "# Bad Case 归因",
        "",
        f"- 数据集：{report.get('dataset')}",
        f"- 报告：{report_name}",
        f"- 题目总数：{total}",
        f"- 存在失败的题数：{len(failed)}（{len(failed) / total:.1%}）",
        "",
        "| 失败维度 | 题数 | 占全部题目 |",
        "| --- | ---: | ---: |",
    ]
    for dimension in DIMENSIONS:
        items = groups.get(dimension, [])
        if items:
            lines.append(f"| {dimension} | {len(items)} | {len(items) / total:.1%} |")

    # 按题型统计失败率，用于判断缺口集中在哪类问题
    by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for result in results:
        by_type[result["type"]].append(result)
    lines.extend(
        [
            "",
            "## 按题型",
            "",
            "| 题型 | 题数 | 失败题数 | 失败率 |",
            "| --- | ---: | ---: | ---: |",
        ]
    )
    for name in sorted(by_type):
        items = by_type[name]
        type_failed = [item for item in items if classify(item)]
        lines.append(
            f"| {name} | {len(items)} | {len(type_failed)} "
            f"| {len(type_failed) / len(items):.1%} |"
        )

    for dimension in DIMENSIONS:
        items = groups.get(dimension, [])
        if not items:
            continue
        lines.extend(
            [
                "",
                f"## {dimension}（{len(items)} 题）",
                "",
                "| 题号 | 题型 | 难度 | 问题 | 缺失项 | 实际答案摘要 |",
                "| --- | --- | --- | --- | --- | --- |",
            ]
        )
        for result in items:
            answer = result.get("actual_answer") or "（无回答）"
            lines.append(
                f"| {result['id']} | {result['type']} | {result['difficulty']} "
                f"| {cell(result['question'])} | {cell(detail(result, dimension))} "
                f"| {cell(answer)} |"
            )

    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="从评测报告导出 Bad Case 归因。")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("badcases.md"))
    args = parser.parse_args()

    report = json.loads(args.report.read_text(encoding="utf-8"))
    args.output.write_text(build(report, args.report.name), encoding="utf-8")
    print(f"badcases={args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
