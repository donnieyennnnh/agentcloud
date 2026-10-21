"""AgentCloud: a demo platform for deploying AI agents to the cloud.

Paste agent code -> click Deploy -> get a public URL, QR code, live logs,
and an optional Telegram bot.

Run locally:   uvicorn app:app --reload
"""
import asyncio
import json
import os
import secrets
import sqlite3
import sys
import time
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

BASE_DIR = Path(__file__).parent
DATA_DIR = Path(os.environ.get("DATA_DIR", BASE_DIR / "data"))
AGENTS_DIR = DATA_DIR / "agents"
DB_PATH = DATA_DIR / "agentcloud.db"
RUN_TIMEOUT = int(os.environ.get("RUN_TIMEOUT", "60"))   # seconds per agent call
STARTED_AT = time.time()
REGION = os.environ.get("FLY_REGION") or os.environ.get("REGION") or "local"

AGENTS_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="AgentCloud")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


# ---------------------------------------------------------------- database
def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


with db() as conn:
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS agents (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        env_json TEXT NOT NULL DEFAULT '{}',
        telegram_token TEXT,
        created_at REAL NOT NULL
    );
    CREATE TABLE IF NOT EXISTS logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        agent_id TEXT NOT NULL,
        ts REAL NOT NULL,
        source TEXT NOT NULL,      -- web | telegram | api | system
        kind TEXT NOT NULL,        -- request | reply | error | info
        text TEXT NOT NULL,
        duration_ms INTEGER
    );
    CREATE INDEX IF NOT EXISTS logs_agent ON logs(agent_id, id);
    """)


def log(agent_id: str, source: str, kind: str, text: str, duration_ms: int | None = None) -> None:
    with db() as conn:
        conn.execute(
            "INSERT INTO logs (agent_id, ts, source, kind, text, duration_ms) VALUES (?,?,?,?,?,?)",
            (agent_id, time.time(), source, kind, text[:4000], duration_ms),
        )


def get_agent(agent_id: str) -> sqlite3.Row:
    with db() as conn:
        row = conn.execute("SELECT * FROM agents WHERE id=?", (agent_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Agent not found")
    return row


def public_base(request: Request) -> str:
    """The URL people outside use to reach this server."""
    return os.environ.get("PUBLIC_URL", str(request.base_url)).rstrip("/")


# ---------------------------------------------------------------- running agents
async def run_agent(agent_id: str, message: str, source: str) -> str:
    """Run the agent's run(message) in a separate process with a timeout."""
    agent = get_agent(agent_id)
    agent_file = AGENTS_DIR / f"{agent_id}.py"
    env = {"PATH": os.environ.get("PATH", ""), **json.loads(agent["env_json"])}

    log(agent_id, source, "request", message)
    start = time.perf_counter()
    proc = await asyncio.create_subprocess_exec(
        sys.executable, str(BASE_DIR / "runner.py"), str(agent_file),
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE, env=env, cwd=str(AGENTS_DIR),
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(message.encode()), RUN_TIMEOUT)
    except asyncio.TimeoutError:
        proc.kill()
        log(agent_id, source, "error", f"Timed out after {RUN_TIMEOUT}s")
        return "Sorry, the agent took too long to respond."
    ms = int((time.perf_counter() - start) * 1000)

    try:
        result = json.loads(out.decode().strip().splitlines()[-1])
    except Exception:
        log(agent_id, source, "error", (err.decode() or out.decode() or "No output")[-1500:], ms)
        return "Sorry, the agent crashed."
    if not result["ok"]:
        log(agent_id, source, "error", result["error"], ms)
        return f"Agent error: {result['error']}"
    log(agent_id, source, "reply", result["reply"], ms)
    return result["reply"]


# ---------------------------------------------------------------- API
class DeployIn(BaseModel):
    name: str
    code: str
    env: dict[str, str] = {}


class ChatIn(BaseModel):
    message: str


class TelegramIn(BaseModel):
    token: str


@app.post("/api/agents")
async def deploy(body: DeployIn, request: Request):
    if "def run" not in body.code:
        raise HTTPException(400, "Code must define run(message) -> str")
    agent_id = secrets.token_urlsafe(6).replace("_", "x").replace("-", "y").lower()
    (AGENTS_DIR / f"{agent_id}.py").write_text(body.code)
    with db() as conn:
        conn.execute(
            "INSERT INTO agents (id, name, env_json, created_at) VALUES (?,?,?,?)",
            (agent_id, body.name.strip() or "My agent", json.dumps(body.env), time.time()),
        )
    log(agent_id, "system", "info", f"Deployed to region '{REGION}'")
    return {"id": agent_id, "url": f"{public_base(request)}/a/{agent_id}"}


