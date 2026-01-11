import os
import asyncio
from typing import List, Optional

import httpx
from fastapi import FastAPI, Request, Response

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
API_BASE = os.getenv("API_BASE", "").rstrip("/")  # e.g. https://andulsir-1.onrender.com

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

app = FastAPI()

# ---------- Telegram helpers ----------
async def tg_send(chat_id: int, text: str, reply_to: Optional[int] = None):
    payload = {"chat_id": chat_id, "text": text}
    if reply_to is not None:
        payload["reply_to_message_id"] = reply_to
    async with httpx.AsyncClient(timeout=20) as client:
        await client.post(f"{TELEGRAM_API}/sendMessage", json=payload)

def extract(update: dict):
    msg = update.get("message") or update.get("edited_message")
    if not msg:
        return None, None, ""
    return msg["chat"]["id"], msg["message_id"], (msg.get("text") or "").strip()

# ---------- Format API response ----------
def format_api_result(item: str, data: dict) -> str:
    """
    Adjust this to match your "image" format.
    This assumes your API returns JSON like:
      { "status": "approved/declined", "message": "...", "details": {...} }
    """
    status = str(data.get("status", "unknown")).upper()
    message = data.get("message", "") or data.get("result", "") or "—"
    code = data.get("code", "")  # optional
    extra = data.get("details", {}) if isinstance(data.get("details"), dict) else {}

    lines = [
        f"Status: {status}",
        f"Item: {item}",
        f"Message: {message}",
    ]
    if code:
        lines.append(f"Code: {code}")

    # show a few safe extra fields if present
    for k in ("brand", "last4", "exp_month", "exp_year", "country"):
        if k in extra:
            lines.append(f"{k}: {extra[k]}")

    return "\n".join(lines)

# ---------- Call your API ----------
async def call_your_api(client: httpx.AsyncClient, item: str) -> dict:
    """
    Example endpoint: {API_BASE}/check/{item}
    Change this path to match your actual API.
    """
    url = f"{API_BASE}/check/{item}"
    r = await client.get(url)
    r.raise_for_status()
    return r.json()

@app.on_event("startup")
async def startup_set_webhook():
    if not (BOT_TOKEN and PUBLIC_BASE_URL):
        return
    webhook_url = f"{PUBLIC_BASE_URL}/webhook"
    async with httpx.AsyncClient(timeout=20) as client:
        await client.post(f"{TELEGRAM_API}/setWebhook", json={"url": webhook_url})

@app.get("/")
async def root():
    return {"ok": True}

@app.post("/webhook")
async def webhook(req: Request):
    update = await req.json()
    chat_id, message_id, text = extract(update)
    if not chat_id or not text:
        return Response(status_code=200)

    if text in ("/start", "/help"):
        await tg_send(
            chat_id,
            "Commands:\n"
            "/chk <token_or_id>\n"
            "/mass ثم ضع 1-30 سطر من tokens/ids\n\n"
            "Example:\n"
            "/chk pm_12345\n"
            "/mass\npm_1\npm_2",
            reply_to=message_id,
        )
        return Response(status_code=200)

    # Single
    if text.startswith("/chk"):
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            await tg_send(chat_id, "Usage: /chk <token_or_id>", reply_to=message_id)
            return Response(status_code=200)

        item = parts[1].strip()
        async with httpx.AsyncClient(timeout=30) as client:
            try:
                data = await call_your_api(client, item)
                out = format_api_result(item, data)
            except Exception as e:
                out = f"Status: ERROR\nItem: {item}\nMessage: {type(e).__name__}"
        await tg_send(chat_id, out, reply_to=message_id)
        return Response(status_code=200)

    # Mass (parallel with limit)
    if text.startswith("/mass"):
        lines = [ln.strip() for ln in text.splitlines()[1:] if ln.strip()]
        items = lines[:30]
        if not items:
            await tg_send(chat_id, "Usage:\n/mass\nid1\nid2\n... (up to 30)", reply_to=message_id)
            return Response(status_code=200)

        await tg_send(chat_id, f"Processing {len(items)} items...", reply_to=message_id)

        sem = asyncio.Semaphore(8)  # concurrency limit (tune 4-10)

        async def worker(client: httpx.AsyncClient, item: str):
            async with sem:
                try:
                    data = await call_your_api(client, item)
                    return item, format_api_result(item, data)
                except Exception as e:
                    return item, f"Status: ERROR\nItem: {item}\nMessage: {type(e).__name__}"

        async with httpx.AsyncClient(timeout=30) as client:
            results = await asyncio.gather(*(worker(client, it) for it in items))

        # Send one-by-one
        for _, msg in results:
            await tg_send(chat_id, msg)
            await asyncio.sleep(0.1)

        return Response(status_code=200)

    return Response(status_code=200)
