"""
LLM module – Two-model Groq pipeline.

Stage 1: llama-3.1-8b-instant  → intent classification (fast, cheap)
Stage 2: llama-3.3-70b-versatile → SQL generation (accurate, powerful)
Stage 3: llama-3.1-8b-instant  → answer formatting (fast, cheap)
"""

import os
import json
import re
import asyncio
import logging
from openai import AsyncOpenAI
from dotenv import load_dotenv

from db import get_schema_text, execute_sql, get_sample_data, get_schema

load_dotenv()
logger = logging.getLogger(__name__)

_client: AsyncOpenAI | None = None
_system_prompt_cache: str | None = None

# ── Model assignment ──
MODEL_FAST = "llama-3.1-8b-instant"      # intent classify + answer format
MODEL_SQL  = "llama-3.3-70b-versatile"   # SQL generation (accuracy critical)

# ── Dangerous SQL patterns ──
_DANGEROUS_SQL_PATTERNS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|REPLACE|ATTACH|DETACH)\b",
    re.IGNORECASE,
)


def get_client() -> AsyncOpenAI:
    """Get or create the Groq client (OpenAI-compatible)."""
    global _client
    if _client is None:
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key or api_key == "your_groq_api_key_here":
            raise ValueError(
                "GROQ_API_KEY not set. Please add it to backend/.env\n"
                "Get a free key at https://console.groq.com"
            )
        _client = AsyncOpenAI(
            api_key=api_key,
            base_url="https://api.groq.com/openai/v1",
        )
    return _client


def build_system_prompt() -> str:
    """Build and cache the SQL generation system prompt."""
    global _system_prompt_cache

    schema_text = get_schema_text()

    schema = get_schema()
    sample_sections = []
    for table in list(schema.keys())[:5]:
        try:
            samples = get_sample_data(table, limit=2)
            if samples:
                sample_sections.append(
                    f"Sample data from '{table}':\n{json.dumps(samples, indent=2, default=str)}"
                )
        except Exception:
            pass

    sample_text = "\n\n".join(sample_sections)

    _system_prompt_cache = f"""You are a data analyst assistant. Translate user questions into SQL queries against this business dataset (orders, deliveries, invoices, payments, customers, products).

=== DATABASE SCHEMA ===
{schema_text}

=== SAMPLE DATA ===
{sample_text}

=== INSTRUCTIONS ===
Return your response ONLY as valid JSON (no markdown, no code fences):
{{"sql": "<your SQL query>", "explanation": "<brief explanation>"}}

=== SQL RULES ===
- Use SQLite syntax and single quotes for strings
- Table and column names must match the schema exactly
- Use JOINs only when you need columns from another table
- Limit results to 50 rows unless user asks for all

=== CRITICAL: AVOID FAN-OUT JOINS ===
Assignment/mapping tables (e.g. customer_sales_area_assignments) have MULTIPLE rows per entity.
Joining them before SUM/COUNT/AVG will multiply values incorrectly.
- BAD:  SELECT customer, SUM(soh.totalnetamount) FROM customer_sales_area_assignments csa JOIN sales_order_headers soh ON csa.customer = soh.soldtoparty GROUP BY customer
- GOOD: SELECT soldtoparty, SUM(totalnetamount) FROM sales_order_headers GROUP BY soldtoparty
If the fact table already has the key you need, query it directly without joining a mapping table.
"""
    logger.info("System prompt built (%d chars)", len(_system_prompt_cache))
    return _system_prompt_cache


def _get_system_prompt() -> str:
    if _system_prompt_cache is not None:
        return _system_prompt_cache
    return build_system_prompt()


def _validate_sql(sql: str) -> str | None:
    stripped = sql.strip().upper()
    if not stripped.startswith("SELECT") and not stripped.startswith("WITH"):
        return "Only SELECT / WITH queries are allowed."
    if _DANGEROUS_SQL_PATTERNS.search(sql):
        return "Query contains forbidden SQL keywords."
    return None


# Patterns indicating JOIN + aggregate combination (fan-out risk)
_JOIN_RE = re.compile(r"\bJOIN\b", re.IGNORECASE)
_AGGREGATE_RE = re.compile(r"\b(SUM|COUNT|AVG|MIN|MAX|TOTAL)\s*\(", re.IGNORECASE)


def _detect_fanout_risk(sql: str) -> str | None:
    """
    Heuristic: if the SQL joins tables AND uses aggregation, there is a risk
    of row multiplication (fan-out). Returns a warning message if detected.
    """
    if _JOIN_RE.search(sql) and _AGGREGATE_RE.search(sql):
        return (
            "⚠️ **Note:** This query uses a JOIN with an aggregate function. "
            "If any joined table has multiple rows per entity, results may be inflated. "
            "Verify totals against a direct query if precision is critical."
        )
    return None


def extract_sql_from_response(text: str) -> tuple[str | None, str | None]:
    try:
        cleaned = re.sub(r"^```(?:json)?\s*", "", text.strip())
        cleaned = re.sub(r"\s*```$", "", cleaned)
        data = json.loads(cleaned)
        return data.get("sql"), data.get("explanation")
    except (json.JSONDecodeError, AttributeError):
        pass

    json_match = re.search(r'\{[^{}]*"sql"\s*:\s*"[^"]*"[^{}]*\}', text, re.DOTALL)
    if json_match:
        try:
            data = json.loads(json_match.group())
            return data.get("sql"), data.get("explanation")
        except json.JSONDecodeError:
            pass

    sql_match = re.search(r"(?:```sql\s*)(.*?)(?:\s*```)", text, re.DOTALL)
    if sql_match:
        return sql_match.group(1).strip(), None

    return None, None


