import json


def format_sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def keep_alive() -> str:
    return ":keep-alive\n\n"
