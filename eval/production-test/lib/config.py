from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


PRODUCTION_TEST_ROOT = Path(__file__).resolve().parents[1]
EVAL_ROOT = PRODUCTION_TEST_ROOT.parent
REPO_ROOT = EVAL_ROOT.parent


def load_env_file(path: Path, *, override: bool = False) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and (override or key not in os.environ):
            os.environ[key] = value


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


@dataclass(frozen=True)
class Settings:
    prod_base_url: str
    prod_api_base_url: str
    prod_email: str
    prod_password: str
    prod_access_token: str | None
    prod_refresh_token: str | None
    user_service_path: str
    query_service_path: str
    document_service_path: str
    mcp_url: str | None
    mcp_internal_token: str | None
    gateway_basic_auth: str | None
    dataset_root: Path
    dataset: str
    output_root: Path
    question_timeout_seconds: float
    concurrency: int
    limit: int | None
    question_offset: int
    dry_run: bool

    @property
    def user_base_url(self) -> str:
        return join_url(self.prod_api_base_url, self.user_service_path)

    @property
    def query_base_url(self) -> str:
        return join_url(self.prod_api_base_url, self.query_service_path)

    @property
    def document_base_url(self) -> str:
        return join_url(self.prod_api_base_url, self.document_service_path)

    def public_manifest_config(self) -> dict[str, object]:
        return {
            "prod_base_url": self.prod_base_url,
            "prod_api_base_url": self.prod_api_base_url,
            "user_service_path": self.user_service_path,
            "query_service_path": self.query_service_path,
            "document_service_path": self.document_service_path,
            "mcp_url_configured": bool(self.mcp_url),
            "gateway_basic_auth_configured": bool(self.gateway_basic_auth),
            "dataset_root": str(self.dataset_root),
            "dataset": self.dataset,
            "question_timeout_seconds": self.question_timeout_seconds,
            "concurrency": self.concurrency,
            "limit": self.limit,
            "question_offset": self.question_offset,
            "dry_run": self.dry_run,
        }


def validate_settings(settings: Settings) -> None:
    parsed = urlparse(settings.prod_base_url)
    host = (parsed.hostname or "").strip().lower()
    if not parsed.scheme or not host:
        raise SystemExit(
            "Invalid PROD_BASE_URL. Expected a full base URL such as "
            "`https://chat.company.internal` or `http://localhost`."
        )
    if host in {"your-production-host.example.com", "example.com"}:
        raise SystemExit(
            "PROD_BASE_URL in `eval/production-test/.env` is still the placeholder "
            f"`{settings.prod_base_url}`. Replace it with the real gateway URL, then rerun."
        )
    parsed_api = urlparse(settings.prod_api_base_url)
    if not parsed_api.scheme or not parsed_api.hostname:
        raise SystemExit(
            "Invalid production API base URL derived from configuration. "
            "Set `PROD_API_BASE_URL` explicitly if your API lives on a different origin."
        )


def join_url(base: str, path: str) -> str:
    return f"{base.rstrip('/')}/{path.strip('/')}"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Production evidence logger for Phase 1.5 evaluation inputs.")
    parser.add_argument("--env-file", default=str(PRODUCTION_TEST_ROOT / ".env"))
    parser.add_argument("--dataset", default=None)
    parser.add_argument("--dataset-root", default=None)
    parser.add_argument("--output-root", default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--question-offset", type=int, default=0)
    parser.add_argument("--concurrency", type=int, default=None)
    parser.add_argument("--question-timeout-seconds", type=float, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--smoke", action="store_true", help="Run one question with concurrency=1.")
    return parser.parse_args(argv)


def settings_from_env(args: argparse.Namespace) -> Settings:
    load_env_file(PRODUCTION_TEST_ROOT / ".env", override=False)
    env_file = Path(args.env_file)
    load_env_file(env_file if env_file.is_absolute() else (REPO_ROOT / env_file), override=True)

    limit = args.limit if args.limit is not None else _env_int("LIMIT", 30)
    concurrency = args.concurrency if args.concurrency is not None else _env_int("CONCURRENCY", 5)
    if args.smoke:
        limit = 1
        concurrency = 1

    dataset_root = Path(args.dataset_root or os.getenv("DATASET_ROOT", "eval/dataset"))
    output_root = Path(args.output_root or os.getenv("OUTPUT_ROOT", "eval/production-test/output"))
    return Settings(
        prod_base_url=_required("PROD_BASE_URL").rstrip("/"),
        prod_api_base_url=_api_base_url(_required("PROD_BASE_URL"), _optional("PROD_API_BASE_URL")),
        prod_email=_required("PROD_EMAIL"),
        prod_password=_required("PROD_PASSWORD"),
        prod_access_token=_optional("PROD_ACCESS_TOKEN"),
        prod_refresh_token=_optional("PROD_REFRESH_TOKEN"),
        user_service_path=os.getenv("USER_SERVICE_PATH", "/api/user"),
        query_service_path=os.getenv("QUERY_SERVICE_PATH", "/api/query"),
        document_service_path=os.getenv("DOCUMENT_SERVICE_PATH", "/api/documents"),
        mcp_url=_optional("MCP_URL"),
        mcp_internal_token=_optional("MCP_INTERNAL_TOKEN"),
        gateway_basic_auth=_optional("GATEWAY_BASIC_AUTH"),
        dataset_root=_resolve_path(dataset_root),
        dataset=args.dataset or os.getenv("DATASET", "dataset_new"),
        output_root=_resolve_path(output_root),
        question_timeout_seconds=(
            args.question_timeout_seconds
            if args.question_timeout_seconds is not None
            else float(os.getenv("QUESTION_TIMEOUT_SECONDS", "30"))
        ),
        concurrency=max(1, int(concurrency)),
        limit=limit if limit and limit > 0 else None,
        question_offset=max(0, int(args.question_offset or 0)),
        dry_run=bool(args.dry_run),
    )


def _required(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise SystemExit(f"Missing required environment variable: {name}")
    return value


def _optional(name: str) -> str | None:
    value = os.getenv(name)
    if value is None or not value.strip():
        return None
    return value.strip()


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _resolve_path(path: Path) -> Path:
    return path if path.is_absolute() else (REPO_ROOT / path).resolve()


def _api_base_url(prod_base_url: str, explicit_api_base: str | None) -> str:
    if explicit_api_base:
        return explicit_api_base.rstrip("/")
    parsed = urlparse(prod_base_url)
    if not parsed.scheme or not parsed.netloc:
        return prod_base_url.rstrip("/")
    return f"{parsed.scheme}://{parsed.netloc}"