def _api_error_message(e: Exception) -> str:
    err_str = str(e)
    if "429" in err_str:
        return "Rate limit reached. Please wait a moment and try again."
    if "401" in err_str:
        return "Invalid Groq API key. Please check your GROQ_API_KEY in backend/.env"
    return f"AI API error: {err_str[:300]}"


async def _classify_intent(client: AsyncOpenAI, message: str) -> str:
    """
    Stage 1 – llama-3.1-8b classifies intent.
    Returns: 'dataset_query' | 'off_topic'
    """
    response = await client.chat.completions.create(
        model=MODEL_FAST,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are an intent classifier. The user is interacting with a business data system "
                    "that contains: sales orders, deliveries, invoices, payments, customers, and products.\n"
                    "Classify the user's message as exactly one of:\n"
                    "- 'dataset_query' if it asks about the business data (orders, customers, deliveries, payments, products, quantities, amounts, dates, etc.)\n"
                    "- 'off_topic' if it asks about anything else (general knowledge, coding, personal questions, etc.)\n"
                    "Reply with ONLY the classification word, nothing else."
                ),
            },
            {"role": "user", "content": message},
        ],
        max_tokens=10,
        temperature=0.0,
    )
    result = (response.choices[0].message.content or "").strip().lower()
    logger.info("Intent classified: %s", result)
    return "dataset_query" if "dataset" in result else "off_topic"


async def chat_stream(
    message: str,
    history: list[dict] | None = None,
):
    """
    Three-stage pipeline:
      1. 8B  → classify intent
      2. 70B → generate SQL
      3. 8B  → format natural language answer
    """
    client = get_client()

    # ── Stage 1: Intent classification (8B, fast) ──
    try:
        intent = await _classify_intent(client, message)
    except Exception as e:
        logger.warning("Intent classification failed, defaulting to dataset_query: %s", e)
        intent = "dataset_query"

    if intent == "off_topic":
        yield json.dumps({
            "type": "guardrail",
            "content": "This system is designed to answer questions related to the provided dataset only."
        })
        yield json.dumps({"type": "done"})
        return

    # ── Stage 2: SQL generation (70B, accurate) ──
    sql_messages = [{"role": "system", "content": _get_system_prompt()}]
    if history:
        for msg in history[-6:]:
            role = "assistant" if msg.get("role") == "model" else msg.get("role", "user")
            sql_messages.append({"role": role, "content": msg["content"]})
    sql_messages.append({"role": "user", "content": message})

    response_text = None
    for attempt in range(2):
        try:
            response = await client.chat.completions.create(
                model=MODEL_SQL,
                messages=sql_messages,
                max_tokens=512,
                temperature=0.1,
            )
            response_text = response.choices[0].message.content or ""
            break
        except Exception as e:
            if "429" in str(e) and attempt == 0:
                await asyncio.sleep(3)
            else:
                yield json.dumps({"type": "error", "content": _api_error_message(e)})
                return

    if not response_text:
        yield json.dumps({"type": "error", "content": "No response from SQL model."})
        return

    sql, explanation = extract_sql_from_response(response_text)

    if not sql:
        # 70B gave a plain text answer — stream it directly
        yield json.dumps({"type": "answer", "content": response_text.strip()})
        yield json.dumps({"type": "done"})
        return

    safety_error = _validate_sql(sql)
    if safety_error:
        yield json.dumps({"type": "error", "content": f"Query blocked: {safety_error}"})
        return

    # Fan-out risk detection: warn if JOIN + aggregate used
    fanout_warning = _detect_fanout_risk(sql)
    if fanout_warning:
        yield json.dumps({"type": "warning", "content": fanout_warning})

    yield json.dumps({"type": "sql", "sql": sql, "explanation": explanation or ""})

    try:
        results = execute_sql(sql)
    except Exception as e:
        yield json.dumps({"type": "error", "content": f"SQL Error: {str(e)}"})
        return

    yield json.dumps({"type": "results_count", "count": len(results)})
    yield json.dumps({"type": "results", "rows": results[:50]})

    # ── Stage 3: Answer formatting (8B, fast) ──
    results_text = json.dumps(results[:50], indent=2, default=str)
    answer_messages = [
        {
            "role": "system",
            "content": "You are a helpful data analyst. Format SQL results into a clear, concise natural language answer with markdown (tables, bold, lists). Do not mention SQL."
        },
        {
            "role": "user",
            "content": (
                f'Question: "{message}"\n\n'
                f"Results ({len(results)} rows):\n{results_text}\n\n"
                "Provide a clear answer with key insights."
            ),
        },
    ]

    try:
        stream = await client.chat.completions.create(
            model=MODEL_FAST,
            messages=answer_messages,
            max_tokens=1024,
            temperature=0.3,
            stream=True,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta:
                yield json.dumps({"type": "chunk", "content": delta})
    except Exception as e:
        yield json.dumps({"type": "error", "content": _api_error_message(e)})

    yield json.dumps({"type": "done"})
