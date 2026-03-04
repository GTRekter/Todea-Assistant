# RAG over Source Code

## The two problems

```
┌─────────────────────────────────────────────────────────────┐
│  Problem 1: TRAINING                                        │
│  "Teach the model to understand Linkerd source code"        │
│                                                             │
│  → Fine-tune on code + explanations                         │
│  → Model learns patterns, idioms, architecture              │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│  Problem 2: INFERENCE (more important, faster to implement) │
│  "Give the model access to specific code at query time"     │
│                                                             │
│  → RAG: retrieve relevant code snippets from a vector store │
│  → Model sees the *actual current code* in its context      │
└─────────────────────────────────────────────────────────────┘
```

> **RAG over source code is more important than training on source code.** Even if you train on the code today, the codebase will evolve. RAG always retrieves the *current* code. Training gives the model intuition; RAG gives it facts.

## RAG architecture

```
User: "Why does the proxy return HTTP 503?"
        │
        ▼
  ollama-hub receives query
        │
        ├─► MCP Tool: search_code("503 response proxy")
        │         │
        │         ▼
        │   Vector DB (code index)
        │   ┌─────────────────────────────┐
        │   │ linkerd2-proxy/src/         │
        │   │  proxy/src/lib.rs  ← match  │
        │   │  errors/classify.rs ← match │
        │   └─────────────────────────────┘
        │         │
        │   Returns top-K code chunks
        │
        ▼
  Model context:
  [system prompt]
  [retrieved code chunks]  ← injected here
  [user question]
        │
        ▼
  Model answers with real code references
```

## Part 1: RAG over source code (implement first)

### What to index

| Repo | Language | Size | Priority |
|---|---|---|---|
| `linkerd/linkerd2` | Go | ~200k LOC | High |
| `linkerd/linkerd2-proxy` | Rust | ~80k LOC | High |
| `linkerd/linkerd2-proxy-api` | Protobuf | Small | Medium |

### How to chunk code intelligently

Naive line-based splitting breaks functions in half. Code needs **semantic chunking**:

- Go: chunk by function/method (`func ...`)
- Rust: chunk by `impl` block, `fn`, `mod`
- Keep file path + line numbers in metadata — the model can cite them

### Vector store options

| Option | Deployment | Notes |
|---|---|---|
| **Qdrant** | Helm chart, single pod | Best for this use case, fast, persistent |
| **ChromaDB** | Simple Docker | Easier but less production-ready |
| **pgvector** | Add extension to Postgres | If you already run Postgres |

### New MCP tool to add

```python
@mcp.tool()
def search_linkerd_code(query: str, top_k: int = 5) -> list[dict]:
    """Search Linkerd source code by semantic similarity."""
    # query → embedding → Qdrant search → return chunks with file/line metadata
```

This plugs directly into the existing MCP server and the ollama-hub tool-calling loop already handles it.

## Part 2: Training on source code (do second)

Training on raw code files doesn't work well. You need **code paired with explanations**. Three sources:

### 1. Synthetic QA from code (best ROI)

Use a capable model (Claude/GPT-4) to generate Q&A pairs from code:

```
Input:  func (s *Server) Serve(ctx context.Context) error { ... }
Output: Q: "What does Server.Serve do?"
        A: "It starts the gRPC server and blocks until ctx is cancelled..."
```

~500 well-generated pairs from core files beats thousands of raw code lines.

### 2. PR descriptions + diffs

A PR description + its diff is a natural "change explanation" training example. Add a formatter that turns `(pr_title, pr_body, diff)` → conversation.

### 3. Code comments + surrounding code

Extract godoc/rustdoc comments with the function they describe. These are already human-written explanations of code.

## Recommended implementation order

```
Week 1: Build the code indexer
  └─ Script to clone repos, chunk by function, embed, store in Qdrant

Week 2: Add MCP tool
  └─ search_linkerd_code() in the existing MCP server
  └─ Test it works through ollama-hub tool-calling

Week 3: Training data enhancement
  └─ PR diff formatter
  └─ Comment extractor
  └─ Optional: synthetic QA generator

Week 4: Continuous pipeline
  └─ CronJob re-indexes code on new commits (via GitHub webhook or schedule)
```

> The biggest win for the least effort is the **code indexer + MCP tool**. It requires no retraining, works immediately with the current `llama3.1:8b`, and the retrieval is always up-to-date with the live codebase.
