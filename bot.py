import os
import re
import requests
import logging
import urllib.parse
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from typing import Optional

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Configuration
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
BASE_API_URL = "https://andul-1.onrender.com/add_payment_method"

# Fixed email (from your URL) - you might want to make this configurable
EMAIL = "sogaged371@hudisk.com"
PASSWORD = "sogaged371@"  # From your URL

def extract_card_details(text: str) -> Optional[dict]:
    """Extract card details from various formats."""
    # Pattern for full card format: number|MM|YY|CVV
    full_card_pattern = r'(\d{13,19})\|(\d{2})\|(\d{2,4})\|(\d{3,4})'
    
    # Pattern for just BIN/number
    bin_pattern = r'(?:/bin|\.bin|\b)(\d{6,})'
    
    # Try full card format first
    full_match = re.search(full_card_pattern, text)
    if full_match:
        number = full_match.group(1)
        month = full_match.group(2)
        year = full_match.group(3)
        cvv = full_match.group(4)
        
        # Handle 2-digit year (convert to 4-digit)
        if len(year) == 2:
            year = "20" + year
        
        return {
            "number": number,
            "month": month,
            "year": year,
            "cvv": cvv,
            "type": "full"
        }
    
    # Try BIN/number only
    bin_match = re.search(bin_pattern, text)
    if bin_match:
        number = bin_match.group(1)
        return {
            "number": number,
            "type": "bin"
        }
    
    return None

def call_payment_api(card_details: dict) -> dict:
    """Call your payment method API."""
    try:
        # Build the URL based on card type
        if card_details["type"] == "full":
            # Format: number|MM|YY|CVV (YY is last 2 digits based on your example)
            card_string = f"{card_details['number']}|{card_details['month']}|{card_details['year'][-2:]}|{card_details['cvv']}"
            
            # URL encode the card string
            encoded_card = urllib.parse.quote(card_string, safe='')
            
            # Build the full URL
            api_url = f"{BASE_API_URL}/{EMAIL}/{PASSWORD}/{encoded_card}"
            
            logger.info(f"Calling API: {api_url}")
            
            # Make the request
            response = requests.get(api_url, timeout=15)
            
        else:  # bin only
            # For BIN only, we need to create a dummy card
            bin_number = card_details["number"]
            
            # Create a dummy full card number (pad with zeros if needed)
            dummy_card = bin_number.ljust(16, '0')[:16]  # Make it 16 digits
            
            # Use current month/year for dummy expiration
            from datetime import datetime
            now = datetime.now()
            month = now.strftime("%m")
            year = str(now.year + 1)[-2:]  # Next year, 2-digit format
            cvv = "123"  # Dummy CVV
            
            card_string = f"{dummy_card}|{month}|{year}|{cvv}"
            encoded_card = urllib.parse.quote(card_string, safe='')
            
            api_url = f"{BASE_API_URL}/{EMAIL}/{PASSWORD}/{encoded_card}"
            
            logger.info(f"Calling API with dummy card for BIN: {api_url}")
            response = requests.get(api_url, timeout=15)
        
        # Log response for debugging
        logger.info(f"API Response Status: {response.status_code}")
        logger.info(f"API Response Text: {response.text[:500]}")  # First 500 chars
        
        if response.status_code == 200:
            try:
                return response.json()
            except:
                # If not JSON, return text
                return {"raw_response": response.text, "status": "success"}
        else:
            return {
                "error": f"API returned status {response.status_code}",
                "details": response.text[:200] if response.text else "No response body"
            }
            
    except requests.exceptions.Timeout:
        return {"error": "API request timed out"}
    except requests.exceptions.RequestException as e:
        return {"error": f"Network error: {str(e)}"}
    except Exception as e:
        return {"error": f"Unexpected error: {str(e)}"}

