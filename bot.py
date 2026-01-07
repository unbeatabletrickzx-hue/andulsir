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

# Configuration - CORRECTED URL
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
BASE_API_URL = "https://andul-1.onrender.com/add_payment_method"  # With underscore

# Fixed credentials
EMAIL = "sogaged371@hudisk.com"
PASSWORD = "sogaged371@"

def extract_card_details(text: str) -> Optional[dict]:
    """Extract card details from various formats."""
    # Remove command if present
    text = re.sub(r'^/bin\s+|^\.bin\s+', '', text).strip()
    
    print(f"DEBUG: Extracting from: '{text}'")
    
    # Try full card format first: number|MM|YYYY|CVV or number|MM|YY|CVV
    # Your example: 5328544152353125|12|2028|923
    full_pattern = r'^(\d{13,19})\|(\d{1,2})\|(\d{2,4})\|(\d{3,4})$'
    match = re.match(full_pattern, text)
    
    if match:
        print(f"DEBUG: Matched full card pattern")
        number = match.group(1)
        month = match.group(2).zfill(2)  # Ensure 2-digit month
        year = match.group(3)
        cvv = match.group(4)
        
        # Handle 2-digit year
        if len(year) == 2:
            year = "20" + year
        
        print(f"DEBUG: Extracted - Number: {number}, Month: {month}, Year: {year}, CVV: {cvv}")
        
        return {
            "number": number,
            "month": month,
            "year": year,
            "cvv": cvv,
            "type": "full"
        }
    
    # Try just BIN/number
    bin_pattern = r'^(\d{6,})$'
    match = re.match(bin_pattern, text)
    if match:
        print(f"DEBUG: Matched BIN pattern: {match.group(1)}")
        return {
            "number": match.group(1),
            "type": "bin"
        }
    
    print(f"DEBUG: No pattern matched")
    return None

def call_payment_api(card_details: dict) -> dict:
    """Call your payment method API."""
    print(f"\n{'='*60}")
    print("DEBUG: Starting API call...")
    print(f"DEBUG: Card type: {card_details['type']}")
    
    try:
        # Prepare card details
        if card_details["type"] == "bin":
            print(f"DEBUG: Processing BIN: {card_details['number']}")
            
            # For BIN check, create a full test card
            bin_num = card_details['number']
            
            # If BIN is shorter than 16, pad it
            if len(bin_num) < 16:
                # Create a valid test card number (using common test patterns)
                # Start with the BIN
                base = bin_num
                # Add filler digits
                while len(base) < 15:
                    base += '0'
                
                # Calculate Luhn check digit
                digits = [int(d) for d in base]
                # Double every other digit starting from right
                for i in range(len(digits)-1, -1, -2):
                    digits[i] = digits[i] * 2
                    if digits[i] > 9:
                        digits[i] -= 9
                
                total = sum(digits)
                check_digit = (10 - (total % 10)) % 10
                
                card_number = base + str(check_digit)
            else:
                card_number = bin_num
            
            month = "12"
            year = "2028"
            cvv = "123"
            
        else:  # Full card
            print(f"DEBUG: Processing full card")
            card_number = card_details["number"]
            month = card_details["month"]
            year = card_details["year"]
            cvv = card_details["cvv"]
        
        # Format year as 2 digits (based on your original example)
        year_2digit = year[-2:]
        
        # Create the card string
        card_string = f"{card_number}|{month}|{year_2digit}|{cvv}"
        print(f"DEBUG: Card string: {card_string}")
        
        # URL encode the pipe characters
        # Pipe character (|) becomes %7C when URL encoded
        encoded_card = urllib.parse.quote(card_string, safe='')
        print(f"DEBUG: Encoded card: {encoded_card}")
        
        # Build the API URL
        api_url = f"{BASE_API_URL}/{EMAIL}/{PASSWORD}/{encoded_card}"
        print(f"DEBUG: API URL: {api_url}")
        print(f"DEBUG: URL length: {len(api_url)} characters")
        
        # Make the request with longer timeout
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'en-US,en;q=0.9',
        }
        
        print(f"DEBUG: Sending GET request...")
        response = requests.get(
            api_url, 
            headers=headers,
            timeout=15,
            verify=True
        )
        
        print(f"DEBUG: Response status: {response.status_code}")
        print(f"DEBUG: Response headers: {dict(response.headers)}")
        print(f"DEBUG: Response content (first 1000 chars):")
        print(response.text[:1000])
        
        if response.status_code == 200:
            try:
                # Try to parse as JSON
                result = response.json()
                print(f"DEBUG: Parsed JSON response")
                return result
            except:
                # Return as text
                print(f"DEBUG: Response is not JSON, returning as text")
                return {
                    "success": True,
                    "raw_response": response.text,
                    "status_code": response.status_code
                }
        else:
            print(f"DEBUG: API returned error status: {response.status_code}")
            return {
                "error": f"API returned status {response.status_code}",
                "status_code": response.status_code,
                "response_text": response.text[:500] if response.text else "No response body"
            }
            
    except requests.exceptions.Timeout:
        print("DEBUG: Request timed out after 15 seconds")
        return {"error": "Request timeout - API server might be slow or down"}
    
    except requests.exceptions.ConnectionError:
        print("DEBUG: Connection error")
        return {"error": "Connection failed - Check if API URL is accessible"}
    
    except requests.exceptions.RequestException as e:
        print(f"DEBUG: Request exception: {str(e)}")
        return {"error": f"Network error: {str(e)}"}
    
    except Exception as e:
        print(f"DEBUG: Unexpected error: {str(e)}")
        return {"error": f"Unexpected error: {str(e)}"}