@app.get("/api/agents")
async def list_agents(request: Request):
    with db() as conn:
        rows = conn.execute("""
            SELECT a.id, a.name, a.created_at, a.telegram_token IS NOT NULL AS telegram,
                   (SELECT COUNT(*) FROM logs l WHERE l.agent_id=a.id AND l.kind='request') AS runs
            FROM agents a ORDER BY a.created_at DESC""").fetchall()
    base = public_base(request)
    return [{**dict(r), "telegram": bool(r["telegram"]), "url": f"{base}/a/{r['id']}"} for r in rows]


@app.delete("/api/agents/{agent_id}")
async def delete_agent(agent_id: str):
    get_agent(agent_id)
    with db() as conn:
        conn.execute("DELETE FROM agents WHERE id=?", (agent_id,))
        conn.execute("DELETE FROM logs WHERE agent_id=?", (agent_id,))
    (AGENTS_DIR / f"{agent_id}.py").unlink(missing_ok=True)
    return {"ok": True}


@app.post("/a/{agent_id}/chat")
async def chat(agent_id: str, body: ChatIn):
    reply = await run_agent(agent_id, body.message, "web")
    return {"reply": reply}


@app.get("/api/agents/{agent_id}/logs/stream")
async def stream_logs(agent_id: str, request: Request):
    """Server-Sent Events: pushes new log lines to the dashboard as they happen."""
    get_agent(agent_id)

    async def events():
        last_id = 0
        while not await request.is_disconnected():
            with db() as conn:
                rows = conn.execute(
                    "SELECT * FROM logs WHERE agent_id=? AND id>? ORDER BY id LIMIT 200",
                    (agent_id, last_id)).fetchall()
            for r in rows:
                last_id = r["id"]
                yield f"data: {json.dumps(dict(r))}\n\n"
            yield ": keepalive\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/agents/{agent_id}/qr.svg")
async def qr_code(agent_id: str, request: Request):
    """QR code of the agent's public URL, made on the server (no outside scripts)."""
    import io
    import qrcode
    import qrcode.image.svg

    get_agent(agent_id)
    img = qrcode.make(f"{public_base(request)}/a/{agent_id}",
                      image_factory=qrcode.image.svg.SvgPathImage, box_size=8, border=2)
    buf = io.BytesIO()
    img.save(buf)
    return Response(buf.getvalue(), media_type="image/svg+xml")


@app.get("/api/status")
async def status():
    return {"status": "running", "region": REGION, "uptime_s": int(time.time() - STARTED_AT),
            "host": os.environ.get("FLY_MACHINE_ID") or os.uname().nodename}


# ---------------------------------------------------------------- Telegram
@app.post("/api/agents/{agent_id}/telegram")
async def connect_telegram(agent_id: str, body: TelegramIn, request: Request):
    get_agent(agent_id)
    base = public_base(request)
    if not base.startswith("https://"):
        raise HTTPException(400, "Telegram needs a public https URL. Deploy to the cloud first "
                                 "(or set PUBLIC_URL to an https tunnel such as ngrok).")
    async with httpx.AsyncClient(timeout=15) as client:
        me = (await client.get(f"https://api.telegram.org/bot{body.token}/getMe")).json()
        if not me.get("ok"):
            raise HTTPException(400, "Telegram rejected that bot token.")
        hook = await client.post(f"https://api.telegram.org/bot{body.token}/setWebhook",
                                 json={"url": f"{base}/telegram/{agent_id}"})
        if not hook.json().get("ok"):
            raise HTTPException(400, f"Could not set webhook: {hook.text}")
    with db() as conn:
        conn.execute("UPDATE agents SET telegram_token=? WHERE id=?", (body.token, agent_id))
    username = me["result"]["username"]
    log(agent_id, "system", "info", f"Connected Telegram bot @{username}")
    return {"ok": True, "bot": username, "link": f"https://t.me/{username}"}


@app.post("/telegram/{agent_id}")
async def telegram_webhook(agent_id: str, request: Request):
    agent = get_agent(agent_id)
    update = await request.json()
    msg = update.get("message") or {}
    text, chat_id = msg.get("text"), (msg.get("chat") or {}).get("id")
    if not text or not chat_id or not agent["telegram_token"]:
        return {"ok": True}

    async def respond():
        reply = await run_agent(agent_id, text, "telegram")
        async with httpx.AsyncClient(timeout=15) as client:
            await client.post(f"https://api.telegram.org/bot{agent['telegram_token']}/sendMessage",
                              json={"chat_id": chat_id, "text": reply[:4000]})

    asyncio.create_task(respond())  # answer Telegram fast, reply in the background
    return {"ok": True}


# ---------------------------------------------------------------- pages
@app.get("/", response_class=HTMLResponse)
async def dashboard():
    return FileResponse(BASE_DIR / "static" / "dashboard.html")


@app.get("/a/{agent_id}", response_class=HTMLResponse)
async def chat_page(agent_id: str):
    agent = get_agent(agent_id)
    html = (BASE_DIR / "static" / "chat.html").read_text()
    name = agent["name"].replace("<", "&lt;").replace(">", "&gt;")
    return html.replace("{{AGENT_NAME}}", name).replace("{{AGENT_ID}}", agent_id)
