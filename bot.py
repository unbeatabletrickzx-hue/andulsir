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
executor = concurrent.futures.ThreadPoolExecutor(max_workers=15)

# Store user states for conversation
user_states = {}

def validate_card(card_input):
    """Validate and format card details"""
    try:
        card_input = card_input.strip()
        
        if '|' not in card_input:
            return None, "Invalid format"
        
        parts = card_input.split('|')
        if len(parts) != 4:
            return None, "Invalid format"
        
        card, month, year, cvv = [p.strip() for p in parts]
        
        # Clean card number
        card = re.sub(r'\D', '', card)
        
        # Validate card number
        if not (13 <= len(card) <= 19):
            return None, "Invalid card length"
        
        # Validate month
        if not month.isdigit() or not (1 <= int(month) <= 12):
            return None, "Invalid month"
        
        # Convert year to 2-digit
        if len(year) == 4:
            year = year[2:]
        elif len(year) != 2:
            return None, "Invalid year"
        
        # Validate CVV
        if not cvv.isdigit() or len(cvv) not in [3, 4]:
            return None, "Invalid CVV"
        
        # Final format
        formatted = f"{card}|{month}|{year}|{cvv}"
        return formatted, None
        
    except Exception as e:
        logger.error(f"Validation error: {e}")
        return None, "Validation error"

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
            return card_input, f"API Error: Status {response.status_code}"
            
    except requests.exceptions.Timeout:
        return card_input, "Request timeout"
    except Exception as e:
        logger.error(f"Request error: {e}")
        return card_input, "Connection error"

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
        status = "DECLINED"
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
                    status = "APPROVED"
                    status_msg = "Card approved"
                elif 'DECLINED' in status_value.upper():
                    status = "DECLINED"
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
- STATUS : ERROR
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

def process_mass_check(chat_id, cards_text):
    """Process mass check in background"""
    try:
        lines = cards_text.split('\n')
        cards = [line.strip() for line in lines if line.strip()]
        
        if len(cards) > 30:
            send_telegram_message(chat_id, f"Limiting to first 30 cards (you sent {len(cards)})")
            cards = cards[:30]
        
        if not cards:
            send_telegram_message(chat_id, "No valid cards found.")
            return
        
        total_cards = len(cards)
        
        # Send initial status
        send_telegram_message(chat_id, f"*ULTRA-FAST MASS CHECK*\nProcessing {total_cards} cards in parallel...\nEstimated: 1-2 minutes", "Markdown")
        
        # Submit all tasks
        futures = []
        for card in cards:
            future = executor.submit(check_card, card)
            futures.append(future)
        
        # Collect and send results as they complete
        completed = 0
        successful = 0
        failed = 0
        
        for i, future in enumerate(concurrent.futures.as_completed(futures), 1):
            try:
                card_input, result = future.result(timeout=30)
                
                if result.startswith("- CARD :"):
                    send_telegram_message(chat_id, f"Card {i}:\n{result}\n{'='*40}")
                    successful += 1
                else:
                    send_telegram_message(chat_id, f"Card {i}: {result}")
                    failed += 1
                
                completed += 1
                
                # Send progress update every 5 cards
                if i % 5 == 0 or i == total_cards:
                    send_telegram_message(chat_id, f"Progress: {i}/{total_cards} cards\nSuccessful: {successful}\nFailed: {failed}")
                    
            except Exception as e:
                logger.error(f"Error processing card {i}: {e}")
                send_telegram_message(chat_id, f"Card {i}: Failed to check")
                failed += 1
        
        # Final summary
        send_telegram_message(chat_id, f"*MASS CHECK COMPLETE!*\n\nResults:\nSuccessful: {successful}\nFailed: {failed}\nTotal: {total_cards}\n\nAll cards checked in parallel!", "Markdown")
        
    except Exception as e:
        logger.error(f"Mass check error: {e}")
        send_telegram_message(chat_id, f"Error during mass check: {str(e)[:100]}")

