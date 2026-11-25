from __future__ import annotations

import asyncio
import json
import re
import shutil
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import httpx

from rag_app.config import Settings
from rag_app.models.document import BlockType, ParsedBlock, ParsedDocument


class MinerUError(RuntimeError):
    pass


class _TableHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._row: list[str] = []
        self._cell_parts: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._row = []
        elif tag in {"td", "th"}:
            self._cell_parts = []
        elif tag == "br" and self._cell_parts is not None:
            self._cell_parts.append(" ")

    def handle_data(self, data: str) -> None:
        if self._cell_parts is not None:
            self._cell_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._cell_parts is not None:
            cell = re.sub(r"\s+", " ", "".join(self._cell_parts)).strip()
            self._row.append(cell)
            self._cell_parts = None
        elif tag == "tr" and self._row:
            self.rows.append(self._row)
            self._row = []


class MinerUAdapter:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def parse(
        self,
        pdf_path: Path,
        *,
        doc_id: str,
        version_id: str,
        title: str,
    ) -> ParsedDocument:
        output_dir = self.settings.mineru_output_dir / version_id
        output_dir.mkdir(parents=True, exist_ok=True)
        if self.settings.mineru_api_key:
            await self._parse_via_api(pdf_path, output_dir, doc_id)
        else:
            await self._parse_via_cli(pdf_path, output_dir)

        content_list = self._find_content_list(output_dir)
        if content_list is None:
            raise MinerUError(
                "MinerU did not create a content_list JSON file. "
                "Adjust MinerUAdapter for the installed MinerU version."
            )
        layout_path = self._find_layout(output_dir)
        blocks = self._parse_content_list(content_list, layout_path)
        return ParsedDocument(
            doc_id=doc_id,
            version_id=version_id,
            title=title,
            source_path=str(pdf_path),
            blocks=blocks,
        )

    async def _parse_via_cli(self, pdf_path: Path, output_dir: Path) -> None:
        if shutil.which(self.settings.mineru_command) is None:
            raise MinerUError(
                f"MinerU command '{self.settings.mineru_command}' was not found in PATH."
            )
        process = await asyncio.create_subprocess_exec(
            self.settings.mineru_command,
            "-p",
            str(pdf_path),
            "-o",
            str(output_dir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            detail = stderr.decode("utf-8", errors="replace").strip()
            raise MinerUError(detail or "MinerU failed without an error message.")

    async def _parse_via_api(self, pdf_path: Path, output_dir: Path, doc_id: str) -> None:
        base_url = self.settings.mineru_base_url.rstrip("/")
        headers = {
            "Authorization": f"Bearer {self.settings.mineru_api_key}",
            "Accept": "application/json",
        }
        async with httpx.AsyncClient(
            headers=headers,
            follow_redirects=True,
            timeout=120.0,
        ) as client:
            upload_data = await self._request_api(
                client,
                "POST",
                f"{base_url}/file-urls/batch",
                action="request upload URL",
                json={
                    "files": [{"name": pdf_path.name, "data_id": doc_id}],
                    "model_version": self.settings.mineru_model_version,
                    "language": "ch",
                    "enable_formula": True,
                    "enable_table": True,
                },
            )
            batch_id = str(upload_data.get("batch_id") or "")
            file_urls = upload_data.get("file_urls")
            if not batch_id or not isinstance(file_urls, list) or len(file_urls) != 1:
                raise MinerUError("MinerU returned an unexpected upload URL response.")

            file_bytes = await asyncio.to_thread(pdf_path.read_bytes)
            upload_response = await client.put(str(file_urls[0]), content=file_bytes)
            if upload_response.is_error:
                raise MinerUError(
                    "MinerU PDF upload failed: "
                    f"{upload_response.status_code} {upload_response.text}"
                )

            zip_url = await self._wait_for_api_result(
                client,
                f"{base_url}/extract-results/batch/{batch_id}",
                doc_id=doc_id,
            )
            zip_response = await client.get(zip_url)
            if zip_response.is_error:
                raise MinerUError(
                    "MinerU result download failed: "
                    f"{zip_response.status_code} {zip_response.text}"
                )

        zip_path = output_dir / f"{batch_id}.zip"
        zip_path.write_bytes(zip_response.content)
        self._extract_zip(zip_path, output_dir)

    async def _wait_for_api_result(
        self,
        client: httpx.AsyncClient,
        url: str,
        *,
        doc_id: str,
    ) -> str:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.settings.mineru_poll_timeout_seconds
        while True:
            data = await self._request_api(
                client,
                "GET",
                url,
                action="query parse result",
            )
            results = data.get("extract_result")
            if results is None:
                results = []
            if not isinstance(results, list):
                raise MinerUError("MinerU returned an unexpected batch result structure.")

            result = next(
                (item for item in results if item.get("data_id") == doc_id),
                results[0] if len(results) == 1 else None,
            )
            if result is not None:
                state = str(result.get("state") or "")
                if state == "done":
                    zip_url = str(result.get("full_zip_url") or "")
                    if not zip_url:
                        raise MinerUError("MinerU completed without a result download URL.")
                    return zip_url
                if state == "failed":
                    detail = str(result.get("err_msg") or "MinerU parsing failed.")
                    raise MinerUError(detail)
                if state not in {"waiting-file", "pending", "running", "converting"}:
                    raise MinerUError(f"MinerU returned an unexpected state: {state or 'empty'}")

            if loop.time() >= deadline:
                raise MinerUError("MinerU parsing timed out.")
            await asyncio.sleep(self.settings.mineru_poll_interval_seconds)

    @staticmethod
    async def _request_api(
        client: httpx.AsyncClient,
        method: str,
        url: str,
        *,
        action: str,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        response = await client.request(method, url, json=json)
        if response.is_error:
            raise MinerUError(
                f"MinerU {action} failed: {response.status_code} {response.text}"
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise MinerUError(f"MinerU {action} returned invalid JSON.") from exc
        if not isinstance(payload, dict) or payload.get("code") != 0:
            message = payload.get("msg") if isinstance(payload, dict) else "invalid response"
            code = payload.get("code") if isinstance(payload, dict) else None
            raise MinerUError(f"MinerU {action} failed: {message} (code: {code})")
        data = payload.get("data")
        if not isinstance(data, dict):
            raise MinerUError(f"MinerU {action} returned an unexpected response.")
        return data

    @staticmethod
    def _extract_zip(zip_path: Path, output_dir: Path) -> None:
        root = output_dir.resolve()
        try:
            with zipfile.ZipFile(zip_path) as archive:
                for member in archive.infolist():
                    target = (output_dir / member.filename).resolve()
                    if target != root and root not in target.parents:
                        raise MinerUError("MinerU result archive contains an unsafe path.")
                archive.extractall(output_dir)
        except zipfile.BadZipFile as exc:
            raise MinerUError("MinerU returned an invalid result archive.") from exc

    @staticmethod
    def _find_content_list(output_dir: Path) -> Path | None:
        for pattern in ("*content_list.json", "*middle.json"):
            candidates = list(output_dir.rglob(pattern))
            if candidates:
                return candidates[0]
        return None

    @staticmethod
    def _find_layout(output_dir: Path) -> Path | None:
        candidates = list(output_dir.rglob("*layout.json"))
        return candidates[0] if candidates else None

    def _parse_content_list(
        self,
        path: Path,
        layout_path: Path | None = None,
    ) -> list[ParsedBlock]:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise MinerUError(f"Unable to read MinerU content list: {path}") from exc

        items = raw if isinstance(raw, list) else raw.get("content_list", [])
        if not isinstance(items, list):
            raise MinerUError("Unexpected MinerU content-list structure.")

        page_sizes = self._load_page_sizes(layout_path) if layout_path else {}
        normalized_bboxes = self._has_normalized_bboxes(items, page_sizes)
        blocks: list[ParsedBlock] = []
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            raw_type = str(item.get("type", "text")).lower()
            if raw_type in {"footer", "page_footer", "page_number", "header", "page_header"}:
                continue

            text = self._item_text(item, raw_type)
            if not text:
                continue
            block_type = self._map_block_type(item)
            page_index = self._page_index(item)
            page_number = page_index + 1
            page_size = page_sizes.get(page_index)
            bbox = self._normalize_bbox(item.get("bbox"))
            if normalized_bboxes and bbox is not None and page_size is not None:
                bbox = self._scale_bbox(bbox, page_size)
            blocks.append(
                ParsedBlock(
                    block_id=f"b{index:05d}",
                    block_type=block_type,
                    text=text,
                    page_number=page_number,
                    bbox=bbox,
                    page_width=(
                        self._optional_float(item.get("page_width"))
                        or (page_size[0] if page_size else None)
                    ),
                    page_height=(
                        self._optional_float(item.get("page_height"))
                        or (page_size[1] if page_size else None)
                    ),
                    level=self._heading_level(item),
                    order=index,
                )
            )
        if not blocks:
            raise MinerUError("MinerU content list contained no readable blocks.")
        return blocks

    def _item_text(self, item: dict[str, Any], raw_type: str) -> str:
        if raw_type == "table":
            parts = [
                *self._string_list(item.get("table_caption")),
                self._html_table_to_text(str(item.get("table_body") or "")),
                *self._string_list(item.get("table_footnote")),
            ]
            text = "\n".join(part for part in parts if part)
            if text:
                return text
        return str(item.get("text") or item.get("content") or "").strip()

    @staticmethod
    def _string_list(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()]

    @classmethod
    def _html_table_to_text(cls, value: str) -> str:
        if not value.strip():
            return ""
        parser = _TableHTMLParser()
        parser.feed(value)
        parser.close()
        return "\n".join(" | ".join(cell for cell in row if cell) for row in parser.rows)

    @staticmethod
    def _load_page_sizes(path: Path | None) -> dict[int, tuple[float, float]]:
        if path is None:
            return {}
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        pages = raw.get("pdf_info") if isinstance(raw, dict) else None
        if not isinstance(pages, list):
            return {}

        page_sizes: dict[int, tuple[float, float]] = {}
        for fallback_index, page in enumerate(pages):
            if not isinstance(page, dict):
                continue
            page_size = page.get("page_size")
            if not isinstance(page_size, list) or len(page_size) != 2:
                continue
            try:
                width = float(page_size[0])
                height = float(page_size[1])
                page_index = int(page.get("page_idx", fallback_index))
            except (TypeError, ValueError):
                continue
            if width > 0 and height > 0:
                page_sizes[page_index] = (width, height)
        return page_sizes

    @classmethod
    def _has_normalized_bboxes(
        cls,
        items: list[Any],
        page_sizes: dict[int, tuple[float, float]],
    ) -> bool:
        if not page_sizes:
            return False
        for item in items:
            if not isinstance(item, dict):
                continue
            bbox = cls._normalize_bbox(item.get("bbox"))
            page_size = page_sizes.get(cls._page_index(item))
            if bbox is None or page_size is None:
                continue
            if bbox[2] > page_size[0] * 1.01 or bbox[3] > page_size[1] * 1.01:
                return True
        return False

    @staticmethod
    def _scale_bbox(bbox: list[float], page_size: tuple[float, float]) -> list[float]:
        width, height = page_size
        return [
            bbox[0] / 1000 * width,
            bbox[1] / 1000 * height,
            bbox[2] / 1000 * width,
            bbox[3] / 1000 * height,
        ]

    @staticmethod
    def _page_index(item: dict[str, Any]) -> int:
        try:
            return int(item.get("page_idx", item.get("page_number", 0)))
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _optional_float(value: Any) -> float | None:
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _normalize_bbox(value: Any) -> list[float] | None:
        if not isinstance(value, list) or len(value) != 4:
            return None
        try:
            return [float(item) for item in value]
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _heading_level(item: dict[str, Any]) -> int | None:
        raw_level = item.get("text_level", item.get("level"))
        if raw_level is None:
            return None
        try:
            level = int(raw_level)
        except (TypeError, ValueError):
            return None
        return max(1, min(level, 6))

    def _map_block_type(self, item: dict[str, Any]) -> BlockType:
        raw_type = str(item.get("type", "text")).lower()
        if self._heading_level(item) is not None or raw_type in {"title", "heading"}:
            return BlockType.TITLE
        mapping = {
            "table": BlockType.TABLE,
            "equation": BlockType.FORMULA,
            "formula": BlockType.FORMULA,
            "list": BlockType.LIST,
            "caption": BlockType.CAPTION,
            "image": BlockType.IMAGE,
        }
        return mapping.get(raw_type, BlockType.TEXT)