async def bin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /bin command."""
    if not context.args:
        await update.message.reply_text(
            "🔍 *BIN Checker*\n\n"
            "Send a BIN or card to check:\n"
            "• `/bin 5328544152353125|12|2028|923`\n"
            "• `/bin 428476` (BIN only)\n"
            "• `.bin 4111111111111111|12|25|123`\n\n"
            f"*API:* `{BASE_API_URL}`",
            parse_mode='Markdown'
        )
        return
    
    user_input = " ".join(context.args)
    await process_check_request(update, user_input)

async def process_check_request(update: Update, user_input: str):
    """Process check request."""
    print(f"\n{'='*60}")
    print(f"Received command: {user_input}")
    
    card_details = extract_card_details(user_input)
    
    if not card_details:
        await update.message.reply_text(
            "❌ *Invalid Format*\n\n"
            "Please use one of these formats:\n"
            "1. `/bin 5328544152353125|12|2028|923`\n"
            "2. `/bin 428476|04|29|736`\n"
            "3. `/bin 428476` (BIN only)\n\n"
            "*Note:* Year can be 2 or 4 digits",
            parse_mode='Markdown'
        )
        return
    
    # Show processing message
    if card_details["type"] == "full":
        card_preview = f"{card_details['number'][:6]}...{card_details['number'][-4:]}"
        processing_text = f"🔍 Checking card: `{card_preview}`\n⏳ Calling API..."
    else:
        bin_num = card_details["number"][:8]
        processing_text = f"🔍 Checking BIN: `{bin_num}`\n⏳ Creating test card and calling API..."
    
    processing_msg = await update.message.reply_text(processing_text, parse_mode='Markdown')
    
    try:
        # Call the API
        print(f"DEBUG: Calling API with details: {card_details}")
        api_response = call_payment_api(card_details)
        print(f"DEBUG: API response received: {api_response}")
        
        # Format the response
        response_text = "📊 *API Response*\n"
        response_text += "─" * 40 + "\n"
        
        if "error" in api_response:
            response_text += f"❌ *Error:* {api_response['error']}\n"
            
            if "status_code" in api_response:
                response_text += f"📡 *Status Code:* {api_response['status_code']}\n"
            
            if "response_text" in api_response:
                response_text += f"📝 *Response:* {api_response['response_text']}\n"
            elif "raw_response" in api_response:
                response_text += f"📋 *Raw:* {api_response['raw_response'][:300]}\n"
        
        elif "success" in api_response and api_response["success"]:
            response_text += "✅ *Success!*\n"
            
            if "raw_response" in api_response:
                # Try to format the raw response
                raw = api_response["raw_response"]
                if len(raw) < 500:
                    response_text += f"📋 *Response:* {raw}\n"
                else:
                    response_text += f"📋 *Response (truncated):*\n```\n{raw[:500]}...\n```\n"
            else:
                # Show all fields from JSON response
                for key, value in api_response.items():
                    if key not in ["success", "_debug"]:
                        formatted_key = key.replace("_", " ").title()
                        response_text += f"• *{formatted_key}:* {value}\n"
        
        else:
            # Unknown response format
            response_text += "⚠️ *Unknown Response Format*\n"
            for key, value in api_response.items():
                if not key.startswith('_'):
                    formatted_key = key.replace("_", " ").title()
                    response_text += f"• *{formatted_key}:* {value}\n"
        
        # Add footer
        response_text += "─" * 40 + "\n"
        response_text += f"🔗 *Endpoint:* `{BASE_API_URL.split('/')[2]}`"
        
        await processing_msg.edit_text(response_text, parse_mode='Markdown')
        
    except Exception as e:
        print(f"ERROR in process_check_request: {str(e)}")
        import traceback
        traceback.print_exc()
        
        await processing_msg.edit_text(
            f"❌ *Processing Error*\n\n"
            f"```\n{str(e)}\n```\n\n"
            f"Check console for details.",
            parse_mode='Markdown'
        )

async def direct_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Direct test of the exact API URL from your example."""
    test_card = "4283322115809145|04|29|736"
    encoded_card = urllib.parse.quote(test_card, safe='')
    test_url = f"{BASE_API_URL}/{EMAIL}/{PASSWORD}/{encoded_card}"
    
    print(f"\n{'='*60}")
    print("DIRECT TEST of example URL:")
    print(f"Test URL: {test_url}")
    
    try:
        response = requests.get(test_url, timeout=10)
        
        result = f"🧪 *Direct API Test*\n\n"
        result += f"*URL:* `{test_url[:100]}...`\n"
        result += f"*Status:* {response.status_code}\n"
        result += f"*Response:*\n```\n{response.text[:300]}\n```"
        
        await update.message.reply_text(result, parse_mode='Markdown')
        
    except Exception as e:
        await update.message.reply_text(f"❌ Test failed: {str(e)}")

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command."""
    await update.message.reply_text(
        "🤖 *BIN Checker Bot*\n\n"
        "I can check BINs and cards using your API.\n\n"
        "*Commands:*\n"
        "• `/bin <number>` - Check BIN or card\n"
        "• `/test` - Test API with example\n"
        "• `/check <BIN>` - Alternative command\n\n"
        "*Examples:*\n"
        "`/bin 5328544152353125|12|2028|923`\n"
        "`/bin 428476`\n"
        "`/check 4111111111111111|12|25|123`\n\n"
        f"*API:* {BASE_API_URL}",
        parse_mode='Markdown'
    )

async def check_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Alternative /check command."""
    if not context.args:
        await update.message.reply_text("Usage: /check <BIN or card>")
        return
    
    user_input = " ".join(context.args)
    await process_check_request(update, user_input)

def main():
    """Start the bot."""
    print("\n" + "="*60)
    print("🤖 BIN Checker Bot")
    print("="*60)
    print(f"API URL: {BASE_API_URL}")
    print(f"Email: {EMAIL}")
    print(f"Password: {PASSWORD}")
    print("\nBot is starting...")
    print("="*60)
    
    if TELEGRAM_BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("\n❌ ERROR: TELEGRAM_BOT_TOKEN not set!")
        print("1. Get a token from @BotFather")
        print("2. Set it as environment variable:")
        print("   export TELEGRAM_BOT_TOKEN='your_token_here'")
        print("3. Or create a .env file")
        return
    
    # Create application
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("bin", bin_command))
    application.add_handler(CommandHandler("check", check_command))
    application.add_handler(CommandHandler("test", direct_test))
    
    # Also handle messages that start with .bin
    application.add_handler(MessageHandler(
        filters.TEXT & filters.Regex(r'^\.bin\s+'), 
        bin_command
    ))
    
    print("\n✅ Bot started successfully!")
    print("📝 Available commands:")
    print("   /start - Show help")
    print("   /bin <number> - Check BIN/card")
    print("   /test - Test API connection")
    print("   .bin <number> - Alternative format")
    print("="*60 + "\n")
    
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
