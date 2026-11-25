from rag_app.services.agicto import AGICTOClient

from scripts.evaluate_rag import compact_text


def test_compact_text_normalizes_chinese_numbers_with_units() -> None:
    assert compact_text("十个工作日内办结") == compact_text("10个工作日办结")
    assert compact_text("十五个工作日") == compact_text("15个工作日")
    assert compact_text("四十学时") == compact_text("40学时")


def test_parse_query_plan_accepts_fenced_json() -> None:
    assert AGICTOClient._parse_query_plan(
        '```json\n{"queries": ["问题一", "问题二"]}\n```'
    ) == ["问题一", "问题二"]
