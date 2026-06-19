"""Probe o3-mini (hoặc reasoning model bất kỳ) THẲNG qua OpenAI API — KHÔNG qua ai-router.

Mục đích: khảo sát thực tế reasoning model nhận argument nào, từ chối cái nào, và
response/stream/usage trả về shape ra sao — làm nền cho refactor "mỗi node 1 tập model".

Chạy:
    export OPENAI_API_KEY=sk-...        # PowerShell: $env:OPENAI_API_KEY="sk-..."
    python eval/probe_o3mini.py                 # mặc định model = o3-mini
    python eval/probe_o3mini.py o4-mini         # đổi model đích
    python eval/probe_o3mini.py gpt-4o-mini     # so sánh với model thường

Không ghi file, chỉ in ra stdout. Mỗi probe tự bắt lỗi -> in PASS/FAIL + lý do,
để lộ chính xác argument nào model chấp nhận.
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any

try:
    from openai import OpenAI
except ImportError:
    sys.exit("Thiếu openai SDK. Cài: pip install openai")

MODEL = sys.argv[1] if len(sys.argv) > 1 else "o3-mini"

api_key = os.environ.get("OPENAI_API_KEY")
if not api_key:
    sys.exit("Thiếu OPENAI_API_KEY trong env.")

# Máy có proxy TLS-inspection: certifi KHÔNG có root CA của proxy -> httpx báo
# 'CERTIFICATE_VERIFY_FAILED' dù curl (dùng Windows store) tới được. Dùng `truststore`
# để Python verify bằng CHÍNH Windows trust store (giữ verify BẬT, không bỏ TLS).
try:
    import truststore
    truststore.inject_into_ssl()
    print("✓ truststore: verify TLS qua Windows trust store.")
except ImportError:
    print("ℹ️  Chưa có truststore (pip install truststore) — dùng certifi mặc định.")

client = OpenAI(api_key=api_key)

PROMPT = "Tính 17 * 23 rồi giải thích ngắn gọn. Trả lời tiếng Việt."


def banner(title: str) -> None:
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def dump_usage(usage: Any) -> None:
    """In usage + tách reasoning_tokens nếu có (reasoning model)."""
    if usage is None:
        print("  usage: <none>")
        return
    try:
        u = usage.model_dump() if hasattr(usage, "model_dump") else dict(usage)
    except Exception:
        u = {"prompt_tokens": getattr(usage, "prompt_tokens", "?"),
             "completion_tokens": getattr(usage, "completion_tokens", "?")}
    print("  usage:", json.dumps(u, ensure_ascii=False))


def try_call(label: str, **params: Any) -> None:
    """Gọi chat.completions non-stream với params cho trước, in kết quả/lỗi."""
    print(f"\n--- {label} ---")
    print("  params gửi:", json.dumps(
        {k: v for k, v in params.items() if k != "messages"}, ensure_ascii=False))
    try:
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": PROMPT}],
            **params,
        )
    except Exception as exc:  # noqa: BLE001 — probe: muốn thấy mọi lỗi
        print(f"  ❌ FAIL [{type(exc).__name__}]: {str(exc)[:300]}")
        return
    msg = resp.choices[0].message
    print("  ✅ OK")
    print("  content:", (msg.content or "<None>")[:120])
    # reasoning_content chỉ có ở 1 số provider (deepseek). OpenAI o-series KHÔNG trả text này.
    rc = getattr(msg, "reasoning_content", None)
    if rc:
        print("  reasoning_content:", str(rc)[:120])
    print("  finish_reason:", resp.choices[0].finish_reason)
    dump_usage(resp.usage)


def probe_non_stream() -> None:
    banner(f"NON-STREAM probes — model={MODEL}")

    # 1) Baseline tối thiểu — chỉ max_completion_tokens (o-series yêu cầu cái này, KHÔNG max_tokens)
    try_call("1. baseline (max_completion_tokens=2000)", max_completion_tokens=2000)

    # 2) max_tokens cũ — kỳ vọng FAIL với o-series (đã deprecated cho reasoning)
    try_call("2. max_tokens=2000 (param cũ)", max_tokens=2000)

    # 3) temperature=0 — kỳ vọng FAIL với o-series (chỉ chấp nhận default=1)
    try_call("3. temperature=0", temperature=0, max_completion_tokens=2000)

    # 4) temperature=1 (default) — kỳ vọng OK
    try_call("4. temperature=1", temperature=1, max_completion_tokens=2000)

    # 5) reasoning_effort — param đặc thù reasoning model
    for eff in ("low", "medium", "high"):
        try_call(f"5. reasoning_effort={eff}", reasoning_effort=eff,
                 max_completion_tokens=4000)

    # 6) top_p / presence_penalty — kỳ vọng FAIL với o-series
    try_call("6. top_p=0.9", top_p=0.9, max_completion_tokens=2000)


def probe_roles() -> None:
    banner("ROLE probes — system vs developer")
    for role in ("system", "developer"):
        print(f"\n--- role={role} ---")
        try:
            resp = client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": role, "content": "Bạn là trợ lý súc tích."},
                    {"role": "user", "content": PROMPT},
                ],
                max_completion_tokens=2000,
            )
            print("  ✅ OK ->", (resp.choices[0].message.content or "")[:80])
        except Exception as exc:  # noqa: BLE001
            print(f"  ❌ FAIL [{type(exc).__name__}]: {str(exc)[:200]}")


def probe_tools() -> None:
    banner("TOOL-CALLING probe (think_node cần cái này)")
    tools = [{
        "type": "function",
        "function": {
            "name": "rag_search",
            "description": "Tìm tài liệu nội bộ.",
            "parameters": {
                "type": "object",
                "properties": {"top_k": {"type": "integer"}},
            },
        },
    }]
    try:
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": "Chính sách nghỉ phép năm là gì?"}],
            tools=tools,
            tool_choice="auto",
            max_completion_tokens=4000,
        )
        msg = resp.choices[0].message
        tc = msg.tool_calls or []
        print("  ✅ OK — gọi được tools")
        print("  tool_calls:", [(t.function.name, t.function.arguments) for t in tc] or "<không gọi>")
        print("  content:", (msg.content or "<None>")[:80])
    except Exception as exc:  # noqa: BLE001
        print(f"  ❌ FAIL [{type(exc).__name__}]: {str(exc)[:250]}")


def probe_stream() -> None:
    banner("STREAM probe — đo event/delta shape + độ trễ reasoning")
    try:
        stream = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": PROMPT}],
            max_completion_tokens=4000,
            stream=True,
            stream_options={"include_usage": True},
        )
    except Exception as exc:  # noqa: BLE001
        print(f"  ❌ FAIL mở stream [{type(exc).__name__}]: {str(exc)[:250]}")
        return

    n_content = 0
    n_reasoning = 0
    first_keys: set[str] = set()
    final_usage = None
    sample_content = []
    for chunk in stream:
        if getattr(chunk, "usage", None):
            final_usage = chunk.usage
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        if delta is None:
            continue
        # Ghi lại các field xuất hiện trong delta (content? reasoning_content? reasoning?)
        try:
            first_keys |= {k for k, v in delta.model_dump().items() if v is not None}
        except Exception:
            pass
        if getattr(delta, "content", None):
            n_content += 1
            if len(sample_content) < 8:
                sample_content.append(delta.content)
        if getattr(delta, "reasoning_content", None) or getattr(delta, "reasoning", None):
            n_reasoning += 1

    print(f"  số delta CÓ content      : {n_content}")
    print(f"  số delta CÓ reasoning    : {n_reasoning}")
    print(f"  các field thấy trong delta: {sorted(first_keys)}")
    print(f"  mẫu content đầu          : {''.join(sample_content)[:100]!r}")
    dump_usage(final_usage)
    if n_content <= 1:
        print("  ⚠️  content KHÔNG stream theo token (trả 1 cục) — ảnh hưởng stream-per-phase!")


def main() -> None:
    print(f"Probing model: {MODEL}")
    print(f"OpenAI key: ...{api_key[-4:]}")
    probe_non_stream()
    probe_roles()
    probe_tools()
    probe_stream()
    banner("XONG — đọc PASS/FAIL ở trên để biết o3-mini chấp nhận argument nào")


if __name__ == "__main__":
    main()
