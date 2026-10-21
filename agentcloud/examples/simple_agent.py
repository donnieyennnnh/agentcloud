# A tiny agent with no API key needed - good for testing the platform.
import datetime


def run(message: str) -> str:
    text = message.lower()
    if "time" in text:
        return f"Server time is {datetime.datetime.utcnow():%H:%M:%S} UTC. I'm running in the cloud!"
    if "hello" in text or "hi" in text:
        return "Hello! I'm a demo agent hosted on AgentCloud."
    return f"You said: {message!r}. Try asking me the time."
