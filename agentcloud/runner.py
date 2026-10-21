"""Runs one agent call in an isolated child process.

Usage: python runner.py <agent_file.py>
Reads the user's message from stdin, prints a JSON result to stdout.
The agent file must define:  def run(message: str) -> str
"""
import importlib.util
import json
import sys
import traceback


def main() -> None:
    agent_path = sys.argv[1]
    message = sys.stdin.read()
    try:
        spec = importlib.util.spec_from_file_location("user_agent", agent_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        if not hasattr(module, "run"):
            raise RuntimeError("Your agent must define a function: run(message) -> str")
        reply = module.run(message)
        print(json.dumps({"ok": True, "reply": str(reply)}))
    except Exception as exc:  # report errors back to the platform
        print(json.dumps({
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "trace": traceback.format_exc(limit=3),
        }))


if __name__ == "__main__":
    main()
