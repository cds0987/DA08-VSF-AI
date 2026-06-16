from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from .auth import AuthSession
from .config import EVAL_ROOT, Settings
from .writer import utc_now


OUTCOME = {
    1: "REFUSE",
    2: "CLARIFY",
    3: "NO_INFO",
    4: "OFF_TOPIC",
    5: "SUCCESS",
    6: "ERROR",
}


@dataclass
class QueryEvidence:
    status_code: int | None = None
    answer: str = ""
    events: list[dict[str, Any]] = field(default_factory=list)
    sources: list[dict[str, Any]] = field(default_factory=list)
    done: dict[str, Any] | None = None
    first_token_latency_seconds: float | None = None
    total_latency_seconds: float | None = None
    error: str | None = None
    timed_out: bool = False
    retry_count: int = 0
    auth_recovered: bool = False


class QueryHttpError(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


class ProductionClient:
    def __init__(self, settings: Settings, http_client: httpx.AsyncClient, auth: AuthSession) -> None:
        self.settings = settings
        self.http = http_client
        self.auth = auth

    async def query_with_recovery(
        self,
        question: str,
        *,
        trace_session: str,
        conversation_title: str,
    ) -> QueryEvidence:
        try:
            async with asyncio.timeout(self.settings.question_timeout_seconds):
                return await self._query_with_recovery_no_timeout(
                    question,
                    trace_session=trace_session,
                    conversation_title=conversation_title,
                )
        except TimeoutError:
            return QueryEvidence(
                timed_out=True,
                error=f"question timed out after {self.settings.question_timeout_seconds:g}s",
            )

    async def _query_with_recovery_no_timeout(
        self,
        question: str,
        *,
        trace_session: str,
        conversation_title: str,
    ) -> QueryEvidence:
        retry_count = 0
        auth_recovered = False
        for attempt in range(2):
            try:
                result = await self._query_once(
                    question,
                    trace_session=trace_session,
                    conversation_title=conversation_title,
                )
                result.retry_count = retry_count
                result.auth_recovered = auth_recovered
                return result
            except QueryHttpError as exc:
                if exc.status_code == 401 and attempt == 0:
                    await self.auth.recover()
                    retry_count += 1
                    auth_recovered = True
                    continue
                return QueryEvidence(
                    status_code=exc.status_code,
                    error=exc.message,
                    retry_count=retry_count,
                    auth_recovered=auth_recovered,
                )
        return QueryEvidence(error="query failed after auth recovery")

    async def _query_once(
        self,
        question: str,
        *,
        trace_session: str,
        conversation_title: str,
    ) -> QueryEvidence:
        started = time.perf_counter()
        headers = {
            **await self.auth.auth_headers(),
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        body = {
            "question": question,
            "user_id": self.auth.user_id,
            "trace_session": trace_session,
            "conversation_title": conversation_title,
        }
        events: list[dict[str, Any]] = []
        answer_parts: list[str] = []
        first_token_latency: float | None = None
        status_code: int | None = None
        async with self.http.stream(
            "POST",
            f"{self.settings.query_base_url}/query",
            headers=headers,
            json=body,
            timeout=httpx.Timeout(self.settings.question_timeout_seconds, connect=10.0),
        ) as response:
            status_code = response.status_code
            if response.status_code != 200:
                raw = (await response.aread()).decode("utf-8", errors="replace")
                raise QueryHttpError(response.status_code, raw[:1000] or f"HTTP {response.status_code}")
            buffer = ""
            stream_error: str | None = None
            try:
                async for chunk in response.aiter_text():
                    buffer += chunk
                    while "\n\n" in buffer:
                        packet, buffer = buffer.split("\n\n", 1)
                        parsed = parse_sse_packet(packet)
                        if parsed is None:
                            continue
                        events.append({"event_index": len(events), "received_at": utc_now(), "data": parsed})
                        token = parsed.get("token")
                        if token is not None:
                            if first_token_latency is None:
                                first_token_latency = time.perf_counter() - started
                            answer_parts.append(str(token))
            except (httpx.RemoteProtocolError, httpx.ReadError) as exc:
                # Server dropped the SSE connection mid-stream; keep whatever was buffered.
                stream_error = f"stream_cut: {exc}"
        ended = time.perf_counter()
        data_events = [event["data"] for event in events]
        done = next((event for event in reversed(data_events) if event.get("done") is True), None)
        sources = (done or {}).get("sources") or []
        return QueryEvidence(
            status_code=status_code,
            answer="".join(answer_parts),
            events=events,
            sources=sources if isinstance(sources, list) else [],
            done=done,
            first_token_latency_seconds=first_token_latency,
            total_latency_seconds=ended - started,
            error=stream_error,
        )

    async def list_documents(self) -> dict[str, Any]:
        candidates = [
            f"{self.settings.document_base_url}/",
            f"{self.settings.document_base_url}/documents",
        ]
        last_error: str | None = None
        for url in candidates:
            result = await self._list_documents_from_url(url)
            if result.get("ok"):
                result["url_shape"] = url.replace(self.settings.prod_base_url, "")
                return result
            last_error = str(result.get("error") or "document list failed")
        return {"ok": False, "error": last_error or "document list failed", "documents": []}

    async def _list_documents_from_url(self, url: str) -> dict[str, Any]:
        try:
            documents: list[dict[str, Any]] = []
            offset = 0
            while True:
                response = await self.http.get(
                    url,
                    headers=await self.auth.auth_headers(),
                    params={"limit": 100, "offset": offset},
                    timeout=30,
                )
                response.raise_for_status()
                payload = response.json()
                if isinstance(payload, list):
                    items = payload
                    total = len(payload)
                else:
                    items = payload.get("items") or payload.get("documents") or []
                    total = payload.get("total")
                if not isinstance(items, list):
                    return {"ok": False, "error": f"unexpected document list shape: {type(items).__name__}", "documents": []}
                documents.extend(item for item in items if isinstance(item, dict))
                if not items or len(items) < 100:
                    break
                offset += len(items)
                if isinstance(total, int) and offset >= total:
                    break
            return {"ok": True, "documents": documents}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc), "documents": []}

    async def retrieval_probe(self, question: str, document_ids: list[str]) -> dict[str, Any]:
        if not self.settings.mcp_url:
            return {"ok": False, "reason": "MCP_URL is not configured", "results": []}
        if not document_ids:
            return {"ok": False, "reason": "no document ids available for MCP probe", "results": []}
        try:
            probe_path = EVAL_ROOT / "lib" / "mcp_probe.py"
            spec = importlib.util.spec_from_file_location("production_test_mcp_probe", probe_path)
            if spec is None or spec.loader is None:
                raise RuntimeError(f"Cannot load MCP probe from {probe_path}")
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
            return await module.rag_search_probe(
                self.settings.mcp_url,
                question,
                document_ids,
                top_k=8,
                internal_token=self.settings.mcp_internal_token,
            )
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "reason": str(exc), "results": []}


