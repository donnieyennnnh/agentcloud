# AgentCloud — demo prototype

Paste an agent's code, click **Deploy**, and get:

- a **public URL** with a chat page anyone can open
- a **QR code** so people in the room can chat from their phones
- **live logs** that show each message arrive in real time
- an optional **Telegram bot** wired to the agent
- a **status bar** showing region (e.g. `sin` = Singapore) and uptime

```
agentcloud/
├── app.py              # the platform: API, agent runner, logs, Telegram
├── runner.py           # runs one agent call in a separate process
├── static/             # dashboard, public chat page, styles
├── examples/           # simple_agent.py (no key) and claude_agent.py (uses Claude)
├── Dockerfile, fly.toml
└── requirements.txt
```

An "agent" is any Python file with one function:

```python
def run(message: str) -> str:
    return "reply"
```

---

## Step 1 — Run it on your computer

```bash
cd agentcloud
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app:app --reload
```

Open http://localhost:8000, click **Deploy**, then **Open chat**. The status bar says `region local`, because it's still on your machine.

## Step 2 — Put it in the cloud (Fly.io, Singapore)

1. Install the Fly CLI: https://fly.io/docs/flyctl/install/ and run `fly auth signup` (or `fly auth login`). Fly may ask for a card.
2. In `fly.toml`, change `app = "agentcloud-demo-change-me"` to a unique name, e.g. `agentcloud-howard`.
3. Create the app and a small disk for the database, then deploy:

```bash
fly launch --no-deploy --copy-config      # say No if it offers to change settings
fly volumes create agentcloud_data --region sin --size 1
fly deploy
```

4. Your platform is now at `https://<your-app-name>.fly.dev`. The status bar now shows **region sin** and a machine ID instead of `local`. That's your proof it's in the cloud.

To redeploy after code changes, run `fly deploy` again. To watch server logs, run `fly logs`.

> Alternatives: Railway or Render also run this Dockerfile with no changes. Add a persistent disk mounted at `/data`.

## Step 3 — Add Telegram (optional, about 5 minutes)

1. In Telegram, message **@BotFather**, send `/newbot`, and follow the prompts. It gives you a token like `123456:ABC...`.
2. In your **cloud** dashboard (not localhost, because Telegram needs https), select your agent, open **Connect a Telegram bot**, paste the token, and click **Connect**.
3. Message your bot. Replies come from the agent, and the logs show `telegram` as the source.

## Step 4 — Deploy a real AI agent

Paste `examples/claude_agent.py` into the code box, and in **Secrets** add:

```
ANTHROPIC_API_KEY=sk-ant-...
```

Secrets are passed to the agent as environment variables, so any key works this way (OpenAI, etc.).

---

## Demo script (about 2 minutes)

1. Open the cloud dashboard and point at the status bar: "Running in Singapore."
2. Paste agent code and click **Deploy**. A URL and QR code appear.
3. Ask the audience to scan the QR code **on mobile data** and send a message.
4. Their messages pop up in **Live logs** with timing.
5. Close your laptop lid. Their phones keep getting replies.
6. Bonus: message the Telegram bot from your own phone.

---

## What this prototype skips (fine for a demo, not for real customers)

| Gap | Why it matters | Fix later |
|---|---|---|
| Agents run as plain processes on one server | One customer's code could read others' files or secrets | Run each agent in a sandbox: Modal, E2B, Fly Machines per agent, or Firecracker/gVisor |
| No login | Anyone with the dashboard URL can deploy or delete | Add auth (Supabase Auth, Clerk) |
| Secrets stored unencrypted in SQLite | A leaked database leaks API keys | Encrypt at rest or use a secrets manager |
| No limits on cost or rate | A looping agent can burn someone's API credits | Per-agent rate limits and spend caps |
| SQLite on one machine | Can't scale past one server | Postgres |
| Only `pip` packages already installed are available | Users can't add dependencies | Build one container image per agent |

**Don't let strangers deploy code on this version.** Use it to demo with code you control.
