export type ParseStatus = "pending" | "parsing" | "indexing" | "completed" | "failed";

export interface SourceSpan {
  page_number: number;
  bbox: number[] | null;
  page_width: number | null;
  page_height: number | null;
  quote: string;
}

export interface Citation {
  evidence_id: string;
  chunk_id: string;
  doc_id: string;
  title: string;
  heading_path: string[];
  page_start: number;
  page_end: number;
  source_spans: SourceSpan[];
  file_url: string;
}

export interface DocumentRecord {
  doc_id: string;
  version_id: string;
  title: string;
  file_name: string;
  page_count: number;
  parse_status: ParseStatus;
  active_version: string | null;
  created_at: string;
  error_message: string | null;
}

export interface ChatResponse {
  conversation_id: string;
  answer: string;
  citations: Citation[];
  evidence_sufficient: boolean;
  retrieval_round: number;
  trace: string[];
}

export interface ConversationRecord {
  conversation_id: string;
  session_id: string;
  user_id: string | null;
  title: string;
  summary: string | null;
  message_count: number;
  summary_message_count: number;
  last_message_at: string;
  summary_updated_at: string | null;
  status: string;
}

export interface ConversationMessage {
  turn_id: string;
  role: "user" | "assistant";
  content: string;
  citations: Citation[];
  evidence_sufficient: boolean | null;
  abstain_reason: string;
  created_at: string;
  model: string | null;
}

export interface ConversationDetail extends ConversationRecord {
  messages: ConversationMessage[];
}

export interface HealthResponse {
  status: string;
  elasticsearch: boolean;
  agicto_configured: boolean;
  chat_model: string | null;
  embedding_model: string | null;
}

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    credentials: "include",
    ...init
  });
  if (!response.ok) {
    let detail = response.statusText;
    const body = await response.text();
    try {
      const payload = JSON.parse(body) as { detail?: unknown };
      if (typeof payload.detail === "string") {
        detail = payload.detail;
      } else if (body) {
        detail = body;
      }
    } catch {
      detail = body || detail;
    }
    throw new ApiError(response.status, detail || `请求失败 (${response.status})`);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export function getHealth(): Promise<HealthResponse> {
  return request<HealthResponse>("/api/health");
}

export function listDocuments(): Promise<DocumentRecord[]> {
  return request<DocumentRecord[]>("/api/documents");
}

export async function uploadDocument(file: File): Promise<void> {
  const body = new FormData();
  body.append("file", file);
  await request("/api/documents", {
    method: "POST",
    body
  });
}

export function sendChat(message: string, conversationId: string | null): Promise<ChatResponse> {
  return request<ChatResponse>("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      message,
      conversation_id: conversationId
    })
  });
}

export function listConversations(): Promise<ConversationRecord[]> {
  return request<ConversationRecord[]>("/api/conversations");
}

export function getConversation(conversationId: string): Promise<ConversationDetail> {
  return request<ConversationDetail>(`/api/conversations/${conversationId}`);
}

export function deleteConversation(conversationId: string): Promise<void> {
  return request<void>(`/api/conversations/${conversationId}`, {
    method: "DELETE"
  });
}