def format_response(api_response: dict, card_details: dict) -> str:
    """Format API response into readable message."""
    # Check for errors first
    if "error" in api_response:
        error_msg = f"❌ *API Error:* {api_response['error']}"
        if "details" in api_response:
            error_msg += f"\n📝 *Details:* {api_response['details']}"
        return error_msg
    
    # Success response formatting
    message = "✅ *BIN/Card Check Results*\n"
    message += "─" * 40 + "\n"
    
    # Card info
    if card_details["type"] == "full":
        message += f"*Card Number:* `{card_details['number']}`\n"
        message += f"*Expiry:* {card_details['month']}/{card_details['year']}\n"
        message += f"*Type:* Full Card Check\n"
    else:
        message += f"*BIN Number:* `{card_details['number'][:8]}`\n"
        message += f"*Type:* BIN Check\n"
    
    message += "─" * 40 + "\n"
    
    # API Response
    message += "*API Response:*\n"
    
    if "raw_response" in api_response:
        # Handle raw text response
        raw_text = api_response['raw_response']
        
        # Try to parse common patterns
        if "success" in raw_text.lower():
            message += "✅ *Status:* Success\n"
        elif "fail" in raw_text.lower() or "error" in raw_text.lower():
            message += "❌ *Status:* Failed\n"
        elif "invalid" in raw_text.lower():
            message += "⚠️ *Status:* Invalid\n"
        
        # Show first 200 chars of response
        preview = raw_text[:200] + ("..." if len(raw_text) > 200 else "")
        message += f"📋 *Details:* {preview}\n"
        
    elif isinstance(api_response, dict):
        # Format JSON response
        for key, value in api_response.items():
            if key not in ["status", "raw_response"] and value:
                # Format key nicely
                formatted_key = key.replace("_", " ").title()
                message += f"• *{formatted_key}:* {value}\n"
    
    # Add footer
    message += "─" * 40
    message += f"\n🔗 *API Used:* {BASE_API_URL.split('/')[2]}"
    
    return message

async def bin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /bin command."""
    if not context.args:
        await update.message.reply_text(
            "📋 *BIN/Card Checker Bot*\n\n"
            "*Usage Examples:*\n"
            "• `/bin 428476` - Check BIN\n"
            "• `/bin 5220940191435288|04|29|736` - Full card check\n"
            "• `.bin 428476` - Alternative format\n"
            "• Just send: `428476|04|29|736`\n\n"
            "*Note:* For BIN checks, I'll use dummy expiry/CVV\n"
            "*Privacy:* Only first 6-8 digits are used for checking!",
            parse_mode='Markdown'
        )
        return
    
    user_input = " ".join(context.args)
    await process_check_request(update, user_input)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle messages containing BINs/cards."""
    user_input = update.message.text.strip()
    
    # Check if message contains card/BIN patterns
    if re.search(r'(?:\d{13,19}\|\d{2}\|\d{2,4}\|\d{3,4})|(?:(?:/bin|\.bin|\b)\d{6,})', user_input):
        await process_check_request(update, user_input)

