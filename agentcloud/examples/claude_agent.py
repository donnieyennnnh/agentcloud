# A real AI agent powered by Claude.
# When deploying, add a secret:  ANTHROPIC_API_KEY = sk-ant-...
import os

import httpx

SYSTEM = "You are a friendly, concise assistant for a Singapore bubble tea shop. Keep replies under 80 words."


def run(message: str) -> str:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return "No ANTHROPIC_API_KEY set for this agent. Add it as a secret when deploying."
    resp = httpx.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
        json={
            "model": "claude-haiku-5-5",
            "max_tokens": 400,
            "system": SYSTEM,
            "messages": [{"role": "user", "content": message}],
        },
        timeout=50,
    )
    resp.raise_for_status()
    return resp.json()["content"][0]["text"]
