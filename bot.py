import os
import re
import asyncio
from contextlib import asynccontextmanager
from typing import List, Optional, Tuple

import httpx
from fastapi import FastAPI, Request, Response

# ================= ENV =================
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

# ================= CARD UTILS =================
CARD_RE = re.compile(r"^\s*(\d{12,19})\|(\d{1,2})\|(\d{2,4})\|(\d{3,4})\s*$")


def luhn_ok(card: str) -> bool:
    total = 0
    rev = card[::-1]
    for i, ch in enumerate(rev):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def mask(card: str) -> str:
    return card[:6] + "*" * (len(card) - 10) + card[-4:]


def normalize_year(y: str) -> int:
    y = int(y)
    return y + 2000 if y < 100 else y


def check_card(card, mm, yy, cvv):
    errors = []

    if not luhn_ok(card):
        errors.append("Luhn failed")

    if not (1 <= int(mm) <= 12):
        errors.append("Month invalid")

    if not (2000 <= normalize_year(yy) <= 2100):
        errors.append("Year invalid")

    if len(cvv) not in (3, 4):
        errors.append("CVV invalid")

    return errors


async def tg_send(chat_id, text, reply_to=None):
    async with httpx.AsyncClient() as client:
        payload = {"chat_id": chat_id, "text": text}
        if reply_to:
            payload["reply_to_message_id"] = reply_to
        await client.post(f"{TELEGRAM_API}/sendMessage", json=payload)


# ================= FASTAPI =================
@asynccontextmanager
async def lifespan(app: FastAPI):
    if BOT_TOKEN and PUBLIC_BASE_URL:
        webhook = f"{PUBLIC_BASE_URL}/webhook"
        async with httpx.AsyncClient() as client:
            try:
                await client.post(
                    f"{TELEGRAM_API}/setWebhook",
                    json={"url": webhook},
                )
            except Exception:
                pass
    yield


app = FastAPI(lifespan=lifespan)


@app.get("/")
async def root():
    return {"status": "ok"}


@app.post("/webhook")
async def webhook(req: Request):
    data = await req.json()
    msg = data.get("message")
    if not msg:
        return Response(status_code=200)

    chat_id = msg["chat"]["id"]
    msg_id = msg["message_id"]
    text = msg.get("text", "").strip()

    if text in ("/start", "/help"):
        await tg_send(
            chat_id,
            "Commands:\n"
            "//chk card|mm|yyyy|cvv\n"
            "/mass (new line) card|mm|yyyy|cvv (1–30 lines)",
            msg_id,
        )
        return Response(status_code=200)

    if text.startswith("//chk") or text.startswith("/chk"):
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            await tg_send(chat_id, "Wrong format", msg_id)
            return Response(status_code=200)

        m = CARD_RE.match(parts[1])
        if not m:
            await tg_send(chat_id, "Invalid format", msg_id)
            return Response(status_code=200)

        card, mm, yy, cvv = m.groups()
        errors = check_card(card, mm, yy, cvv)

        status = "✅ VALID" if not errors else "❌ INVALID"
        result = (
            f"{status}\n"
            f"Card: {mask(card)}\n"
            f"Exp: {mm}/{normalize_year(yy)}\n"
            f"Result: {' / '.join(errors) if errors else 'Format OK'}"
        )

        await tg_send(chat_id, result, msg_id)
        return Response(status_code=200)

    if text.startswith("/mass"):
        lines = text.splitlines()[1:]
        cards = []
        for ln in lines:
            m = CARD_RE.match(ln)
            if m:
                cards.append(m.groups())
            if len(cards) >= 30:
                break

        await tg_send(chat_id, f"Checking {len(cards)} cards...")

        for card, mm, yy, cvv in cards:
            errors = check_card(card, mm, yy, cvv)
            status = "✅ VALID" if not errors else "❌ INVALID"
            msg = (
                f"{status}\n"
                f"Card: {mask(card)}\n"
                f"Exp: {mm}/{normalize_year(yy)}\n"
                f"Result: {' / '.join(errors) if errors else 'Format OK'}"
            )
            await tg_send(chat_id, msg)
            await asyncio.sleep(0.3)

    return Response(status_code=200)
