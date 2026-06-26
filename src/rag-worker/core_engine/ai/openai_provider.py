"""OpenAIProvider — AIProvider hiện thực bằng OpenAI SDK (openai.AsyncOpenAI).

MỘT điểm vào SDK duy nhất cho mọi call AI. OpenAI-compatible nên `base_url` trỏ
được vLLM / OpenRouter / BGE-M3-served-as-OpenAI / AI gateway tập trung mà KHÔNG
đổi nơi gọi (embedding.md §5). Mỗi capability (embed/caption/rerank) có thể trỏ
endpoint/model riêng; client `AsyncOpenAI` được cache theo (base_url, api_key) để
tái dùng connection pool.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from core_engine.ai.base import (
    AIProvider,
    AISettings,
    CapabilityConfig,
    EMBED,
    OCR,
    PermanentAIError,
    TransientAIError,
    VisionImage,
    load_ai_settings,
    retry_async,
)

if TYPE_CHECKING:
    from openai import AsyncOpenAI


class OpenAIProvider(AIProvider):
    def __init__(self, settings: AISettings | None = None):
        self._s = settings or load_ai_settings()
        self._clients: Dict[Tuple[Optional[str], str], Any] = {}

    @property
    def name(self) -> str:
        return "openai"

    # --- client pool (1 AsyncOpenAI / endpoint) ---------------------------- #
    def _client(self, cfg: CapabilityConfig):
        key = (cfg.base_url, cfg.api_key)
        client = self._clients.get(key)
        if client is None:
            try:
                from openai import AsyncOpenAI
            except ModuleNotFoundError as exc:
                raise ModuleNotFoundError(
                    "OpenAIProvider can openai package. Cai: pip install openai"
                ) from exc
            client = AsyncOpenAI(
                api_key=cfg.api_key or "EMPTY",   # OpenAI-compatible local thường bỏ qua key
                base_url=cfg.base_url,
                max_retries=0,                    # retry policy đồng nhất ở retry_async
                timeout=self._s.timeout,
            )
            self._clients[key] = client
        return client

    # --- config validation (fail-fast, embedding.md §4) -------------------- #
    def validate(self) -> None:
        for name in (EMBED, "caption", OCR):
            cfg = self._s.cap(name)
            if not cfg.model:
                raise ValueError(f"AI config thiếu model cho capability '{name}'")
            # Provider OpenAI thật (không base_url) bắt buộc có key.
            if cfg.base_url is None and not cfg.api_key:
                raise ValueError(
                    f"AI config '{name}': thiếu API key (set *_API_KEY/OPENAI_API_KEY "
                    "hoặc *_BASE_URL trỏ provider OpenAI-compatible local)."
                )

    # --- capabilities ------------------------------------------------------ #
    async def embed(
        self, texts: List[str], *, dimension: Optional[int] = None
    ) -> List[List[float]]:
        if not texts:
            return []
        cfg = self._s.embed
        client = self._client(cfg)
        dim = dimension if dimension is not None else self._s.embed_dimension

        async def _call():
            kwargs = {"model": cfg.model, "input": texts}
            if dim is not None:
                kwargs["dimensions"] = dim   # text-embedding-3-* hỗ trợ; provider khác bỏ qua
            # ÉP encoding_format=float (GỐC CUỐI của TypeError-NoneType giết doc dưới tải):
            # KHÔNG set -> OpenAI SDK mặc định gửi base64 + gắn post-parser decode chạy
            # `for embedding in obj.data`. Khi gateway shed/degraded trả data=null, vòng đó
            # lặp `for x in None` -> TypeError NGAY TRONG create(), TRƯỚC guard dưới -> không
            # map được transient -> permanent -> doc chết (đo: 18% fail @conc=120). Set 'float'
            # -> SDK BỎ post-parser -> data=None xuống guard -> TransientAIError -> retry.
            kwargs["encoding_format"] = "float"
            try:
                res = await client.embeddings.create(**kwargs)
            except Exception as exc:  # noqa: BLE001 - SDK-specific mapping stays in adapter
                raise self._map_error(exc, cfg.base_url) from exc
            # DEGRADED guard: gateway/provider có thể trả HTTP 200 nhưng body thiếu `data`
            # (rate-shed dưới tải / envelope lỗi upstream) -> SDK cho res.data=None. KHÔNG để
            # rơi xuống sorted(res.data) -> TypeError 'NoneType' không iterate -> classify_ingest_error
            # xếp PERMANENT (doc chết, KHÔNG retry). Raise TransientAIError TRONG _call -> retry_async
            # tự thử lại (đổi key qua ai-router); cạn retry -> job-level transient retry. Thiếu/thừa
            # vector so input -> map index sai -> cũng transient.
            data = getattr(res, "data", None)
            if not data or len(data) != len(texts):
                raise TransientAIError(
                    f"embed degraded: response thiếu/lệch 'data' "
                    f"(got={None if data is None else len(data)}, want={len(texts)}, model={cfg.model})"
                )
            return res

        res = await retry_async(_call, max_retries=self._s.max_retries)
        # API trả theo `index` — sort lại để chắc chắn khớp thứ tự input.
        data = sorted(res.data, key=lambda d: d.index)
        return [d.embedding for d in data]

    async def chat(
        self,
        user: str,
        *,
        system: Optional[str] = None,
        capability: str = "caption",
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
    ) -> str:
        cfg = self._s.cap(capability)
        client = self._client(cfg)
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user})

        async def _call():
            try:
                res = await client.chat.completions.create(
                    model=cfg.model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            except Exception as exc:  # noqa: BLE001 - SDK-specific mapping stays in adapter
                raise self._map_error(exc, cfg.base_url) from exc
            # DEGRADED guard (xem embed): 200 nhưng thiếu choices -> res.choices[0] TypeError/
            # IndexError unmapped -> PERMANENT. Xếp transient -> retry-across-keys.
            if not getattr(res, "choices", None):
                raise TransientAIError(f"chat degraded: response thiếu 'choices' (model={cfg.model})")
            return res

        res = await retry_async(_call, max_retries=self._s.max_retries)
        return (res.choices[0].message.content or "").strip()

    async def extract_text_from_images(
        self,
        images: List[VisionImage],
        *,
        prompt: str,
        capability: str = OCR,
        max_tokens: Optional[int] = None,
    ) -> str:
        if not images:
            return ""
        cfg = self._s.cap(capability)
        client = self._client(cfg)
        # Content parts theo vision API của OpenAI SDK: 1 text prompt + N ảnh
        # (tương đương ChatMessage TextContent + ImageContent của haystack).
        content: List[Dict[str, Any]] = [{"type": "text", "text": prompt}]
        for image in images:
            content.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{image.mime_type};base64,{image.base64_data}",
                        "detail": "high",
                    },
                }
            )
        messages = [{"role": "user", "content": content}]

        # OCR reasoning-OFF (qwen-vl reasoning-model: bật nghĩ -> 22s + truncate; tắt -> 9.7s + 100%
        # acc) do AI-ROUTER tự inject SERVER-SIDE cho capability 'ocr' CHỈ khi provider=OpenRouter
        # (xem router._prep_body). Provider KHÔNG gửi 'reasoning' -> tránh 400 khi ocr degrade OpenAI.
        async def _call():
            try:
                res = await client.chat.completions.create(
                    model=cfg.model,
                    messages=messages,
                    temperature=0.0,
                    max_tokens=max_tokens,
                )
            except Exception as exc:  # noqa: BLE001 - SDK-specific mapping stays in adapter
                raise self._map_error(exc, cfg.base_url) from exc
            # DEGRADED guard (xem embed): vision //hoá -> tải cao -> dễ 200-thiếu-choices.
            # Không guard -> res.choices[0] unmapped TypeError -> PERMANENT (OCR fail giết doc).
            if not getattr(res, "choices", None):
                raise TransientAIError(f"ocr/vision degraded: response thiếu 'choices' (model={cfg.model})")
            return res

        res = await retry_async(_call, max_retries=self._s.max_retries)
        return (res.choices[0].message.content or "").strip()

    async def probe_dimension(self) -> int:
        """Probe dimension thật từ embed model (notebook cell 14)."""
        vec = (await self.embed(["probe"]))[0]
        return len(vec)

    @staticmethod
    def _map_error(exc: Exception, base_url: str | None = None) -> Exception:
        try:
            from openai import (
                APIConnectionError,
                APITimeoutError,
                AuthenticationError,
                BadRequestError,
                ConflictError,
                InternalServerError,
                NotFoundError,
                PermissionDeniedError,
                RateLimitError,
                UnprocessableEntityError,
            )
        except ModuleNotFoundError:
            return exc

        # 401 từ GATEWAY NỘI BỘ ai-router lúc startup/recreate = TRANSIENT (token đúng nhưng
        # ai-router chưa load auth kịp) -> retry. Phân biệt với 401 provider thật (permanent).
        if isinstance(exc, AuthenticationError) and base_url and "ai-router" in base_url:
            return TransientAIError(f"ai-router gateway auth transient: {exc}")

        if isinstance(
            exc,
            (
                RateLimitError,
                APITimeoutError,
                APIConnectionError,
                InternalServerError,
                ConflictError,
            ),
        ):
            return TransientAIError(str(exc))
        if isinstance(
            exc,
            (
                AuthenticationError,
                BadRequestError,
                NotFoundError,
                PermissionDeniedError,
                UnprocessableEntityError,
            ),
        ):
            return PermanentAIError(str(exc))
        return exc
