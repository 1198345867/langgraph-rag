from rag_app.config import Settings
from rag_app.models.document import BlockType, ParsedBlock, ParsedDocument
from rag_app.services.chunking import HierarchicalChunker


def make_settings() -> Settings:
    return Settings(
        chunk_target_chars=20,
        chunk_max_section_chars=30,
        chunk_overlap_ratio=0.2,
    )


def test_hierarchical_chunking_respects_section_boundaries() -> None:
    document = ParsedDocument(
        doc_id="doc-1",
        version_id="v1",
        title="测试文档",
        source_path="test.pdf",
        blocks=[
            ParsedBlock(
                block_id="b1",
                block_type=BlockType.TITLE,
                text="第一章",
                page_number=1,
                level=1,
                order=0,
            ),
            ParsedBlock(
                block_id="b2",
                text="第一段内容" * 8,
                page_number=1,
                bbox=[10, 20, 100, 40],
                page_width=600,
                page_height=800,
                order=1,
            ),
            ParsedBlock(
                block_id="b3",
                block_type=BlockType.TITLE,
                text="第二章",
                page_number=2,
                level=1,
                order=2,
            ),
            ParsedBlock(
                block_id="b4",
                text="第二段内容" * 4,
                page_number=2,
                bbox=[20, 30, 120, 50],
                page_width=600,
                page_height=800,
                order=3,
            ),
        ],
    )

    chunked = HierarchicalChunker(make_settings()).chunk(document)

    first_chapter = next(section for section in chunked.sections if section.heading == "第一章")
    second_chapter = next(section for section in chunked.sections if section.heading == "第二章")
    first_chunks = [
        chunk for chunk in chunked.chunks if chunk.section_id == first_chapter.section_id
    ]
    second_chunks = [
        chunk for chunk in chunked.chunks if chunk.section_id == second_chapter.section_id
    ]

    assert first_chunks
    assert second_chunks
    assert all("第二段内容" not in chunk.text for chunk in first_chunks)
    assert all("第一段内容" not in chunk.text for chunk in second_chunks)
    assert all(chunk.source_spans for chunk in first_chunks)


def test_large_section_uses_overlap() -> None:
    document = ParsedDocument(
        doc_id="doc-2",
        version_id="v2",
        title="重叠测试",
        source_path="test.pdf",
        blocks=[
            ParsedBlock(
                block_id="b1",
                block_type=BlockType.TITLE,
                text="正文",
                page_number=1,
                level=1,
                order=0,
            ),
            ParsedBlock(
                block_id="b2",
                text="".join(chr(ord("a") + index % 26) for index in range(90)),
                page_number=1,
                bbox=[0, 0, 200, 100],
                page_width=600,
                page_height=800,
                order=1,
            ),
        ],
    )

    chunks = HierarchicalChunker(make_settings()).chunk(document).chunks

    assert len(chunks) >= 3
    assert chunks[0].text[-4:] == chunks[1].text[:4]
    assert chunks[0].prev_chunk_id is None
    assert chunks[-1].next_chunk_id is None
