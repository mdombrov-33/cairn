import json


def sse(type_: str, data: dict) -> str:
    return f"event: {type_}\ndata: {json.dumps(data)}\n\n"
