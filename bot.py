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
    level=logging.DEBUG  # Changed to DEBUG for more info
)
logger = logging.getLogger(__name__)

# Configuration
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
BASE_API_URL = "https://andul-1.onrender.com/add_payment_method"

# Fixed credentials (from your URL)
EMAIL = "sogaged371@hudisk.com"
PASSWORD = "sogaged371@"

def debug_print(message: str):
    """Print debug messages."""
    print(f"[DEBUG] {message}")
    logger.debug(message)

def extract_card_details(text: str) -> Optional[dict]:
    """Extract card details from various formats."""
    debug_print(f"Extracting from text: {text}")
    
    # Remove command if present
    text = re.sub(r'^/bin\s+|^\.bin\s+', '', text).strip()
    
    # Pattern 1: Full card format - number|MM|YY|CVV
    pattern1 = r'^(\d{13,19})\|(\d{2})\|(\d{2,4})\|(\d{3,4})$'
    match1 = re.match(pattern1, text)
    if match1:
        debug_print(f"Matched full card pattern: {match1.groups()}")
        number = match1.group(1)
        month = match1.group(2)
        year = match1.group(3)
        cvv = match1.group(4)
        
        # Handle year format
        if len(year) == 2:
            year = "20" + year
        
        return {
            "number": number,
            "month": month,
            "year": year,
            "cvv": cvv,
            "type": "full"
        }
    
    # Pattern 2: Just numbers (BIN)
    pattern2 = r'^(\d{6,})$'
    match2 = re.match(pattern2, text)
    if match2:
        debug_print(f"Matched BIN pattern: {match2.group(1)}")
        return {
            "number": match2.group(1),
            "type": "bin"
        }
    
    debug_print("No pattern matched")
    return None

def call_payment_api(card_details: dict) -> dict:
    """Call your payment method API."""
    try:
        # For BIN only, create a complete card number
        if card_details["type"] == "bin":
            bin_number = card_details["number"]
            
            # Create a valid test card number
            # If BIN is less than 16 digits, pad with test digits
            if len(bin_number) < 16:
                # Pad with valid test digits (making sure the Luhn check might pass)
                # Common test pattern: BIN + 000000 + check digit
                padded = bin_number.ljust(15, '0')  # Pad to 15 digits
                # Simple Luhn check digit calculation
                digits = [int(d) for d in padded]
                for i in range(len(digits)-1, -1, -2):
                    digits[i] = digits[i] * 2
                    if digits[i] > 9:
                        digits[i] -= 9
                total = sum(digits)
                check_digit = (10 - (total % 10)) % 10
                card_number = padded + str(check_digit)
            else:
                card_number = bin_number
            
            # Use a valid future expiration
            month = "12"
            year = "2029"  # Far future
            cvv = "123"
            
        else:  # Full card
            card_number = card_details["number"]
            month = card_details["month"]
            year = card_details["year"]
            cvv = card_details["cvv"]
        
        # Format year as 2 digits for API (based on your example)
        year_2digit = year[-2:]
        
        # Create card string exactly as your API expects
        card_string = f"{card_number}|{month}|{year_2digit}|{cvv}"
        
        # Debug: Show what we're sending
        debug_print(f"Card string: {card_string}")
        debug_print(f"Card length: {len(card_number)}")
        
        # Don't URL encode - your example shows it's not encoded
        # Let's try both encoded and non-encoded to see what works
        test_strings = [
            card_string,  # Not encoded
            urllib.parse.quote(card_string, safe='')  # Encoded
        ]
        
        for i, card_str in enumerate(test_strings):
            api_url = f"{BASE_API_URL}/{EMAIL}/{PASSWORD}/{card_str}"
            debug_print(f"\n{'='*50}")
            debug_print(f"API Attempt {i+1}:")
            debug_print(f"URL: {api_url}")
            debug_print(f"Card String Type: {'Encoded' if i == 1 else 'Not Encoded'}")
            
            try:
                response = requests.get(api_url, timeout=10)
                debug_print(f"Status Code: {response.status_code}")
                debug_print(f"Response Headers: {dict(response.headers)}")
                debug_print(f"Response Text (first 500 chars): {response.text[:500]}")
                
                # Check if this attempt was successful
                if response.status_code == 200:
                    try:
                        result = response.json()
                        debug_print(f"JSON Response: {result}")
                    except:
                        result = {"raw_response": response.text}
                    
                    # Add which method worked
                    result["_debug_method"] = "encoded" if i == 1 else "not_encoded"
                    return result
                
            except Exception as e:
                debug_print(f"Attempt {i+1} failed: {str(e)}")
                continue
        
        # If neither worked
        return {
            "error": f"All attempts failed",
            "status_code": response.status_code if 'response' in locals() else "No response",
            "response_preview": response.text[:200] if 'response' in locals() else "No response"
        }
            
    except requests.exceptions.Timeout:
        debug_print("Request timed out")
        return {"error": "API request timed out (10s)"}
    except requests.exceptions.RequestException as e:
        debug_print(f"Request exception: {str(e)}")
        return {"error": f"Network error: {str(e)}"}
    except Exception as e:
        debug_print(f"Unexpected error: {str(e)}")
        return {"error": f"Unexpected error: {str(e)}"}

