"use client";

import { useRef, useState } from "react";

type Source = {
  source: string;
  page: number | null;
  text: string;
};

type Message = {
  role: "user" | "assistant";
  content: string;
  sources?: Source[];
};

type DocumentFile = {
  id: string;
  name: string;
  size: number;
  status: "uploading" | "uploaded" | "error";
  error?: string;
};

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

const MAX_FILE_SIZE = 20 * 1024 * 1024; // 20 MB
const MAX_QUESTION_LENGTH = 2000;

export default function Home() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [documents, setDocuments] = useState<DocumentFile[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [uploadingCount, setUploadingCount] = useState(0);
  const [uploadMessage, setUploadMessage] = useState("");
  const [uploadError, setUploadError] = useState("");

  const requestInProgress = useRef(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const uploadedDocuments = documents.filter(
    (document) => document.status === "uploaded"
  );

  function handleNewChat() {
    if (requestInProgress.current) return;

    setMessages([]);
    setInput("");
  }

  async function handleFileSelection(
    event: React.ChangeEvent<HTMLInputElement>
  ) {
    const files = Array.from(event.target.files ?? []);

    // Permit selecting the same file again later.
    event.target.value = "";

    if (files.length === 0) return;

    setUploadMessage("");
    setUploadError("");

    const validFiles: File[] = [];
    const errors: string[] = [];

    for (const file of files) {
      const isPdf =
        file.type === "application/pdf" ||
        file.name.toLowerCase().endsWith(".pdf");

      if (!isPdf) {
        errors.push(`${file.name}: Only PDF files are supported.`);
        continue;
      }

      if (file.size === 0) {
        errors.push(`${file.name}: The file is empty.`);
        continue;
      }

      if (file.size > MAX_FILE_SIZE) {
        errors.push(`${file.name}: Maximum file size is 20 MB.`);
        continue;
      }

      const alreadyAdded = documents.some(
        (document) =>
          document.name === file.name &&
          document.size === file.size &&
          document.status !== "error"
      );

      if (alreadyAdded) {
        errors.push(`${file.name}: This file is already in the list.`);
        continue;
      }

      validFiles.push(file);
    }

    if (errors.length > 0) {
      setUploadError(errors.join("\n"));
    }

    if (validFiles.length === 0) return;

    setUploadingCount((count) => count + validFiles.length);

    for (const file of validFiles) {
      const id = crypto.randomUUID();

      setDocuments((previous) => [
        ...previous,
        {
          id,
          name: file.name,
          size: file.size,
          status: "uploading",
        },
      ]);

      try {
        const formData = new FormData();
        formData.append("file", file);

        const response = await fetch(
          `${API_BASE_URL}/api/documents/upload`,
          {
            method: "POST",
            body: formData,
          }
        );

        const data = await response.json().catch(() => null);

        if (!response.ok) {
          throw new Error(
            data?.detail ||
              data?.message ||
              `Upload failed with status ${response.status}.`
          );
        }

        setDocuments((previous) =>
          previous.map((document) =>
            document.id === id
              ? { ...document, status: "uploaded" }
              : document
          )
        );

        setUploadMessage(
          `${file.name} uploaded and indexed successfully.`
        );
      } catch (error) {
        console.error("PDF upload error:", error);

        const errorText =
          error instanceof TypeError
            ? "Cannot connect to the backend. Check that FastAPI is running."
            : error instanceof Error
              ? error.message
              : "An unexpected upload error occurred.";

        setDocuments((previous) =>
          previous.map((document) =>
            document.id === id
              ? {
                  ...document,
                  status: "error",
                  error: errorText,
                }
              : document
          )
        );

        setUploadError(`${file.name}: ${errorText}`);
      } finally {
        setUploadingCount((count) => Math.max(0, count - 1));
      }
    }
  }

  function removeDocument(id: string) {
    const document = documents.find((item) => item.id === id);

    // Do not remove a file while its upload is in progress.
    if (!document || document.status === "uploading") return;

    setDocuments((previous) =>
      previous.filter((item) => item.id !== id)
    );
  }

  async function handleSendMessage() {
    const question = input.trim();

    if (requestInProgress.current || isLoading) return;

    if (!question) return;

    if (question.length > MAX_QUESTION_LENGTH) {
      setMessages((previous) => [
        ...previous,
        {
          role: "assistant",
          content: `Please keep your question under ${MAX_QUESTION_LENGTH} characters.`,
        },
      ]);
      return;
    }

    if (uploadingCount > 0) {
      setMessages((previous) => [
        ...previous,
        {
          role: "assistant",
          content:
            "Please wait for your PDF uploads to finish before asking a question.",
        },
      ]);
      return;
    }

    requestInProgress.current = true;
    setIsLoading(true);
    setInput("");

    const userMessage: Message = {
      role: "user",
      content: question,
    };

    const loadingMessage: Message = {
      role: "assistant",
      content: "Thinking...",
    };

    // Add the question and loading message together.
    setMessages((previous) => [
      ...previous,
      userMessage,
      loadingMessage,
    ]);

    try {
      const response = await fetch(
        `${API_BASE_URL}/api/chat/`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ query: question }),
        }
      );

      const data = await response.json().catch(() => null);

      if (!response.ok) {
        throw new Error(
          data?.detail ||
            data?.message ||
            `The backend returned status ${response.status}.`
        );
      }

      const answer =
        typeof data?.answer === "string" && data.answer.trim()
          ? data.answer
          : "The AI returned an empty answer.";

      const sources: Source[] = Array.isArray(data?.sources)
        ? data.sources
            .filter(
              (source: unknown) =>
                typeof source === "object" &&
                source !== null &&
                typeof (source as Source).source === "string"
            )
            .map((source: Source) => ({
              source: source.source,
              page:
                typeof source.page === "number"
                  ? source.page
                  : null,
              text:
                typeof source.text === "string"
                  ? source.text
                  : "",
            }))
        : [];

      setMessages((previous) => {
        const updated = [...previous];

        const loadingIndex = updated.findLastIndex(
          (message) =>
            message.role === "assistant" &&
            message.content === "Thinking..."
        );

        if (loadingIndex !== -1) {
          updated[loadingIndex] = {
            role: "assistant",
            content: answer,
            sources,
          };
        }

        return updated;
      });
    } catch (error) {
      console.error("Chat API error:", error);

      const errorMessage =
        error instanceof TypeError
          ? "Cannot connect to FloatChat's backend. Check that FastAPI is running and try again."
          : error instanceof Error
            ? error.message
            : "An unexpected error occurred. Please try again.";

      setMessages((previous) => {
        const updated = [...previous];

        const loadingIndex = updated.findLastIndex(
          (message) =>
            message.role === "assistant" &&
            message.content === "Thinking..."
        );

        if (loadingIndex !== -1) {
          updated[loadingIndex] = {
            role: "assistant",
            content: errorMessage,
            sources: [],
          };
        }

        return updated;
      });
    } finally {
      requestInProgress.current = false;
      setIsLoading(false);
    }
  }

  return (
    <main className="flex h-screen overflow-hidden bg-white text-slate-900">
      {/* Sidebar */}
      <aside className="flex w-72 shrink-0 flex-col border-r border-slate-200 bg-slate-50">
        {/* Logo */}
        <div className="flex items-center gap-3 border-b border-slate-200 px-6 py-5">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-blue-600 text-lg font-bold text-white shadow-sm">
            F
          </div>

          <div>
            <h1 className="text-lg font-bold tracking-tight">
              FloatChat
            </h1>
            <p className="text-xs text-slate-500">
              AI Document Assistant
            </p>
          </div>
        </div>

        {/* New Chat */}
        <div className="p-4">
          <button
            onClick={handleNewChat}
            disabled={isLoading}
            className="flex w-full items-center justify-center gap-2 rounded-xl bg-blue-600 px-4 py-3 text-sm font-semibold text-white transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-60"
          >
            <span className="text-lg">+</span>
            New conversation
          </button>
        </div>

        {/* Documents */}
        <div className="flex-1 overflow-y-auto px-4">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-xs font-semibold uppercase tracking-wider text-slate-500">
              Your documents
            </h2>

            <span className="rounded-full bg-slate-200 px-2 py-0.5 text-xs text-slate-600">
              {uploadedDocuments.length}
            </span>
          </div>

          <label
            className={`flex flex-col items-center rounded-xl border-2 border-dashed border-slate-300 bg-white px-4 py-6 text-center transition ${
              uploadingCount > 0
                ? "cursor-wait opacity-60"
                : "cursor-pointer hover:border-blue-400 hover:bg-blue-50/50"
            }`}
          >
            <span className="mb-2 flex h-10 w-10 items-center justify-center rounded-xl bg-blue-50 text-xl">
              +
            </span>

            <span className="text-sm font-semibold text-slate-700">
              Upload PDF files
            </span>

            <span className="mt-1 text-xs text-slate-500">
              PDF only · Maximum 20 MB per file
            </span>

            <input
              ref={fileInputRef}
              type="file"
              accept=".pdf,application/pdf"
              multiple
              disabled={uploadingCount > 0}
              className="hidden"
              onChange={handleFileSelection}
            />
          </label>

          {uploadingCount > 0 && (
            <p className="mt-3 text-center text-xs text-blue-600">
              Uploading and indexing documents...
            </p>
          )}

          {uploadMessage && (
            <p
              role="status"
              className="mt-3 break-words text-xs text-emerald-700"
            >
              {uploadMessage}
            </p>
          )}

          {uploadError && (
            <div
              role="alert"
              className="mt-3 whitespace-pre-wrap break-words rounded-lg bg-red-50 p-3 text-xs text-red-700"
            >
              {uploadError}
            </div>
          )}

          <div className="mt-4 space-y-2">
            {documents.map((document) => (
              <div
                key={document.id}
                className="flex items-center gap-3 rounded-xl border border-slate-200 bg-white p-3"
              >
                <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-red-50 text-xs font-bold text-red-600">
                  PDF
                </div>

                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium text-slate-700">
                    {document.name}
                  </p>

                  <p className="text-xs text-slate-400">
                    {(document.size / 1024).toFixed(1)} KB
                  </p>

                  {document.status === "uploading" && (
                    <p className="mt-1 text-xs text-blue-600">
                      Uploading...
                    </p>
                  )}

                  {document.status === "uploaded" && (
                    <p className="mt-1 text-xs text-emerald-600">
                      Indexed
                    </p>
                  )}

                  {document.status === "error" && (
                    <p
                      className="mt-1 break-words text-xs text-red-600"
                      title={document.error}
                    >
                      Upload failed
                    </p>
                  )}
                </div>

                <button
                  onClick={() => removeDocument(document.id)}
                  disabled={document.status === "uploading"}
                  className="rounded-md px-2 py-1 text-slate-400 hover:bg-red-50 hover:text-red-600 disabled:cursor-not-allowed disabled:opacity-30"
                  aria-label={`Remove ${document.name}`}
                  title="Remove file from this list"
                >
                  ×
                </button>
              </div>
            ))}

            {documents.length === 0 && (
              <p className="px-2 py-3 text-center text-xs leading-5 text-slate-400">
                Your uploaded documents will appear here.
              </p>
            )}
          </div>
        </div>

        {/* Sidebar Footer */}
        <div className="border-t border-slate-200 p-4">
          <div className="flex items-center gap-3 rounded-xl p-2">
            <div className="flex h-9 w-9 items-center justify-center rounded-full bg-blue-100 text-sm font-bold text-blue-700">
              FC
            </div>

            <div>
              <p className="text-sm font-semibold">
                FloatChat Workspace
              </p>
              <p className="text-xs text-slate-500">
                Document intelligence
              </p>
            </div>
          </div>
        </div>
      </aside>

      {/* Main Chat Area */}
      <section className="flex min-w-0 flex-1 flex-col">
        {/* Header */}
        <header className="flex h-[73px] shrink-0 items-center justify-between border-b border-slate-200 px-6 md:px-10">
          <div>
            <h2 className="font-semibold text-slate-800">
              Document Assistant
            </h2>
            <p className="text-xs text-slate-500">
              Ask questions about your documents
            </p>
          </div>

          <div className="flex items-center gap-2 rounded-full border border-emerald-200 bg-emerald-50 px-3 py-1.5">
            <span className="h-2 w-2 rounded-full bg-emerald-500" />
            <span className="text-xs font-medium text-emerald-700">
              Workspace ready
            </span>
          </div>
        </header>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto">
          {messages.length === 0 ? (
            <div className="flex min-h-full flex-col items-center justify-center px-6 py-12">
              <div className="mb-6 flex h-16 w-16 items-center justify-center rounded-2xl bg-blue-600 text-2xl font-bold text-white shadow-lg shadow-blue-100">
                F
              </div>

              <p className="mb-3 text-sm font-semibold text-blue-600">
                YOUR DOCUMENTS, UNDERSTOOD
              </p>

              <h1 className="max-w-2xl text-center text-3xl font-bold tracking-tight text-slate-900 sm:text-4xl">
                What would you like to know?
              </h1>

              <p className="mt-4 max-w-lg text-center text-sm leading-6 text-slate-500 sm:text-base">
                Upload your PDFs and explore their contents with AI.
                Find information, understand complex topics, and get
                answers grounded in your documents.
              </p>

              <div className="mt-10 grid w-full max-w-2xl gap-3 sm:grid-cols-2">
                {[
                  {
                    title: "Summarize a document",
                    description: "Give me the key points from my PDF.",
                  },
                  {
                    title: "Find important information",
                    description: "Find the most relevant details in my files.",
                  },
                  {
                    title: "Explain a complex topic",
                    description: "Explain a concept in simple language.",
                  },
                  {
                    title: "Compare information",
                    description: "Compare ideas across my documents.",
                  },
                ].map((item) => (
                  <button
                    key={item.title}
                    onClick={() => setInput(item.description)}
                    className="rounded-xl border border-slate-200 bg-white p-4 text-left transition hover:border-blue-300 hover:bg-blue-50/40"
                  >
                    <p className="text-sm font-semibold text-slate-800">
                      {item.title}
                    </p>
                    <p className="mt-1 text-xs leading-5 text-slate-500">
                      {item.description}
                    </p>
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="mx-auto max-w-3xl space-y-8 px-6 py-10">
              {messages.map((message, index) => (
                <div
                  key={index}
                  className={`flex gap-3 ${
                    message.role === "user"
                      ? "justify-end"
                      : "justify-start"
                  }`}
                >
                  {message.role === "assistant" && (
                    <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-blue-600 font-bold text-white">
                      F
                    </div>
                  )}

                  <div className="max-w-[85%]">
                    <div
                      className={`whitespace-pre-wrap rounded-2xl px-4 py-3 text-sm leading-7 ${
                        message.role === "user"
                          ? "bg-blue-600 text-white"
                          : "border border-slate-200 bg-slate-50 text-slate-800"
                      }`}
                    >
                      {message.content}
                    </div>

                    {/* Source citations */}
                    {message.role === "assistant" &&
                      message.sources &&
                      message.sources.length > 0 && (
                        <div className="mt-3 rounded-xl border border-slate-200 bg-white p-4">
                          <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-slate-500">
                            Sources
                          </h3>

                          <div className="space-y-3">
                            {message.sources.map((source, sourceIndex) => (
                              <div
                                key={`${source.source}-${source.page}-${sourceIndex}`}
                                className="flex gap-3"
                              >
                                <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-red-50 text-xs font-bold text-red-600">
                                  PDF
                                </div>

                                <div className="min-w-0 flex-1">
                                  <p className="break-words text-sm font-medium text-slate-800">
                                    {source.source}
                                  </p>

                                  <p className="mt-1 text-xs text-slate-500">
                                    {source.page != null
                                      ? `Page ${source.page}`
                                      : "Page unavailable"}
                                  </p>

                                  {source.text && (
                                    <details className="mt-2">
                                      <summary className="cursor-pointer text-xs font-medium text-blue-600 hover:text-blue-700">
                                        View relevant excerpt
                                      </summary>

                                      <p className="mt-2 whitespace-pre-wrap rounded-lg bg-slate-50 p-3 text-xs leading-5 text-slate-600">
                                        {source.text}
                                      </p>
                                    </details>
                                  )}
                                </div>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Input Area */}
        <div className="shrink-0 border-t border-slate-200 bg-white px-4 py-5 sm:px-8">
          <div className="mx-auto max-w-3xl">
            {uploadedDocuments.length === 0 && (
              <p className="mb-3 text-center text-xs text-slate-400">
                Upload your documents before asking document-specific questions.
              </p>
            )}

            <form
              onSubmit={(event) => {
                event.preventDefault();
                void handleSendMessage();
              }}
              className="flex items-end gap-3 rounded-2xl border border-slate-300 bg-white p-3 shadow-sm transition focus-within:border-blue-400 focus-within:ring-4 focus-within:ring-blue-50"
            >
              <textarea
                value={input}
                onChange={(event) => setInput(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault();
                    void handleSendMessage();
                  }
                }}
                placeholder="Ask a question about your documents..."
                rows={1}
                maxLength={MAX_QUESTION_LENGTH}
                className="max-h-32 min-h-10 flex-1 resize-y bg-transparent px-2 py-2 text-sm text-slate-800 outline-none placeholder:text-slate-400"
              />

              <button
                type="submit"
                disabled={!input.trim() || isLoading || uploadingCount > 0}
                className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-blue-600 text-lg text-white transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-slate-300"
                aria-label="Send message"
                title="Send message"
              >
                {isLoading ? "…" : "↑"}
              </button>
            </form>

            <p className="mt-3 text-center text-xs text-slate-400">
              FloatChat AI can make mistakes. Verify important information against your sources.
            </p>
          </div>
        </div>
      </section>
    </main>
  );
}