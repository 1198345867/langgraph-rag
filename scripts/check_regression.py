"""离线校验评测报告是否相对基线发生回退。

只读 JSON，不依赖 Elasticsearch 与外部 API，可直接在 CI 中运行。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

# 指标名 -> (中文名, 方向)；方向为 1 表示越大越好，为 -1 表示越小越好
METRICS: dict[str, tuple[str, int]] = {
    "keyword_recall_macro": ("关键词召回", 1),
    "citation_doc_recall_macro": ("引用文档召回", 1),
    "citation_present_rate": ("引用出现率", 1),
    "all_expected_docs_cited_rate": ("期望文档全部引用率", 1),
    "evidence_sufficient_rate": ("证据充分率", 1),
    "invalid_citation_rate": ("非法引用率", -1),
    "repair_success_rate": ("引用修复成功率", 1),
    "all_citations_highlighted_rate": ("引用高亮覆盖率", 1),
    "answer_similarity_mean": ("答案相似度", 1),
}


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="校验评测报告相对基线是否回退。")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, default=Path("rag_eval_baseline.json"))
    parser.add_argument(
        "--tolerance",
        type=float,
        default=0.01,
        help="允许的回退幅度，默认 1 个百分点",
    )
    args = parser.parse_args()

    report = load(args.report)
    baseline = load(args.baseline)
    summary = report["summary"]

    failures: list[str] = []
    if report.get("dataset") != baseline.get("dataset"):
        failures.append(
            f"数据集不一致：报告 {report.get('dataset')} / 基线 {baseline.get('dataset')}"
        )
    if summary.get("total") != baseline.get("total"):
        failures.append(
            f"题目数不一致：报告 {summary.get('total')} / 基线 {baseline.get('total')}"
        )
    if summary.get("errors"):
        failures.append(f"存在 {summary['errors']} 道接口错误题")

    print("| 指标 | 基线 | 本次 | 变化 | 结论 |")
    print("| --- | ---: | ---: | ---: | --- |")
    for name, (label, direction) in METRICS.items():
        expected = baseline["metrics"].get(name)
        if expected is None:
            continue
        actual = summary.get(name)
        if actual is None:
            failures.append(f"{label}：报告缺少该指标")
            print(f"| {label} | {expected:.4f} | 缺失 | - | 失败 |")
            continue
        # 统一保留 4 位小数，避免浮点尾差带来虚假变化
        delta = round(float(actual), 4) - round(float(expected), 4)
        regressed = delta < -args.tolerance if direction > 0 else delta > args.tolerance
        if regressed:
            failures.append(f"{label}：{delta:+.4f}")
        print(
            f"| {label} | {expected:.4f} | {float(actual):.4f} | {delta:+.4f} "
            f"| {'回退' if regressed else '通过'} |"
        )

    print(
        f"\n参考：P50 {summary.get('latency_ms_p50')}ms / "
        f"P95 {summary.get('latency_ms_p95')}ms，延迟受机器与网络影响，不作为门禁。"
    )

    if failures:
        print("\n回退明细：")
        for item in failures:
            print(f"- {item}")
        return 1
    print("\n全部指标未低于基线。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
