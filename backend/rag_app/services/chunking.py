from __future__ import annotations

from dataclasses import dataclass

from rag_app.config import Settings
from rag_app.models.document import (
    BlockType,
    ChunkedDocument,
    ChunkRecord,
    ParsedBlock,
    ParsedDocument,
    SectionNode,
    SourceSpan,
)

ATOMIC_BLOCK_TYPES = {BlockType.TABLE, BlockType.FORMULA, BlockType.IMAGE}
CHUNKER_VERSION = "hierarchical-v1"


@dataclass
class TextSegment:
    text: str
    start: int
    end: int
    block: ParsedBlock


class HierarchicalChunker:
    def __init__(self, settings: Settings) -> None:
        self.target_chars = settings.chunk_target_chars
        self.max_section_chars = settings.chunk_max_section_chars
        self.overlap_chars = int(self.target_chars * settings.chunk_overlap_ratio)

    def chunk(self, document: ParsedDocument) -> ChunkedDocument:
        sections, section_blocks = self._build_sections(document)
        chunks: list[ChunkRecord] = []

        for section in sections:
            blocks = section_blocks[section.section_id]
            content_blocks = [block for block in blocks if block.block_type is not BlockType.TITLE]
            if not content_blocks:
                continue
            section_chunks = self._chunk_section(document, section, content_blocks)
            chunks.extend(section_chunks)

        chunks = self._link_neighbors(chunks)
        return ChunkedDocument(document=document, sections=sections, chunks=chunks)

    def _build_sections(
        self,
        document: ParsedDocument,
    ) -> tuple[list[SectionNode], dict[str, list[ParsedBlock]]]:
        root_id = f"{document.version_id}:s0000"
        root_heading = [document.title]
        root = SectionNode(
            section_id=root_id,
            doc_id=document.doc_id,
            version_id=document.version_id,
            level=0,
            order=0,
            heading=document.title,
            heading_path=root_heading,
            page_start=1,
            page_end=max(block.page_number for block in document.blocks),
        )
        sections = [root]
        section_blocks: dict[str, list[ParsedBlock]] = {root_id: []}
        heading_stack: list[tuple[int, str, str]] = [(0, document.title, root_id)]
        section_counter = 1

        for block in document.blocks:
            if block.block_type is BlockType.TITLE and block.level is not None:
                while heading_stack and heading_stack[-1][0] >= block.level:
                    heading_stack.pop()
                parent_id = heading_stack[-1][2] if heading_stack else root_id
                section_id = f"{document.version_id}:s{section_counter:04d}"
                section_counter += 1
                heading_path = [item[1] for item in heading_stack[1:]] + [block.text]
                section = SectionNode(
                    section_id=section_id,
                    doc_id=document.doc_id,
                    version_id=document.version_id,
                    parent_section_id=parent_id,
                    level=block.level,
                    order=block.order,
                    heading=block.text,
                    heading_path=[document.title, *heading_path],
                    page_start=block.page_number,
                    page_end=block.page_number,
                )
                sections.append(section)
                section_blocks[section_id] = []
                heading_stack.append((block.level, block.text, section_id))
                continue

            current_id = heading_stack[-1][2] if heading_stack else root_id
            section_blocks.setdefault(current_id, []).append(block)

        section_lookup = {section.section_id: section for section in sections}
        for section in sections:
            blocks = section_blocks.get(section.section_id, [])
            if blocks:
                section.page_start = min(block.page_number for block in blocks)
                section.page_end = max(block.page_number for block in blocks)
            if section.parent_section_id:
                parent = section_lookup[section.parent_section_id]
                parent.child_ids.append(section.section_id)
                parent.is_leaf = False

        return sections, section_blocks

    def _chunk_section(
        self,
        document: ParsedDocument,
        section: SectionNode,
        blocks: list[ParsedBlock],
    ) -> list[ChunkRecord]:
        total_chars = sum(len(block.text) for block in blocks)
        if total_chars <= self.max_section_chars:
            return [
                self._make_chunk(
                    document=document,
                    section=section,
                    chunk_index=0,
                    text="\n\n".join(block.text for block in blocks),
                    blocks=blocks,
                )
            ]

        chunks: list[ChunkRecord] = []
        pending_blocks: list[ParsedBlock] = []
        pending_chars = 0

        for block in blocks:
            if block.block_type in ATOMIC_BLOCK_TYPES:
                if pending_blocks:
                    chunks.extend(
                        self._split_text_blocks(document, section, pending_blocks, len(chunks))
                    )
                    pending_blocks = []
                    pending_chars = 0
                chunks.append(
                    self._make_chunk(
                        document=document,
                        section=section,
                        chunk_index=len(chunks),
                        text=block.text,
                        blocks=[block],
                    )
                )
                continue

            pending_blocks.append(block)
            pending_chars += len(block.text)
            if pending_chars >= self.target_chars:
                chunks.extend(
                    self._split_text_blocks(document, section, pending_blocks, len(chunks))
                )
                pending_blocks = []
                pending_chars = 0

        if pending_blocks:
            chunks.extend(self._split_text_blocks(document, section, pending_blocks, len(chunks)))
        return chunks

    def _split_text_blocks(
        self,
        document: ParsedDocument,
        section: SectionNode,
        blocks: list[ParsedBlock],
        start_index: int,
    ) -> list[ChunkRecord]:
        text, segments = self._join_blocks(blocks)
        if len(text) <= self.target_chars:
            return [
                self._make_chunk(
                    document=document,
                    section=section,
                    chunk_index=start_index,
                    text=text,
                    blocks=blocks,
                )
            ]

        chunks: list[ChunkRecord] = []
        start = 0
        while start < len(text):
            end = min(start + self.target_chars, len(text))
            chunk_text = text[start:end].strip()
            if chunk_text:
                spans = self._spans_for_range(segments, start, end)
                chunks.append(
                    self._make_chunk(
                        document=document,
                        section=section,
                        chunk_index=start_index + len(chunks),
                        text=chunk_text,
                        blocks=blocks,
                        spans=spans,
                    )
                )
            if end >= len(text):
                break
            start = max(end - self.overlap_chars, start + 1)
        return chunks

    @staticmethod
    def _join_blocks(blocks: list[ParsedBlock]) -> tuple[str, list[TextSegment]]:
        parts: list[str] = []
        segments: list[TextSegment] = []
        cursor = 0
        for index, block in enumerate(blocks):
            if index:
                parts.append("\n\n")
                cursor += 2
            start = cursor
            parts.append(block.text)
            cursor += len(block.text)
            segments.append(TextSegment(text=block.text, start=start, end=cursor, block=block))
        return "".join(parts), segments

    @staticmethod
    def _spans_for_range(
        segments: list[TextSegment],
        start: int,
        end: int,
    ) -> list[SourceSpan]:
        spans: list[SourceSpan] = []
        for segment in segments:
            overlap_start = max(start, segment.start)
            overlap_end = min(end, segment.end)
            if overlap_start >= overlap_end:
                continue
            local_start = overlap_start - segment.start
            local_end = overlap_end - segment.start
            spans.append(
                SourceSpan(
                    page_number=segment.block.page_number,
                    bbox=segment.block.bbox,
                    page_width=segment.block.page_width,
                    page_height=segment.block.page_height,
                    quote=segment.text[local_start:local_end],
                )
            )
        return spans

    @staticmethod
    def _make_chunk(
        *,
        document: ParsedDocument,
        section: SectionNode,
        chunk_index: int,
        text: str,
        blocks: list[ParsedBlock],
        spans: list[SourceSpan] | None = None,
    ) -> ChunkRecord:
        source_spans = spans or [
            SourceSpan(
                page_number=block.page_number,
                bbox=block.bbox,
                page_width=block.page_width,
                page_height=block.page_height,
                quote=block.text,
            )
            for block in blocks
        ]
        return ChunkRecord(
            chunk_id=f"{section.section_id}:c{chunk_index:04d}",
            doc_id=document.doc_id,
            version_id=document.version_id,
            document_title=document.title,
            section_id=section.section_id,
            chunk_index=chunk_index,
            content_type="text",
            text=text,
            heading_path=section.heading_path,
            page_start=min(span.page_number for span in source_spans),
            page_end=max(span.page_number for span in source_spans),
            source_spans=source_spans,
            char_count=len(text),
        )

    @staticmethod
    def _link_neighbors(chunks: list[ChunkRecord]) -> list[ChunkRecord]:
        for index, chunk in enumerate(chunks):
            if index > 0:
                chunk.prev_chunk_id = chunks[index - 1].chunk_id
            if index < len(chunks) - 1:
                chunk.next_chunk_id = chunks[index + 1].chunk_id
        return chunks
