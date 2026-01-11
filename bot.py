import os
import re
import asyncio
from contextlib import asynccontextmanager
from typing import List, Optional, Tuple

import httpx
from fastapi import FastAPI, Request, Response

# ====== ENV VARS (set these in Render) ======
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "").strip()
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

# ====== CARD PARSER ======
CARD_LINE_RE = re.compile(r"^\s*(\d{12,19})\|(\d{1,2})\|(\d{2,4})\|(\d{3,4})\s*$")


def luhn_ok(pan: str) -> bool:
    """Return True if PAN passes Luhn checksum."""
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
    """Show first 6 and last 4 digits; mask the rest."""
    if len(pan) < 10:
        return pan
    return f"{pan[:6]}{'*' * (len(pan) - 10)}{pan[-4:]}"


def normalize_year(y: str) -> int:
    yi = int(y)
    if len(y) == 2:
        yi += 2000
    return yi


def validate_card_fields(pan: str, mm: str, yy: str, cvv: str) -> Tuple[bool, List[str]]:
    """Validate basic format, expiry ranges, CVV length, and Luhn."""
    issues = []

    if not (12 <= len(pan) <= 19):
        issues.append("PAN length invalid")

    try:
        m = int(mm)
        if not (1 <= m <= 12):
            issues.append("Expiry month invalid")
    except ValueError:
        issues.append("Expiry month invalid")

    try:
        y = normalize_year(yy)
        if not (2000 <= y <= 2100):
            issues.append("Expiry year invalid")
    except ValueError:
        issues.append("Expiry year invalid")

    if len(cvv) not in (3, 4):
        issues.append("CVV length invalid")

    if not luhn_ok(pan):
        issues.append("Luhn check failed")

    return (len(issues) == 0), issues


def render_reply(pan: str, mm: str, yy: str, ok: bool, issues: List[str]) -> str:
    """Telegram reply text. CVV is NEVER echoed back."""
    masked = mask_pan(pan)
    year = normalize_year(yy)
    status = "✅ VALID (format/Luhn)" if ok else "❌ INVALID (format/Luhn)"
    reason = " / ".join(issues) if issues else "Looks syntactically valid."

    # Edit this text to match your preferred “image” style
    return (
        f"{status}\n"
        f"Card: {masked}\n"
        f"Exp: {int(mm):02d}/{year}\n"
        f"Result: {reason}"
    )


async def tg_send_message(chat_id: int, text: str, reply_to: Optional[int] = None):
    """Send a message to Telegram."""
    if not BOT_TOKEN:
        return

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


def parse_single(card_str: str) -> Optional[Tuple[str, str, str, str]]:
    m = CARD_LINE_RE.match(card_str)
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


# ====== LIFESPAN (startup) to set webhook ======
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: set webhook if env vars are set
    if BOT_TOKEN and WEBHOOK_SECRET and PUBLIC_BASE_URL:
        webhook_url = f"{PUBLIC_BASE_URL}/webhook/{WEBHOOK_SECRET}"
        async with httpx.AsyncClient(timeout=20) as client:
            try:
                await client.post(f"{TELEGRAM_API}/setWebhook", json={"url": webhook_url})
            except Exception:
                # Don't crash the app if Telegram is unreachable
                pass
    yield
    # Shutdown: nothing


app = FastAPI(lifespan=lifespan)


@app.get("/")
async def root():
    return {"ok": True, "service": "telegram-format-luhn-bot"}


@app.post("/webhook/{secret}")
async def telegram_webhook(secret: str, req: Request):
    # Basic secret check
    if secret != WEBHOOK_SECRET:
        return Response(status_code=403)

    update = await req.json()
    chat_id, message_id, text = extract_text(update)
    if not chat_id or not text:
        return Response(status_code=200)

    text = text.strip()

    # Help
    if text in ("/start", "/help"):
        await tg_send_message(
            chat_id,
            "Commands:\n"
            "//chk card|mm|yyyy|cvv  → format + Luhn\n"
            "/mass then paste 1–30 lines of card|mm|yyyy|cvv\n\n"
            "Example:\n"
            "//chk 5220940191435288|06|2027|404",
            reply_to=message_id,
        )
        return Response(status_code=200)

    # Single check
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
        reply = render_reply(pan, mm, yy, ok, issues)
        await tg_send_message(chat_id, reply, reply_to=message_id)
        return Response(status_code=200)

    # Mass check
    if text.startswith("/mass"):
        lines = text.splitlines()
        card_lines = lines[1:] if len(lines) > 1 else []
        cards = parse_mass_lines(card_lines)

        if not cards:
            await tg_send_message(
                chat_id,
                "Usage:\n/mass\n"
                "5220940191435288|06|2027|404\n"
                "4111111111111111|12|2027|123\n"
                "(1 to 30 lines)",
                reply_to=message_id,
            )
            return Response(status_code=200)

        await tg_send_message(chat_id, f"Processing {len(cards)} entries (format/Luhn only)...", reply_to=message_id)

        for pan, mm, yy, cvv in cards:
            ok, issues = validate_card_fields(pan, mm, yy, cvv)
            reply = render_reply(pan, mm, yy, ok, issues)
            await tg_send_message(chat_id, reply)
            await asyncio.sleep(0.25)  # pacing for Telegram rate limits

        return Response(status_code=200)

    return Response(status_code=200)
