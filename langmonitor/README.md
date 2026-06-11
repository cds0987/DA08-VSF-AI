# langmonitor

Tài liệu hướng dẫn cắm observability (tracing chi tiết từng step) vào các service.

| Thư mục | Backend | Trạng thái |
|---------|---------|-----------|
| [langfuse/](langfuse/) | Langfuse (self-host v2 trong VM) | Guide v1 — cắm full step query-service |
| [langsmith/](langsmith/) | LangSmith (cloud SaaS) | TODO — làm sau khi langfuse xong |

> Mục tiêu: full-step tracing cho **query-service** trước (guardrail → route → cache →
> tool → retrieval → agent iteration → LLM → output guardrail). Các service khác
> (rag-worker, mcp-service, hr-service) tính sau.
>
> Nguyên tắc bất di bất dịch: **tracing là best-effort** — mọi lỗi tracing đều bị nuốt,
> KHÔNG bao giờ được làm vỡ / treo / chậm đáng kể luồng query thật.