async def process_check_request(update: Update, user_input: str):
    """Process card/BIN check request."""
    # Extract card details
    card_details = extract_card_details(user_input)
    
    if not card_details:
        await update.message.reply_text(
            "❌ *Invalid Format!*\n\n"
            "*Valid formats:*\n"
            "1. `/bin 123456` - 6+ digit BIN\n"
            "2. `/bin 1234567812345678|MM|YY|CVV` - Full card\n"
            "3. `.bin 123456` - Alternative command\n"
            "4. `1234567812345678|04|29|736` - Direct card\n"
            "5. `123456` - Just BIN number\n\n"
            "*Example:* `/bin 4283322115809145|04|29|736`",
            parse_mode='Markdown'
        )
        return
    
    # Send processing message
    if card_details["type"] == "full":
        processing_text = f"🔍 Checking card `{card_details['number'][:6]}...{card_details['number'][-4:]}`..."
    else:
        processing_text = f"🔍 Checking BIN `{card_details['number'][:8]}`..."
    
    processing_msg = await update.message.reply_text(processing_text)
    
    try:
        # Call API
        api_response = call_payment_api(card_details)
        
        # Format and send response
        response_text = format_response(api_response, card_details)
        await processing_msg.edit_text(response_text, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Error: {e}")
        await processing_msg.edit_text(
            f"❌ *Processing Error*\n\n"
            f"*Error:* {str(e)}\n\n"
            f"Please try again or check the format.",
            parse_mode='Markdown'
        )

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command."""
    welcome_text = """
🤖 *BIN & Card Checker Bot*

*Quick Start:*
Send me a BIN or card in any format:

*Formats Accepted:*
• `/bin 428476` - BIN check
• `/bin 5220940191435288|04|29|736` - Full card
• `.bin 123456` - Alternative
• `428476|04|29|736` - Direct card
• `123456` - Just BIN

*Examples:*
• `/bin 428476`
• `/bin 4283322115809145|04|29|736`
• Just send: `4111111111111111|12|25|123`

*Privacy:* I only use necessary digits for checking!
    """
    await update.message.reply_text(welcome_text, parse_mode='Markdown')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command."""
    help_text = """
📚 *Help Guide*

*Available Commands:*
• `/start` - Welcome message
• `/bin <number>` - Check BIN or card
• `/help` - This help message

*Card Format:*
`CARD_NUMBER|MM|YY|CVV`
Example: `4283322115809145|04|29|736`

*BIN Format:*
6-8 digit number
Example: `428476` or `/bin 428476`

*What happens with BIN only?*
For BIN checks, I'll:
1. Pad to 16 digits with zeros
2. Use dummy expiry (next year)
3. Use dummy CVV (123)
4. Check against API

*Security Note:*
• No card data stored
• Only API communication
• Use at your own risk
    """
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def test_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Test command to check API connection."""
    test_msg = await update.message.reply_text("🔄 Testing API connection...")
    
    # Test with a dummy BIN
    test_details = {"number": "428476", "type": "bin"}
    
    try:
        response = call_payment_api(test_details)
        
        if "error" not in response:
            await test_msg.edit_text(
                "✅ *API Connection Successful!*\n\n"
                f"*Status:* Connected\n"
                f"*URL:* {BASE_API_URL}\n"
                f"*Email:* {EMAIL}\n\n"
                "Bot is ready to use! Try `/bin 428476`",
                parse_mode='Markdown'
            )
        else:
            await test_msg.edit_text(
                f"❌ *API Connection Failed*\n\n"
                f"*Error:* {response.get('error', 'Unknown')}\n"
                f"*Details:* {response.get('details', 'None')}",
                parse_mode='Markdown'
            )
    except Exception as e:
        await test_msg.edit_text(f"❌ Exception: {str(e)}")

def main():
    """Start the bot."""
    # Check required environment variables
    if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        logger.error("Please set TELEGRAM_BOT_TOKEN environment variable!")
        print("\n❌ ERROR: Please set TELEGRAM_BOT_TOKEN")
        print("1. Get token from @BotFather")
        print("2. Create .env file or set environment variable")
        print("3. Run: export TELEGRAM_BOT_TOKEN='your_token_here'")
        return
    
    # Create application
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("bin", bin_command))
    application.add_handler(CommandHandler("test", test_command))  # Optional test command
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Start bot
    logger.info("Starting bot...")
    logger.info(f"Using API: {BASE_API_URL}")
    logger.info(f"Using email: {EMAIL}")
    print(f"\n🤖 Bot is starting...")
    print(f"🔗 API URL: {BASE_API_URL}")
    print(f"📧 Email: {EMAIL}")
    print(f"🔑 Password: {'*' * len(PASSWORD)}")
    print(f"✅ Ready to receive BIN/card checks!")
    
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
