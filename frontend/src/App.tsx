import {
  ChangeEvent,
  FormEvent,
  MouseEvent as ReactMouseEvent,
  useEffect,
  useMemo,
  useRef,
  useState
} from "react";
import {
  AlertCircle,
  CheckCircle2,
  FileText,
  Loader2,
  MessageSquareText,
  Plus,
  Send,
  Trash2,
  Upload
} from "lucide-react";

import {
  ApiError,
  Citation,
  ConversationMessage,
  ConversationRecord,
  DocumentRecord,
  HealthResponse,
  deleteConversation,
  getConversation,
  getHealth,
  listConversations,
  listDocuments,
  sendChat,
  uploadDocument
} from "./api";
import PdfPreview from "./components/PdfPreview";

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  sufficient?: boolean;
}

const statusLabels: Record<DocumentRecord["parse_status"], string> = {
  pending: "等待解析",
  parsing: "解析中",
  indexing: "建立索引",
  completed: "可检索",
  failed: "失败"
};

function toUiMessage(message: ConversationMessage): Message {
  return {
    id: message.turn_id,
    role: message.role,
    content: message.content,
    citations: message.citations,
    sufficient: message.evidence_sufficient ?? undefined
  };
}

export default function App() {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [documents, setDocuments] = useState<DocumentRecord[]>([]);
  const [conversations, setConversations] = useState<ConversationRecord[]>([]);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [selectedCitation, setSelectedCitation] = useState<Citation | null>(null);
  const [question, setQuestion] = useState("");
  const [sending, setSending] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [loadingConversations, setLoadingConversations] = useState(true);
  const [loadingConversationId, setLoadingConversationId] = useState<string | null>(null);
  const [deletingConversationId, setDeletingConversationId] = useState<string | null>(null);
  const [error, setError] = useState("");

  const refreshDocuments = async () => {
    try {
      setDocuments(await listDocuments());
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "文档列表加载失败");
    }
  };

  const refreshConversations = async () => {
    try {
      setConversations(await listConversations());
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "会话列表加载失败");
    } finally {
      setLoadingConversations(false);
    }
  };

  useEffect(() => {
    getHealth().then(setHealth).catch(() => undefined);
    refreshDocuments();
    refreshConversations();
    const interval = window.setInterval(refreshDocuments, 5000);
    return () => window.clearInterval(interval);
  }, []);

  const indexedCount = useMemo(
    () => documents.filter((document) => document.parse_status === "completed").length,
    [documents]
  );

  const handleUpload = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) {
      return;
    }
    setUploading(true);
    setError("");
    try {
      await uploadDocument(file);
      await refreshDocuments();
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "上传失败");
    } finally {
      setUploading(false);
    }
  };

  const startNewConversation = () => {
    setConversationId(null);
    setMessages([]);
    setSelectedCitation(null);
    setQuestion("");
    setError("");
  };

  const handleSelectConversation = async (selectedConversationId: string) => {
    if (
      selectedConversationId === conversationId ||
      sending ||
      loadingConversationId !== null
    ) {
      return;
    }
    setLoadingConversationId(selectedConversationId);
    setError("");
    try {
      const conversation = await getConversation(selectedConversationId);
      const restoredMessages = conversation.messages.map(toUiMessage);
      setConversationId(conversation.conversation_id);
      setMessages(restoredMessages);
      setSelectedCitation(
        [...restoredMessages]
          .reverse()
          .find((message) => message.citations?.length)?.citations?.[0] ?? null
      );
    } catch (requestError) {
      if (requestError instanceof ApiError && requestError.status === 404) {
        setConversationId(null);
        setMessages([]);
        setSelectedCitation(null);
        setError("该会话已不存在，请开始新对话。");
        await refreshConversations();
      } else {
        setError(requestError instanceof Error ? requestError.message : "会话加载失败");
      }
    } finally {
      setLoadingConversationId(null);
    }
  };

  const handleDeleteConversation = async (
    event: ReactMouseEvent<HTMLButtonElement>,
    targetConversationId: string,
    title: string
  ) => {
    event.stopPropagation();
    if (!window.confirm(`删除会话“${title}”？`)) {
      return;
    }
    setDeletingConversationId(targetConversationId);
    setError("");
    try {
      await deleteConversation(targetConversationId);
      if (targetConversationId === conversationId) {
        startNewConversation();
      }
      await refreshConversations();
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "删除会话失败");
    } finally {
      setDeletingConversationId(null);
    }
  };

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    const content = question.trim();
    if (!content || sending) {
      return;
    }
    const userMessage: Message = {
      id: crypto.randomUUID(),
      role: "user",
      content
    };
    setMessages((current) => [...current, userMessage]);
    setQuestion("");
    setSending(true);
    setError("");
    try {
      const response = await sendChat(content, conversationId);
      setConversationId(response.conversation_id);
      setMessages((current) => [
        ...current,
        {
          id: crypto.randomUUID(),
          role: "assistant",
          content: response.answer,
          citations: response.citations,
          sufficient: response.evidence_sufficient
        }
      ]);
      if (response.citations[0]) {
        setSelectedCitation(response.citations[0]);
      }
      void refreshConversations();
    } catch (requestError) {
      if (requestError instanceof ApiError && requestError.status === 404) {
        setConversationId(null);
        setMessages((current) => current.filter((message) => message.id !== userMessage.id));
        setError("原会话已不存在，已切换到新对话，请重新发送。");
        void refreshConversations();
      } else {
        setError(requestError instanceof Error ? requestError.message : "问答请求失败");
      }
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">
          <MessageSquareText size={20} />
          <strong>私有文档问答</strong>
        </div>
        <div className="service-state">
          <span className={health?.elasticsearch ? "dot online" : "dot offline"} />
          <span>Elasticsearch</span>
          <span className="divider" />
          <span className={health?.agicto_configured ? "dot online" : "dot offline"} />
          <span>AGICTO</span>
        </div>
      </header>

      <aside className="sidebar">
        <section className="sidebar-section document-section">
          <div className="sidebar-heading">
            <div>
              <span className="eyebrow">知识库</span>
              <strong>{indexedCount} 份可检索</strong>
            </div>
            <button
              className="icon-button"
              type="button"
              onClick={() => fileInputRef.current?.click()}
              disabled={uploading}
              title="上传 PDF"
            >
              {uploading ? <Loader2 className="spin" size={18} /> : <Plus size={18} />}
            </button>
          </div>
          <input
            ref={fileInputRef}
            type="file"
            accept="application/pdf,.pdf"
            hidden
            onChange={handleUpload}
          />
          <button
            className="upload-button"
            type="button"
            onClick={() => fileInputRef.current?.click()}
            disabled={uploading}
          >
            <Upload size={17} />
            上传 PDF
          </button>
          <div className="document-list">
            {documents.map((document) => (
              <div className="document-item" key={document.doc_id}>
                <FileText size={17} />
                <div className="document-copy">
                  <strong title={document.title}>{document.title}</strong>
                  <span className={`status ${document.parse_status}`}>
                    {statusLabels[document.parse_status]}
                  </span>
                </div>
              </div>
            ))}
            {!documents.length && <div className="empty-list">暂无文档</div>}
          </div>
        </section>

        <section className="sidebar-section conversation-section">
          <div className="sidebar-heading">
            <div>
              <span className="eyebrow">对话</span>
              <strong>历史会话</strong>
            </div>
            <button
              className="icon-button"
              type="button"
              onClick={startNewConversation}
              disabled={sending || loadingConversationId !== null}
              title="新建对话"
            >
              <Plus size={18} />
            </button>
          </div>
          <div className="conversation-list">
            {conversations.map((conversation) => {
              const active = conversation.conversation_id === conversationId;
              const loading = conversation.conversation_id === loadingConversationId;
              const deleting = conversation.conversation_id === deletingConversationId;
              return (
                <div
                  className={`conversation-item${active ? " active" : ""}`}
                  key={conversation.conversation_id}
                >
                  <button
                    className="conversation-select"
                    type="button"
                    onClick={() => handleSelectConversation(conversation.conversation_id)}
                    disabled={sending || deleting}
                    title={conversation.title}
                  >
                    {loading ? (
                      <Loader2 className="spin" size={16} />
                    ) : (
                      <MessageSquareText size={16} />
                    )}
                    <span className="conversation-copy">
                      <strong>{conversation.title}</strong>
                      <small>{conversation.message_count} 条消息</small>
                    </span>
                  </button>
                  <button
                    className="conversation-delete"
                    type="button"
                    onClick={(event) =>
                      handleDeleteConversation(
                        event,
                        conversation.conversation_id,
                        conversation.title
                      )
                    }
                    disabled={deleting || sending}
                    title="删除会话"
                  >
                    {deleting ? (
                      <Loader2 className="spin" size={15} />
                    ) : (
                      <Trash2 size={15} />
                    )}
                  </button>
                </div>
              );
            })}
            {!conversations.length && !loadingConversations && (
              <div className="empty-list">暂无历史会话</div>
            )}
            {loadingConversations && (
              <div className="empty-list">
                <Loader2 className="spin" size={15} />
              </div>
            )}
          </div>
        </section>
      </aside>

      <main className="conversation">
        <div className="conversation-scroll">
          {!messages.length ? (
            <div className="conversation-empty">
              <MessageSquareText size={26} />
              <strong>向知识库提问</strong>
            </div>
          ) : (
            messages.map((message) => (
              <article className={`message ${message.role}`} key={message.id}>
                <div className="message-label">
                  {message.role === "user" ? "你" : "助手"}
                  {message.role === "assistant" && message.sufficient === false && (
                    <AlertCircle size={14} />
                  )}
                </div>
                <div className="message-content">{message.content}</div>
                {message.citations && message.citations.length > 0 && (
                  <div className="citation-list">
                    {message.citations.map((citation) => (
                      <button
                        type="button"
                        key={`${message.id}-${citation.evidence_id}`}
                        onClick={() => setSelectedCitation(citation)}
                        className={
                          selectedCitation?.chunk_id === citation.chunk_id ? "active" : ""
                        }
                      >
                        <CheckCircle2 size={14} />
                        [{citation.evidence_id}] {citation.title} · 第 {citation.page_start} 页
                      </button>
                    ))}
                  </div>
                )}
              </article>
            ))
          )}
          {sending && (
            <div className="thinking">
              <Loader2 className="spin" size={16} />
              正在检索
            </div>
          )}
        </div>
        {error && <div className="error-strip">{error}</div>}
        <form className="composer" onSubmit={handleSubmit}>
          <textarea
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            placeholder="输入问题"
            rows={2}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                event.currentTarget.form?.requestSubmit();
              }
            }}
          />
          <button
            className="send-button"
            type="submit"
            disabled={sending || loadingConversationId !== null || !question.trim()}
          >
            {sending ? <Loader2 className="spin" size={18} /> : <Send size={18} />}
          </button>
        </form>
      </main>

      <div className="preview-slot">
        <PdfPreview citation={selectedCitation} />
      </div>
    </div>
  );
}