async def bin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /bin command."""
    if not context.args:
        await update.message.reply_text(
            "📋 *BIN Checker*\n\n"
            "*Usage:*\n"
            "• `/bin 428476` - Check BIN\n"
            "• `/bin 428476|04|29|736` - Check full card\n"
            "\n*Note:* This uses your API endpoint directly.",
            parse_mode='Markdown'
        )
        return
    
    user_input = " ".join(context.args)
    await process_check_request(update, user_input)

async def process_check_request(update: Update, user_input: str):
    """Process check request."""
    card_details = extract_card_details(user_input)
    
    if not card_details:
        await update.message.reply_text(
            "❌ *Invalid Format*\n\n"
            "Please use:\n"
            "• `/bin 123456` (BIN only)\n"
            "• `/bin 1234567890123456|MM|YY|CVV`\n\n"
            "Example: `/bin 428476`",
            parse_mode='Markdown'
        )
        return
    
    # Show what we're checking
    if card_details["type"] == "full":
        status_msg = f"🔍 *Checking Card:* `{card_details['number'][:6]}...{card_details['number'][-4:]}`"
    else:
        status_msg = f"🔍 *Checking BIN:* `{card_details['number'][:8]}`"
    
    status_msg += f"\n📧 *Account:* {EMAIL}"
    
    processing_msg = await update.message.reply_text(status_msg, parse_mode='Markdown')
    
    try:
        # Call API
        api_response = call_payment_api(card_details)
        
        debug_print(f"Final API Response: {api_response}")
        
        # Format response
        response_text = "📊 *API Response*\n"
        response_text += "─" * 30 + "\n"
        
        if "error" in api_response:
            response_text += f"❌ *Error:* {api_response['error']}\n"
            if "status_code" in api_response:
                response_text += f"📡 *Status Code:* {api_response['status_code']}\n"
            if "response_preview" in api_response:
                response_text += f"📝 *Response:* {api_response['response_preview']}\n"
        elif "raw_response" in api_response:
            response_text += f"📋 *Raw Response:*\n```\n{api_response['raw_response'][:500]}\n```\n"
        else:
            response_text += "✅ *Success!*\n"
            for key, value in api_response.items():
                if not key.startswith('_'):
                    response_text += f"• *{key}:* {value}\n"
        
        # Add debug info
        response_text += "─" * 30 + "\n"
        response_text += f"🔗 *Endpoint:* {BASE_API_URL}\n"
        if "_debug_method" in api_response:
            response_text += f"⚙️ *Method:* {api_response['_debug_method']}"
        
        await processing_msg.edit_text(response_text, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Error: {e}")
        await processing_msg.edit_text(
            f"❌ *Bot Error*\n\n"
            f"```\n{str(e)}\n```\n\n"
            f"Please check the console/logs for details.",
            parse_mode='Markdown'
        )

async def test_api(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Test the API directly."""
    debug_print("\n" + "="*50)
    debug_print("Starting API test...")
    
    # Test with your exact example from the URL
    test_card = "4283322115809145|04|29|736"
    api_url = f"{BASE_API_URL}/{EMAIL}/{PASSWORD}/{test_card}"
    
    debug_print(f"Test URL: {api_url}")
    
    try:
        response = requests.get(api_url, timeout=10)
        debug_print(f"Test Status: {response.status_code}")
        debug_print(f"Test Response: {response.text[:500]}")
        
        await update.message.reply_text(
            f"🧪 *API Test Results*\n\n"
            f"*URL:* `{api_url}`\n"
            f"*Status:* {response.status_code}\n"
            f"*Response:*\n```\n{response.text[:300]}\n```",
            parse_mode='Markdown'
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Test failed: {str(e)}")

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command."""
    await update.message.reply_text(
        "🤖 *BIN Checker Bot*\n\n"
        "*Commands:*\n"
        "• `/bin <number>` - Check BIN or card\n"
        "• `/test` - Test API connection\n"
        "• `/debug` - Show debug info\n\n"
        "*Examples:*\n"
        "`/bin 428476`\n"
        "`/bin 4283322115809145|04|29|736`\n\n"
        "*Current API:*\n"
        f"`{BASE_API_URL}`",
        parse_mode='Markdown'
    )

async def debug_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show debug information."""
    info = f"""
🔧 *Debug Information*

*API Configuration:*
• URL: `{BASE_API_URL}`
• Email: `{EMAIL}`
• Password: `{PASSWORD}`

*Bot Status:*
• Token Set: {'✅ Yes' if TELEGRAM_BOT_TOKEN != "YOUR_BOT_TOKEN_HERE" else '❌ No'}
• Log Level: DEBUG

*Test Commands:*
• `/test` - Test API directly
• `/bin 428476` - Test BIN
• `/bin 4111111111111111|12|25|123` - Test card

*Note:* Check console for detailed logs
    """
    await update.message.reply_text(info, parse_mode='Markdown')

def main():
    """Start the bot."""
    print("\n" + "="*50)
    print("🤖 BIN Checker Bot - Debug Mode")
    print("="*50)
    print(f"API URL: {BASE_API_URL}")
    print(f"Email: {EMAIL}")
    print(f"Password: {PASSWORD}")
    print(f"Token Set: {'YES' if TELEGRAM_BOT_TOKEN != 'YOUR_BOT_TOKEN_HERE' else 'NO (Please set TELEGRAM_BOT_TOKEN)'}")
    print("\nLogs will show detailed debug information")
    print("Use /test command to check API directly")
    print("="*50 + "\n")
    
    if TELEGRAM_BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("❌ ERROR: Please set TELEGRAM_BOT_TOKEN")
        print("1. Get token from @BotFather")
        print("2. Run: export TELEGRAM_BOT_TOKEN='your_token_here'")
        print("3. Or create .env file with TELEGRAM_BOT_TOKEN=your_token")
        return
    
    # Create application
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("bin", bin_command))
    application.add_handler(CommandHandler("test", test_api))
    application.add_handler(CommandHandler("debug", debug_info))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bin_command))
    
    # Start bot
    print("✅ Bot is starting...")
    print("📝 Send /test to check API connection")
    print("📝 Send /bin 428476 to test BIN check")
    print("="*50 + "\n")
    
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