def process_command(update):
    """Process Telegram command"""
    try:
        message = update.get('message', {})
        chat_id = message.get('chat', {}).get('id')
        text = message.get('text', '').strip()
        
        if not chat_id or not text:
            return
        
        # Check if user is in mass check mode
        if chat_id in user_states and user_states[chat_id] == 'waiting_for_cards':
            if text.lower() == '/cancel':
                send_telegram_message(chat_id, "Mass check cancelled.")
                del user_states[chat_id]
                return
            
            # Process mass check
            send_telegram_action(chat_id, "typing")
            del user_states[chat_id]
            
            # Start mass check in background
            threading.Thread(target=process_mass_check, args=(chat_id, text)).start()
            return
        
        # Handle /start command
        if text == '/start':
            welcome_text = """CC CHECKER BOT

Commands:
/chk - Check single card
/mass - Check multiple cards FAST (1-30)
/help - Show detailed help

Format: CARD|MM|YY|CVV
Example: /chk 5220940191435288|06|27|404

Features:
- Parallel processing (15 cards at once)
- 30 cards in 1-2 minutes
- Real-time progress updates"""
            
            send_telegram_message(chat_id, welcome_text, "Markdown")
        
        # Handle /help command
        elif text == '/help':
            help_text = """CC CHECKER BOT HELP

Commands:
/start - Show commands
/help - Show this help
/chk - Check single card
/mass - Check multiple cards FAST (1-30)

Card Format:
CARD_NUMBER|MM|YYYY|CVV

Examples:/chk 5220940191435288|06|2027|404
/mass
4232231106894283|06|26|241
4116670005727071|02|26|426

Mass Check Instructions:
1. Type /mass
2. Send your cards (one per line)
3. Bot will check all cards simultaneously
4. Results sent one by one

Note: Year can be 2 or 4 digits (26 or 2026)"""
            
            send_telegram_message(chat_id, help_text, "Markdown")
        
        # Handle /chk command
        elif text.startswith('/chk '):
            card_input = text[5:].strip()
            if not card_input:
                send_telegram_message(chat_id, "Usage: /chk CARD|MM|YYYY|CVV\n\nExample: /chk 5220940191435288|06|2027|404")
                return
            
            send_telegram_action(chat_id, "typing")
            _, result = check_card(card_input)
            send_telegram_message(chat_id, result)
        
        # Handle /mass command
        elif text == '/mass':
            user_states[chat_id] = 'waiting_for_cards'
            mass_text = """ULTRA-FAST MASS CHECK

Send up to 30 cards (one per line):
4232231106894283|06|26|241
4116670005727071|02|26|426
5303471055207621|01|27|456
                    
Type /cancel to stop.

Speed: 30 cards in 1-2 minutes"""
            
            send_telegram_message(chat_id, mass_text, "Markdown")
        
        # Handle single card input (without command)
        elif '|' in text and text.count('|') == 3 and any(c.isdigit() for c in text):
            send_telegram_action(chat_id, "typing")
            _, result = check_card(text)
            send_telegram_message(chat_id, result)
        
        # Handle unknown command
        elif text.startswith('/'):
            send_telegram_message(chat_id, "Unknown command. Use /start to see available commands.")
            
    except Exception as e:
        logger.error(f"Error processing command: {e}")

@app.route('/webhook', methods=['POST'])
def webhook():
    """Telegram webhook endpoint"""
    try:
        update = request.json
        
        # Log the update (optional, for debugging)
        logger.info(f"Received update")
        
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
        # Get the webhook URL from Render environment or use request host
        webhook_url = f"https://andulsir-1.onrender.com/webhook"
        
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/setWebhook"
        payload = {'url': webhook_url}
        response = requests.post(url, json=payload)
        
        if response.status_code == 200:
            result = response.json()
            if result.get('ok'):
                return f"Webhook set successfully!<br>URL: {webhook_url}"
            else:
                return f"Failed to set webhook: {result.get('description')}"
        else:
            return f"HTTP Error: {response.status_code}"
    except Exception as e:
        return f"Error: {str(e)}"

@app.route('/deletewebhook', methods=['GET'])
def delete_webhook():
    """Delete Telegram webhook"""
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/deleteWebhook"
        response = requests.get(url)
        return f"Webhook deleted: {response.text}"
    except Exception as e:
        return f"Error: {str(e)}"

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'service': 'cc-checker-bot',
        'version': '1.0'
    }), 200

@app.route('/')
def home():
    """Home page"""
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>CC Checker Bot</title>
        <style>
            body {
                font-family: Arial, sans-serif;
                max-width: 800px;
                margin: 0 auto;
                padding: 20px;
                background-color: #f5f5f5;
            }
            .container {
                background: white;
                padding: 30px;
                border-radius: 10px;
                box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            }
            h1 {
                color: #333;
            }
            .bot-info {
                background: #e3f2fd;
                padding: 15px;
                border-radius: 5px;
                margin: 20px 0;
            }
            .btn {
                display: inline-block;
                background: #4285f4;
                color: white;
                padding: 10px 20px;
                text-decoration: none;
                border-radius: 5px;
                margin: 5px;
            }
            .btn:hover {
                background: #3367d6;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>CC Checker Bot</h1>
            <p>Telegram bot for fast credit card checking</p>
            
            <div class="bot-info">
                <h3>Bot Status: Running</h3>
                <p>Webhook URL: https://andulsir-1.onrender.com/webhook</p>
                <p>Features:</p>
                <ul>
                    <li>Single card check</li>
                    <li>Mass check (up to 30 cards)</li>
                    <li>Parallel processing (15 cards at once)</li>
                    <li>Fast results (30 cards in 1-2 minutes)</li>
                </ul>
            </div>
            
            <h3>Quick Actions:</h3>
            <a href="/setwebhook" class="btn">Set Webhook</a>
            <a href="/deletewebhook" class="btn">Delete Webhook</a>
            <a href="/health" class="btn">Health Check</a>
            
            <h3>How to use:</h3>
            <ol>
                <li>Open Telegram and find your bot</li>
                <li>Send /start to see commands</li>
                <li>Use /chk to check single card</li>
                <li>Use /mass to check multiple cards</li>
            </ol>
            
            <p>Format: CARD|MM|YY|CVV</p>
            <p>Example: 5220940191435288|06|27|404</p>
        </div>
    </body>
    </html>
    """

if __name__ == '__main__':
    port = int(os.getenv('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=False)
