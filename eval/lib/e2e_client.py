from __future__ import annotations

import asyncio
import base64
import json
import os
import shlex
import statistics
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx


OUTCOME = {
    1: "REFUSE",
    2: "CLARIFY",
    3: "NO_INFO",
    4: "OFF_TOPIC",
    5: "SUCCESS",
    6: "ERROR",
}


@dataclass(frozen=True)
class EvalConfig:
    user_url: str = "http://localhost:8000"
    query_url: str = "http://localhost:8001"
    doc_url: str = "http://localhost:8002"
    mcp_url: str = "http://localhost:8003"
    admin_email: str = "admin@company.com"
    admin_password: str = "DemoAdminPassword123!"
    jwt_secret: str = "e2e-jwt-secret-shared-across-services-32ch"
    jwt_algorithm: str = "HS256"
    qdrant_url: str | None = None
    qdrant_api_key: str | None = None
    qdrant_basic_auth: str | None = None
    qdrant_collection: str = "rag_chatbot__te3s__d1536"
    qdrant_mode: str = "rest"
    qdrant_docker_prefix: str = "sudo docker compose"
    qdrant_docker_compose_file: str | None = None
    qdrant_docker_service: str = "mcp-service"
    ingest_timeout_seconds: int = 900
    total_employees: int = 100

    @classmethod
    def from_env(cls, target: str = "e2e-local") -> "EvalConfig":
        collection = os.getenv("QDRANT_COLLECTION") or os.getenv("VECTOR_COLLECTION") or "rag_chatbot"
        embed_model = os.getenv("OPENAI_EMBEDDING_MODEL") or os.getenv("EMBED_MODEL") or "text-embedding-3-small"
        dimension = int(os.getenv("EMBED_DIMENSION") or "1536")
        qdrant_collection = _contract_collection(collection, embed_model, dimension)
        qdrant_mode = (os.getenv("QDRANT_MODE") or ("docker_exec" if target in {"vm-local", "production-vm"} else "rest")).strip().lower()
        return cls(
            user_url=os.getenv("USER_URL", cls.user_url).rstrip("/"),
            query_url=os.getenv("QUERY_URL", cls.query_url).rstrip("/"),
            doc_url=os.getenv("DOC_URL", cls.doc_url).rstrip("/"),
            mcp_url=os.getenv("MCP_URL", cls.mcp_url).rstrip("/"),
            admin_email=os.getenv("SEED_ADMIN_EMAIL", cls.admin_email),
            admin_password=os.getenv("SEED_ADMIN_PASSWORD", cls.admin_password),
            jwt_secret=os.getenv("JWT_SECRET_KEY", cls.jwt_secret),
            jwt_algorithm=os.getenv("JWT_ALGORITHM", cls.jwt_algorithm),
            qdrant_url=(os.getenv("QDRANT_URL") or os.getenv("VECTOR_DB_URL") or "").rstrip("/") or None,
            qdrant_api_key=os.getenv("QDRANT_API_KEY") or os.getenv("VECTOR_DB_API_KEY") or None,
            qdrant_basic_auth=os.getenv("VECTOR_DB_BASIC_AUTH") or os.getenv("QDRANT_BASIC_AUTH") or None,
            qdrant_collection=os.getenv("EVAL_QDRANT_COLLECTION", qdrant_collection),
            qdrant_mode=qdrant_mode,
            qdrant_docker_prefix=os.getenv("QDRANT_DOCKER_PREFIX", cls.qdrant_docker_prefix),
            qdrant_docker_compose_file=os.getenv("QDRANT_DOCKER_COMPOSE_FILE") or None,
            qdrant_docker_service=os.getenv("QDRANT_DOCKER_SERVICE", cls.qdrant_docker_service),
            ingest_timeout_seconds=int(os.getenv("EVAL_INGEST_TIMEOUT_SECONDS", str(cls.ingest_timeout_seconds))),
            total_employees=int(os.getenv("EVAL_TOTAL_EMPLOYEES", str(cls.total_employees))),
        )

    @property
    def has_qdrant_access(self) -> bool:
        return bool(self.qdrant_url or self.qdrant_mode == "docker_exec")


@dataclass(frozen=True)
class LoginResult:
    token: str
    user_id: str