def parse_sse_packet(packet: str) -> dict[str, Any] | None:
    data_lines: list[str] = []
    for raw_line in packet.splitlines():
        line = raw_line.strip()
        if line.startswith("data:"):
            data_lines.append(line[5:].strip())
    if not data_lines:
        return None
    try:
        parsed = json.loads("\n".join(data_lines))
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None


def document_keys(document: dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    for field in ("name", "document_name", "filename", "file_name", "original_filename", "title", "source_gcs_uri"):
        value = document.get(field)
        if not value:
            continue
        text = str(value).replace("\\", "/")
        keys.add(_norm(text))
        keys.add(_norm(Path(text).name))
    return {key for key in keys if key}


def build_document_map(documents: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for document in documents:
        for key in document_keys(document):
            out.setdefault(key, document)
    return out


def document_id(document: dict[str, Any] | None) -> str | None:
    if not document:
        return None
    value = document.get("id") or document.get("document_id") or document.get("doc_id")
    return str(value) if value else None


def source_doc_ids(sources: list[dict[str, Any]]) -> list[str]:
    seen: set[str] = set()
    ids: list[str] = []
    for source in sources:
        value = source.get("document_id")
        if value and str(value) not in seen:
            seen.add(str(value))
            ids.append(str(value))
    return ids


def source_doc_names(sources: list[dict[str, Any]]) -> list[str]:
    return sorted({
        str(source.get("document_name") or source.get("document_id") or "")
        for source in sources
        if str(source.get("document_name") or source.get("document_id") or "").strip()
    })


def retrieval_rows_from_probe(
    *,
    question_id: str,
    source_doc: str,
    probe: dict[str, Any],
    fallback_sources: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if probe.get("ok") and isinstance(probe.get("results"), list):
        for rank, item in enumerate(probe["results"], start=1):
            text = str(item.get("parent_text") or item.get("text") or item.get("content") or item.get("caption") or "")
            rows.append({
                "ts": utc_now(),
                "question_id": question_id,
                "rank": rank,
                "chunk_id": item.get("chunk_id"),
                "document_id": item.get("document_id") or item.get("doc_id"),
                "document_name": item.get("document_name") or item.get("doc_name"),
                "source_doc": source_doc,
                "score": item.get("score"),
                "page_number": item.get("page_number") or item.get("page"),
                "heading_path": item.get("heading_path") or item.get("section"),
                "caption": item.get("caption"),
                "text": text,
                "text_preview": text[:500],
                "probe_ok": True,
                "probe_error": None,
            })
        return rows

    reason = probe.get("reason") or probe.get("error") or "retrieval probe unavailable"
    for rank, source in enumerate(fallback_sources, start=1):
        text = str(source.get("caption") or "")
        rows.append({
            "ts": utc_now(),
            "question_id": question_id,
            "rank": rank,
            "chunk_id": source.get("chunk_id"),
            "document_id": source.get("document_id"),
            "document_name": source.get("document_name"),
            "source_doc": source_doc,
            "score": source.get("score"),
            "page_number": source.get("page_number"),
            "heading_path": source.get("heading_path"),
            "caption": source.get("caption"),
            "text": text,
            "text_preview": text[:500],
            "probe_ok": False,
            "probe_error": reason,
        })
    return rows


def _norm(value: str) -> str:
    return value.replace("\\", "/").strip().lower()
