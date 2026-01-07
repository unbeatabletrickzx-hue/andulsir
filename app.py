import os
import requests
from flask import Flask, request, jsonify
from telegram import Update
from telegram.ext import Updater, CommandHandler, CallbackContext, MessageHandler, Filters

# Replace with your actual Telegram bot token
TELEGRAM_BOT_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN_HERE"

# Replace with your API URL from the provided link
API_URL = "https://andul-1.onrender.com/add_payment_method/sogaged371@hudisk.com/sogaged371@/4283322115809145%7C04%7C29%7C736"

app = Flask(__name__)

# Telegram bot setup
updater = Updater(token=TELEGRAM_BOT_TOKEN, use_context=True)
dispatcher = updater.dispatcher

# Command to start the bot
def start(update: Update, context: CallbackContext):
    update.message.reply_text("Send me a credit card to check!")

# Handler for messages
def check_credit_card(update: Update, context: CallbackContext):
    message_text = update.message.text
    parts = message_text.split()
    
    # Ensure the message has the correct format
    if len(parts) < 2:
        update.message.reply_text("Invalid format. Use: /check <card_number> <exp_month> <exp_year> <cvv>")
        return
    
    # Extract card details
    card_number = parts[0]
    exp_month = parts[1]
    exp_year = parts[2]
    cvv = parts[3]
    
    # Format the data for the API
    data = {
        "card_number": card_number,
        "exp_month": exp_month,
        "exp_year": exp_year,
        "cvv": cvv
    }
    
    # Send request to your API
    try:
        response = requests.post(API_URL, data=data)
        result = response.json()
        
        # Format the response for Telegram
        if result.get("valid"):
            update.message.reply_text("✅ Valid credit card!")
        else:
            update.message.reply_text("❌ Invalid credit card.")
    
    except Exception as e:
        update.message.reply_text(f"⚠️ Error: {str(e)}")

# Register handlers
start_handler = CommandHandler('start', start)
check_handler = MessageHandler(Filters.text & (~Filters.command), check_credit_card)

dispatcher.add_handler(start_handler)
dispatcher.add_handler(check_handler)

# Run the bot
if __name__ == "__main__":
    updater.start_polling()
    print("Bot is running...")
    updater.idle()