class E2EClient:
    def __init__(self, config: EvalConfig) -> None:
        self.config = config
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=10.0))

    async def aclose(self) -> None:
        await self._client.aclose()

    async def preflight(self) -> dict[str, Any]:
        checks: dict[str, Any] = {}
        for name, url in {
            "user": self.config.user_url,
            "query": self.config.query_url,
            "document": self.config.doc_url,
            "mcp": self.config.mcp_url,
        }.items():
            try:
                response = await self._client.get(f"{url}/health")
                checks[name] = {"ok": response.status_code < 500, "status_code": response.status_code}
            except Exception as exc:  # noqa: BLE001
                checks[name] = {"ok": False, "error": str(exc)}
        return checks

    async def login_admin(self) -> LoginResult:
        response = await self._client.post(
            f"{self.config.user_url}/auth/login",
            json={"email": self.config.admin_email, "password": self.config.admin_password},
        )
        response.raise_for_status()
        token = str(response.json()["access_token"])
        return LoginResult(token=token, user_id=_jwt_user_id(token))

    def signed_eval_user_token(
        self,
        *,
        user_id: str = "33333333-3333-4333-8333-333333333333",
        email: str = "eval.user@company.com",
        role: str = "user",
        department: str = "Eval",
        account_type: str = "internal",
    ) -> str:
        try:
            import jwt
        except ImportError as exc:
            raise RuntimeError("PyJWT is required to sign eval user tokens") from exc
        now = datetime.now(timezone.utc)
        payload = {
            "sub": user_id,
            "user_id": user_id,
            "email": email,
            "role": role,
            "department": department,
            "account_type": account_type,
            "is_active": True,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(hours=8)).timestamp()),
        }
        return jwt.encode(payload, self.config.jwt_secret, algorithm=self.config.jwt_algorithm)

    async def upload_document(
        self,
        token: str,
        path: Path,
        *,
        classification: str = "public",
        allowed_departments: str | None = None,
        allowed_user_ids: str | None = None,
    ) -> dict[str, Any]:
        data: dict[str, str] = {"classification": classification}
        if allowed_departments:
            data["allowed_departments"] = allowed_departments
        if allowed_user_ids:
            data["allowed_user_ids"] = allowed_user_ids
        with path.open("rb") as fh:
            response = await self._client.post(
                f"{self.config.doc_url}/documents/upload",
                headers={"Authorization": f"Bearer {token}"},
                files={"file": (path.name, fh)},
                data=data,
            )
        payload: dict[str, Any]
        try:
            payload = response.json()
        except Exception:  # noqa: BLE001
            payload = {"text": response.text}
        payload["status_code"] = response.status_code
        if response.status_code == 202:
            payload["ok"] = True
        else:
            payload["ok"] = False
        return payload

    async def delete_document(self, token: str, document_id: str) -> dict[str, Any]:
        response = await self._client.delete(
            f"{self.config.doc_url}/documents/{document_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        try:
            payload = response.json()
        except Exception:  # noqa: BLE001
            payload = {"text": response.text}
        payload["status_code"] = response.status_code
        return payload

    async def list_documents(self, token: str, *, status: str | None = None, page_size: int = 100) -> list[dict[str, Any]]:
        documents: list[dict[str, Any]] = []
        offset = 0
        total: int | None = None
        while True:
            params: dict[str, Any] = {"limit": page_size, "offset": offset}
            if status:
                params["status"] = status
            response = await self._client.get(
                f"{self.config.doc_url}/documents",
                headers={"Authorization": f"Bearer {token}"},
                params=params,
            )
            response.raise_for_status()
            payload = response.json()
            if isinstance(payload, list):
                items = payload
                total = len(payload)
            else:
                items = payload.get("items") or payload.get("documents") or []
                if isinstance(payload.get("total"), int):
                    total = int(payload["total"])
            if not isinstance(items, list):
                raise RuntimeError(f"Unexpected /documents response shape: {type(items).__name__}")
            documents.extend([item for item in items if isinstance(item, dict)])
            if not items:
                break
            offset += len(items)
            if total is not None and offset >= total:
                break
            if len(items) < page_size:
                break
        return documents

    async def query_sse(
        self,
        token: str,
        user_id: str,
        question: str,
        *,
        trace_session: str | None = None,
        conversation_title: str | None = None,
        document_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        first_token_latency: float | None = None
        events: list[dict[str, Any]] = []
        answer_parts: list[str] = []
        error: str | None = None
        status_code: int | None = None
        body = {"question": question, "user_id": user_id}
        if trace_session:
            body["trace_session"] = trace_session
        if conversation_title:
            body["conversation_title"] = conversation_title
        if document_ids is not None:
            body["document_ids"] = list(document_ids)
        try:
            async with self._client.stream(
                "POST",
                f"{self.config.query_url}/query",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json=body,
                timeout=httpx.Timeout(180.0, connect=10.0),
            ) as response:
                status_code = response.status_code
                if response.status_code != 200:
                    error = await response.aread()
                    error = str(error)[:1000]
                else:
                    buffer = ""
                    async for chunk in response.aiter_text():
                        buffer += chunk
                        while "\n\n" in buffer:
                            packet, buffer = buffer.split("\n\n", 1)
                            parsed = _parse_sse_packet(packet)
                            if parsed is None:
                                continue
                            events.append(parsed)
                            token_text = parsed.get("token")
                            if token_text is not None:
                                if first_token_latency is None:
                                    first_token_latency = time.perf_counter() - started
                                answer_parts.append(str(token_text))
        except Exception as exc:  # noqa: BLE001
            error = str(exc)
        ended = time.perf_counter()
        done = next((event for event in reversed(events) if event.get("done") is True), None)
        tool_events = [event for event in events if event.get("tool") or event.get("phase") in {"acting", "observing"}]
        return {
            "status_code": status_code,
            "answer": "".join(answer_parts),
            "events": events,
            "done": done,
            "tool_events": tool_events,
            "sources": (done or {}).get("sources") or [],
            "session_id": (done or {}).get("session_id"),
            "trace_id": (done or {}).get("trace_id"),
            "outcome": (done or {}).get("outcome"),
            "outcome_name": OUTCOME.get((done or {}).get("outcome"), str((done or {}).get("outcome"))),
            "fallback": bool((done or {}).get("fallback")),
            "cached": bool((done or {}).get("cached")),
            "effective_document_ids": (done or {}).get("effective_document_ids") or [],
            "first_token_latency_seconds": first_token_latency,
            "total_latency_seconds": ended - started,
            "error": error,
        }

    async def send_feedback(self, token: str, session_id: str, score: int, trace_id: str | None = None) -> dict[str, Any]:
        response = await self._client.post(
            f"{self.config.query_url}/feedback",
            headers={"Authorization": f"Bearer {token}"},
            json={"session_id": session_id, "score": score, "trace_id": trace_id},
        )
        try:
            payload = response.json()
        except Exception:  # noqa: BLE001
            payload = {"text": response.text}
        payload["status_code"] = response.status_code
        return payload

    async def admin_metrics(self, token: str) -> dict[str, Any]:
        response = await self._client.get(
            f"{self.config.query_url}/admin/metrics",
            headers={"Authorization": f"Bearer {token}"},
        )
        try:
            payload = response.json()
        except Exception:  # noqa: BLE001
            payload = {"text": response.text}
        payload["status_code"] = response.status_code
        return payload

    async def wait_for_ingest(self, document_ids: list[str]) -> dict[str, Any]:
        expected = set(document_ids)
        if not expected:
            return {"ok": True, "expected": 0, "seen": 0, "document_ids": []}
        deadline = time.monotonic() + self.config.ingest_timeout_seconds
        last_seen: set[str] = set()
        last_error: str | None = None
        while time.monotonic() < deadline:
            try:
                last_seen = await self.qdrant_seen_doc_ids(expected)
                if expected <= last_seen:
                    return {
                        "ok": True,
                        "expected": len(expected),
                        "seen": len(last_seen & expected),
                        "document_ids": sorted(last_seen & expected),
                    }
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
            await asyncio.sleep(5)
        return {
            "ok": False,
            "expected": len(expected),
            "seen": len(last_seen & expected),
            "document_ids": sorted(last_seen & expected),
            "error": last_error or "timeout",
        }

    async def qdrant_seen_doc_ids(self, wanted: set[str]) -> set[str]:
        if not self.config.has_qdrant_access:
            raise RuntimeError("QDRANT_URL/VECTOR_DB_URL or QDRANT_MODE=docker_exec is required for ingest polling")
        seen: set[str] = set()
        offset: Any = None
        while True:
            body: dict[str, Any] = {
                "limit": 256,
                "with_payload": ["document_id"],
                "with_vector": False,
                "filter": {
                    "must": [
                        {
                            "key": "document_id",
                            "match": {"any": sorted(wanted)},
                        }
                    ]
                },
            }
            if offset is not None:
                body["offset"] = offset
            payload = await self._qdrant("POST", f"/collections/{self.config.qdrant_collection}/points/scroll", body)
            result = payload.get("result") or {}
            for point in result.get("points") or []:
                doc_id = ((point or {}).get("payload") or {}).get("document_id")
                if doc_id:
                    seen.add(str(doc_id))
            offset = result.get("next_page_offset")
            if not offset:
                return seen

    async def qdrant_delete_documents(self, document_ids: list[str]) -> dict[str, Any]:
        if not document_ids:
            return {"ok": True, "deleted_filter_doc_ids": []}
        if not self.config.has_qdrant_access:
            return {"ok": False, "reason": "QDRANT_URL/VECTOR_DB_URL or QDRANT_MODE=docker_exec is not configured"}
        body = {
            "filter": {
                "must": [
                    {
                        "key": "document_id",
                        "match": {"any": document_ids},
                    }
                ]
            }
        }
        try:
            payload = await self._qdrant("POST", f"/collections/{self.config.qdrant_collection}/points/delete", body)
            return {"ok": True, "deleted_filter_doc_ids": document_ids, "response": payload}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "reason": str(exc), "deleted_filter_doc_ids": document_ids}

    async def _qdrant(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.config.qdrant_url and self.config.qdrant_mode == "docker_exec":
            return await self._qdrant_via_docker_exec(method, path, body)
        if not self.config.qdrant_url:
            raise RuntimeError("QDRANT_URL/VECTOR_DB_URL is not configured")
        headers: dict[str, str] = {}
        if self.config.qdrant_api_key:
            headers["api-key"] = self.config.qdrant_api_key
        if self.config.qdrant_basic_auth and ":" in self.config.qdrant_basic_auth:
            headers["Authorization"] = "Basic " + base64.b64encode(self.config.qdrant_basic_auth.encode()).decode()
        response = await self._client.request(
            method,
            f"{self.config.qdrant_url}{path}",
            headers=headers,
            json=body,
            timeout=httpx.Timeout(60.0, connect=10.0),
        )
        response.raise_for_status()
        return response.json() if response.content else {}

    async def _qdrant_via_docker_exec(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        script = r"""
import json
import sys
import urllib.error
import urllib.request

payload = json.load(sys.stdin)
data = None
headers = {}
if payload.get("body") is not None:
    data = json.dumps(payload["body"]).encode("utf-8")
    headers["Content-Type"] = "application/json"
request = urllib.request.Request(
    "http://qdrant:6333" + payload["path"],
    data=data,
    headers=headers,
    method=payload["method"],
)
try:
    with urllib.request.urlopen(request, timeout=60) as response:
        raw = response.read().decode("utf-8")
        print(raw or "{}")
except urllib.error.HTTPError as exc:
    raw = exc.read().decode("utf-8", errors="replace")
    print(json.dumps({"error": raw, "status_code": exc.code}))
    sys.exit(1)
"""
        command = shlex.split(self.config.qdrant_docker_prefix)
        if self.config.qdrant_docker_compose_file:
            command.extend(["-f", self.config.qdrant_docker_compose_file])
        command.extend(["exec", "-T", self.config.qdrant_docker_service, "python", "-c", script])
        payload = json.dumps({"method": method, "path": path, "body": body}).encode("utf-8")

        def run() -> subprocess.CompletedProcess[bytes]:
            return subprocess.run(command, input=payload, capture_output=True, check=False)

        proc = await asyncio.to_thread(run)
        stdout = proc.stdout.decode("utf-8", errors="replace").strip()
        stderr = proc.stderr.decode("utf-8", errors="replace").strip()
        if proc.returncode != 0:
            message = stderr or stdout or f"docker exec qdrant request failed with exit code {proc.returncode}"
            raise RuntimeError(message)
        return json.loads(stdout) if stdout else {}


def percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    index = (len(values) - 1) * pct
    lower = int(index)
    upper = min(lower + 1, len(values) - 1)
    if lower == upper:
        return values[lower]
    return values[lower] + (values[upper] - values[lower]) * (index - lower)


def summarize_latencies(rows: list[dict[str, Any]]) -> dict[str, Any]:
    first = [float(r["first_token_latency_seconds"]) for r in rows if r.get("first_token_latency_seconds") is not None]
    total = [float(r["total_latency_seconds"]) for r in rows if r.get("total_latency_seconds") is not None]
    return {
        "count": len(rows),
        "first_token_median_seconds": statistics.median(first) if first else None,
        "first_token_p95_seconds": percentile(first, 0.95),
        "response_median_seconds": statistics.median(total) if total else None,
        "response_p95_seconds": percentile(total, 0.95),
    }


def _parse_sse_packet(packet: str) -> dict[str, Any] | None:
    data_lines = []
    for raw_line in packet.splitlines():
        line = raw_line.strip()
        if line.startswith("data:"):
            data_lines.append(line[5:].strip())
    if not data_lines:
        return None
    try:
        return json.loads("\n".join(data_lines))
    except json.JSONDecodeError:
        return None


def _jwt_user_id(token: str) -> str:
    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    data = json.loads(base64.urlsafe_b64decode(payload.encode()).decode())
    return str(data.get("user_id") or data.get("sub") or data.get("id") or "")


def _contract_collection(collection: str, embed_model: str, dimension: int) -> str:
    tags = {
        "text-embedding-3-small": "te3s",
        "text-embedding-3-large": "te3l",
        "bge-m3": "bgem3",
        "offline": "offline",
    }
    tag = tags.get(embed_model.strip().lower(), embed_model.strip().lower().replace("-", "_"))
    return f"{collection}__{tag}__d{int(dimension)}"
