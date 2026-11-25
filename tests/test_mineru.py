import json

from rag_app.config import Settings
from rag_app.services.mineru import MinerUAdapter


def test_parse_content_list_scales_normalized_bboxes_and_includes_tables(tmp_path) -> None:
    layout_path = tmp_path / "layout.json"
    layout_path.write_text(
        json.dumps({"pdf_info": [{"page_idx": 0, "page_size": [600, 800]}]}),
        encoding="utf-8",
    )
    content_path = tmp_path / "sample_content_list.json"
    content_path.write_text(
        json.dumps(
            [
                {
                    "type": "text",
                    "text": "测试标题",
                    "text_level": 1,
                    "bbox": [100, 100, 200, 110],
                    "page_idx": 0,
                },
                {
                    "type": "table",
                    "table_caption": ["测试表"],
                    "table_body": (
                        "<table><tr><td>项目</td><td>值</td></tr>"
                        "<tr><td>期限</td><td>3天</td></tr></table>"
                    ),
                    "table_footnote": ["注：测试"],
                    "bbox": [50, 200, 950, 300],
                    "page_idx": 0,
                },
                {
                    "type": "page_number",
                    "text": "1",
                    "bbox": [480, 950, 500, 960],
                    "page_idx": 0,
                },
            ]
        ),
        encoding="utf-8",
    )

    blocks = MinerUAdapter(Settings())._parse_content_list(content_path, layout_path)

    assert [block.text for block in blocks] == [
        "测试标题",
        "测试表\n项目 | 值\n期限 | 3天\n注：测试",
    ]
    assert blocks[0].bbox == [60, 80, 120, 88]
    assert blocks[1].bbox == [30, 160, 570, 240]
    assert blocks[0].page_width == 600
    assert blocks[0].page_height == 800
