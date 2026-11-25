import { useEffect, useRef, useState } from "react";
import { Document, Page } from "react-pdf";
import { ExternalLink, FileText } from "lucide-react";

import type { Citation, SourceSpan } from "../api";

interface PdfPreviewProps {
  citation: Citation | null;
}

function overlaysForPage(citation: Citation, pageNumber: number) {
  return citation.source_spans.filter(
    (span): span is SourceSpan & { bbox: number[]; page_width: number; page_height: number } =>
      span.page_number === pageNumber &&
      span.bbox?.length === 4 &&
      Boolean(span.page_width) &&
      Boolean(span.page_height)
  );
}

export default function PdfPreview({ citation }: PdfPreviewProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(520);
  const [pageCount, setPageCount] = useState(0);

  useEffect(() => {
    const element = containerRef.current;
    if (!element) {
      return;
    }
    const observer = new ResizeObserver(([entry]) => {
      setWidth(Math.max(280, Math.min(Math.floor(entry.contentRect.width) - 2, 720)));
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  if (!citation) {
    return (
      <section className="preview-panel" aria-label="PDF 预览">
        <div className="panel-heading">
          <FileText size={17} />
          <span>原文预览</span>
        </div>
        <div className="preview-empty">点击回答中的引用查看原文位置</div>
      </section>
    );
  }

  const pageNumber = Math.min(citation.page_start, pageCount || citation.page_start);
  const overlays = overlaysForPage(citation, pageNumber);

  return (
    <section className="preview-panel" aria-label="PDF 预览">
      <div className="panel-heading">
        <div className="preview-title">
          <FileText size={17} />
          <span>{citation.title}</span>
        </div>
        <a href={`${citation.file_url}#page=${pageNumber}`} target="_blank" rel="noreferrer">
          <ExternalLink size={16} />
        </a>
      </div>
      <div className="citation-context">
        <span>{citation.heading_path.join(" / ")}</span>
        <span>
          第 {citation.page_start}
          {citation.page_end !== citation.page_start ? `-${citation.page_end}` : ""} 页
        </span>
      </div>
      <div className="pdf-scroll" ref={containerRef}>
        <Document
          file={citation.file_url}
          onLoadSuccess={({ numPages }) => setPageCount(numPages)}
          loading={<div className="preview-message">正在加载 PDF</div>}
          error={<div className="preview-message">PDF 加载失败</div>}
        >
          <div className="pdf-page-wrap">
            <Page
              pageNumber={pageNumber}
              width={width}
              renderAnnotationLayer={false}
              renderTextLayer={false}
            />
            <div className="pdf-highlight-layer">
              {overlays.map((span, index) => {
                const [x0, y0, x1, y1] = span.bbox;
                return (
                  <div
                    className="pdf-highlight"
                    key={`${span.page_number}-${index}`}
                    style={{
                      left: `${(x0 / span.page_width) * 100}%`,
                      top: `${(y0 / span.page_height) * 100}%`,
                      width: `${((x1 - x0) / span.page_width) * 100}%`,
                      height: `${((y1 - y0) / span.page_height) * 100}%`
                    }}
                    title={span.quote}
                  />
                );
              })}
            </div>
          </div>
        </Document>
      </div>
      <div className="quote-panel">
        {citation.source_spans.map((span, index) => (
          <blockquote key={`${span.page_number}-${index}`}>{span.quote}</blockquote>
        ))}
      </div>
    </section>
  );
}
