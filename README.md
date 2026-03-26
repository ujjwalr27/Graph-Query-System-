# Dodgeai — Graph-Based Data Modelling & LLM Query System

A full-stack application that unifies fragmented business data into an interactive graph and enables natural language querying via a two-model LLM pipeline.

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                  React Frontend                     │
│  Graph Visualization · Chat · Semantic Search Bar   │
└────────────────────┬────────────────────────────────┘
                     │  HTTP / SSE
┌────────────────────▼────────────────────────────────┐
│                 FastAPI Backend                     │
│                                                     │
│  ┌─────────────────────────────────────────────┐   │
│  │        Two-Model LLM Pipeline (Groq)        │   │
│  │  Stage 1: llama-3.1-8b  → intent classify   │   │
│  │  Stage 2: llama-3.3-70b → SQL generation    │   │
│  │  Stage 3: llama-3.1-8b  → answer format     │   │
│  └─────────────────────────────────────────────┘   │
│                                                     │
│  ┌──────────────┐  ┌──────────────┐                │
│  │  NetworkX    │  │  SQLite      │  ← CSVs        │
│  │  (graph)     │  │  (queries)   │                │
│  └──────────────┘  └──────────────┘                │
│                                                     │
│  ┌──────────────────────────────┐                  │
│  │  TF-IDF Search Index        │  (scikit-learn)   │
│  └──────────────────────────────┘                  │
└─────────────────────────────────────────────────────┘
```

---

## Architecture Decisions

### Database: SQLite
- **Why:** Zero-config, file-based, perfect for read-heavy analytical queries on flat CSV data. Entire dataset loads in-memory at startup.
- **Auto-discovery:** Schema is dynamically extracted and injected into the LLM system prompt — no hardcoded column names.
- **Tradeoff:** Not suitable for concurrent writes or >10GB datasets. For production scale, PostgreSQL + read replicas would replace it.

### Graph: NetworkX (in-memory directed graph)
- **Why:** Pythonic, supports BFS/DFS/community detection, zero external dependencies.
- **Auto-relationship detection:** Edges are created automatically between tables sharing FK-like column names (e.g. `soldtoparty`, `deliverydocument`). No manual schema mapping needed.
- **Community detection:** Greedy modularity maximization assigns cluster IDs to every node at startup.
- **Tradeoff:** Memory-bound (~100K nodes). Production scale → Neo4j AuraDB.

### LLM: Two-Model Groq Pipeline
Using OpenAI-compatible API against Groq's inference endpoint:

| Stage | Model | Role | Rationale |
|-------|-------|------|-----------|
| 1 | `llama-3.1-8b-instant` | Intent classification | Fast (50ms), cheap — 14,400 req/day |
| 2 | `llama-3.3-70b-versatile` | SQL generation | Accuracy critical — 1,000 req/day budget preserved |
| 3 | `llama-3.1-8b-instant` | Answer formatting + streaming | Fast, capable enough for formatting |

This design uses only **1× 70B call** per query instead of 2×, doubling the effective daily quota.

### LLM Prompting Strategy
The Stage 2 system prompt includes:
1. **Full database schema** — all table names and column types
2. **Sample data** (2 rows per table) — gives the model concrete value examples
3. **Structured output contract** — must return `{"sql": "...", "explanation": "..."}` JSON
4. **SQL rules** — SQLite syntax, string quoting, 50-row limit
5. **Anti-pattern examples** — explicit BAD/GOOD examples to prevent fan-out join bugs

**Fan-out prevention example in prompt:**
```
BAD:  SELECT customer, SUM(soh.totalnetamount)
      FROM customer_sales_area_assignments csa
      JOIN sales_order_headers soh ON csa.customer = soh.soldtoparty
      GROUP BY customer
      -- BUG: multiplied by number of sales areas per customer

GOOD: SELECT soldtoparty, SUM(totalnetamount)
      FROM sales_order_headers
      GROUP BY soldtoparty
```

### Semantic Search: TF-IDF
- Uses `scikit-learn` TF-IDF vectorizer with bigrams over node text descriptions
- Indexed at startup, sub-millisecond query time
- No external API or model download required
- Upgrade path: swap `TfidfVectorizer` for `fastembed` or `sentence-transformers` without changing the search interface

---

## Guardrails

The system uses **layered guardrails**:

| Layer | Mechanism | What it catches |
|-------|-----------|-----------------|
| **Stage 1** | `llama-3.1-8b` intent classifier | Off-topic queries (general knowledge, creative writing, etc.) |
| **Stage 2** | Regex SQL blocklist | `INSERT / UPDATE / DELETE / DROP / ALTER / TRUNCATE` |
| **Stage 3** | Fan-out detection | `JOIN + aggregate` pattern → amber warning banner |
| **Prompt** | System prompt scope | SQL generation scoped to business dataset only |

**Off-topic response (exact):**
> *"This system is designed to answer questions related to the provided dataset only."*

---

## Optional Extensions Implemented

| Extension | Implementation |
|-----------|----------------|
| ✅ NL → SQL translation | Groq 70B, structured JSON output, schema + sample data in prompt |
| ✅ Node highlighting | SQL results → node IDs → graph glow on query completion |
| ✅ Semantic search | TF-IDF index, live search bar in header, result count badge |
| ✅ Streaming responses | SSE `chunk` events, real-time rendering |
| ✅ Conversation memory | Session store (20 msg rolling window) per `session_id` |
| ✅ Graph clustering | Greedy modularity communities, toggle button recolors nodes by cluster |

---

## Quick Start (Docker)

```bash
git clone <repo>
cd Dodgeai

# Add your Groq API key (free at console.groq.com)
echo "GROQ_API_KEY=your_key_here" > backend/.env

# Place CSV files in backend/data/
# (Download from task brief Google Drive link)

docker compose up --build
```

Open `http://localhost` — the app is running.

---

## Example Queries

| Query | What happens |
|-------|-------------|
| "Top 5 customers by total order value" | Direct `sales_order_headers` aggregation, no fan-out |
| "Which deliveries have not been billed yet?" | LEFT JOIN with NULL check against `billing_document_items` |
| "Identify sales orders with broken or incomplete flows" | Multi-status check on `outbound_delivery_headers` |
| "What is the capital of France?" | ❌ Blocked by Stage 1 guardrail |
| "DROP TABLE sales_order_headers" | ❌ Blocked by SQL blocklist |

---

## API Reference

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/health` | GET | Health check |
| `/api/schema` | GET | Database schema |
| `/api/graph` | GET | Full graph (nodes + links + entity types) |
| `/api/graph/clusters` | GET | Community cluster assignments |
| `/api/graph/node/{id}` | GET | Node + neighbors (expandable) |
| `/api/chat` | POST | NL query — SSE streaming response |
| `/api/search` | GET | Semantic entity search (`?q=...`) |

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | FastAPI, Python 3.12 |
| Database | SQLite + pandas (CSV ingestion) |
| Graph | NetworkX + greedy modularity clustering |
| LLM | Groq — llama-3.3-70b-versatile + llama-3.1-8b-instant |
| LLM Client | `openai` SDK (OpenAI-compatible API) |
| Search | scikit-learn TF-IDF + cosine similarity |
| Frontend | React 18, Vite 6 |
| Visualization | react-force-graph-2d |
| Markdown | react-markdown + remark-gfm |
| Styling | Vanilla CSS (dark theme) |
| Container | Docker + nginx |

---

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GROQ_API_KEY` | ✅ Yes | Get free at [console.groq.com](https://console.groq.com) |

---

## License

MIT
