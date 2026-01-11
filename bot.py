
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
