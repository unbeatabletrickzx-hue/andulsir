import os
import re
import asyncio
from typing import List, Optional, Tuple

import httpx
from fastapi import FastAPI, Request, Response

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "").strip()  # simple shared secret path segment
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")  # e.g. https://your-app.onrender.com

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

app = FastAPI()

CARD_LINE_RE = re.compile(
    r"^\s*(\d{12,19})\|(\d{1,2})\|(\d{2,4})\|(\d{3,4})\s*$"
)

def luhn_ok(pan: str) -> bool:
    # Luhn checksum
    total = 0
    rev = pan[::-1]
    for i, ch in enumerate(rev):
        d = ord(ch) - 48
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0

def mask_pan(pan: str) -> str:
    # show first 6 and last 4, mask the rest
    if len(pan) < 10:
        return pan
    return f"{pan[:6]}{'*' * (len(pan) - 10)}{pan[-4:]}"

def normalize_year(y: str) -> int:
    yi = int(y)
    if len(y) == 2:
        yi += 2000
    return yi

def validate_card_fields(pan: str, mm: str, yy: str, cvv: str) -> Tuple[bool, List[str]]:
    issues = []

    # PAN basic length
    if not (12 <= len(pan) <= 19):
        issues.append("PAN length invalid")

    # Month range
    m = int(mm)
    if not (1 <= m <= 12):
        issues.append("Expiry month invalid")

    # Year range (simple sanity)
    y = normalize_year(yy)
    if not (2000 <= y <= 2100):
        issues.append("Expiry year invalid")

    # CVV length
    if len(cvv) not in (3, 4):
        issues.append("CVV length invalid")

    # Luhn
    if not luhn_ok(pan):
        issues.append("Luhn check failed")

    return (len(issues) == 0), issues

def render_reply(pan: str, mm: str, yy: str, cvv: str, ok: bool, issues: List[str]) -> str:
    # You can tweak this to match your “image” style.
    masked = mask_pan(pan)
    year = normalize_year(yy)

    status = "✅ VALID (format)" if ok else "❌ INVALID (format)"
    reason = " / ".join(issues) if issues else "Looks syntactically valid."

    # NOTE: We do NOT print CVV back.
    return (
        f"{status}\n"
        f"Card: {masked}\n"
        f"Exp: {int(mm):02d}/{year}\n"
        f"Result: {reason}"
    )

async def tg_send_message(chat_id: int, text: str, reply_to: Optional[int] = None):
    payload = {"chat_id": chat_id, "text": text}
    if reply_to is not None:
        payload["reply_to_message_id"] = reply_to

    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(f"{TELEGRAM_API}/sendMessage", json=payload)
        r.raise_for_status()

def extract_text(update: dict) -> Tuple[Optional[int], Optional[int], str]:
    msg = update.get("message") or update.get("edited_message")
    if not msg:
        return None, None, ""
    chat_id = msg.get("chat", {}).get("id")
    message_id = msg.get("message_id")
    text = msg.get("text") or ""
    return chat_id, message_id, text

def parse_single(text: str) -> Optional[Tuple[str, str, str, str]]:
    m = CARD_LINE_RE.match(text)
    if not m:
        return None
    return m.group(1), m.group(2), m.group(3), m.group(4)

def parse_mass_lines(lines: List[str]) -> List[Tuple[str, str, str, str]]:
    out = []
    for ln in lines:
        m = CARD_LINE_RE.match(ln)
        if m:
            out.append((m.group(1), m.group(2), m.group(3), m.group(4)))
        if len(out) >= 30:
            break
    return out

@app.get("/")
async def root():
    return {"ok": True, "service": "telegram-format-checker"}

@app.post(f"/webhook/{WEBHOOK_SECRET}")
async def telegram_webhook(req: Request):
    update = await req.json()
    chat_id, message_id, text = extract_text(update)
    if not chat_id or not text:
        return Response(status_code=200)

    text = text.strip()

    # --- Single check ---
    # Accept: //chk <pipe>  OR /chk <pipe>
    if text.startswith("//chk") or text.startswith("/chk"):
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            await tg_send_message(chat_id, "Usage:\n//chk 5220940191435288|06|2027|404", reply_to=message_id)
            return Response(status_code=200)

        card_str = parts[1].strip()
        parsed = parse_single(card_str)
        if not parsed:
            await tg_send_message(chat_id, "Invalid format. Use:\ncard|mm|yyyy|cvv", reply_to=message_id)
            return Response(status_code=200)

        pan, mm, yy, cvv = parsed
        ok, issues = validate_card_fields(pan, mm, yy, cvv)
        reply = render_reply(pan, mm, yy, cvv, ok, issues)
        await tg_send_message(chat_id, reply, reply_to=message_id)
        return Response(status_code=200)

    # --- Mass check ---
    # Format:
    # /mass
    # 4111111111111111|12|2027|123
    # 5555....|...
    if text.startswith("/mass"):
        # everything after first line are card lines
        lines = text.splitlines()
        card_lines = lines[1:] if len(lines) > 1 else []
        cards = parse_mass_lines(card_lines)

        if not cards:
            await tg_send_message(
                chat_id,
                "Usage:\n/mass\n5220940191435288|06|2027|404\n4111111111111111|12|2027|123\n(1 to 30 lines)",
                reply_to=message_id,
            )
            return Response(status_code=200)

        await tg_send_message(chat_id, f"Processing {len(cards)} entries (format/Luhn only)...", reply_to=message_id)

        # Send one-by-one (Telegram rate limits exist; we pace slightly)
        for pan, mm, yy, cvv in cards:
            ok, issues = validate_card_fields(pan, mm, yy, cvv)
            reply = render_reply(pan, mm, yy, cvv, ok, issues)
            await tg_send_message(chat_id, reply)
            await asyncio.sleep(0.25)  # gentle pacing

        return Response(status_code=200)

    # Help
    if text in ("/start", "/help"):
        await tg_send_message(
            chat_id,
            "Commands:\n"
            "//chk card|mm|yyyy|cvv  → format + Luhn\n"
            "/mass (newline) card|mm|yyyy|cvv (1–30 lines)\n\n"
            "Example:\n"
            "//chk 5220940191435288|06|2027|404",
            reply_to=message_id
        )

    return Response(status_code=200)

@app.on_event("startup")
async def on_startup():
    # Optionally auto-set webhook if PUBLIC_BASE_URL is provided.
    if not (BOT_TOKEN and WEBHOOK_SECRET and PUBLIC_BASE_URL):
        return
    webhook_url = f"{PUBLIC_BASE_URL}/webhook/{WEBHOOK_SECRET}"
    async with httpx.AsyncClient(timeout=20) as client:
        await client.post(f"{TELEGRAM_API}/setWebhook", json={"url": webhook_url})
