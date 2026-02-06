import sqlite3
import telebot
import time
import threading
import os
import logging
from telebot import types

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('manager.log')
    ]
)

API_TOKEN = 'xxx'
CHAT_ID = 123456789
DB_PATH = os.path.expanduser('~/nostrnews/published.db')

bot = telebot.TeleBot(API_TOKEN)

def get_db_connection():
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error as e:
        logging.error(f"Fatal Error in DB connection: {e}")
        raise

@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    """Buttons select manager"""
    try:
        action, guid = call.data.split("|")
        conn = get_db_connection()
        cursor = conn.cursor()

        if action == "approve":
            cursor.execute("UPDATE published SET status = 'reviewed' WHERE guid = ?", (guid,))
            new_text = "✅ **APPROVED**\nThe article will publish on Nostr on next execution."
            logging.info(f"Approved Article (GUID: {guid})")
        else:
            cursor.execute("UPDATE published SET status = 'skipped' WHERE guid = ?", (guid,))
            new_text = "❌ **REJECTED**\nThe article will not be published."
            logging.info(f"ALERT: Article Rejected (GUID: {guid})")

        conn.commit()
        conn.close()
        
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        bot.send_message(call.message.chat.id, f"{new_text}\n\nOriginal: {call.message.text[:50]}...", parse_mode='Markdown')
    
    except Exception as e:
        logging.error(f"Error in callback handler: {e}")

def check_for_new_articles():
    """Check and Send periodicaly records in 'draft' status, that aren't still sended to Telegram"""
    logging.info(f"Monitoring DB thread started: {DB_PATH}")
    while True:
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            # Getting the articles that still not sended on Telegram
            cursor.execute("SELECT * FROM published WHERE status = 'draft' AND tg_sent = 0")
            rows = cursor.fetchall()

            if rows:
                logging.info(f"Article found {len(rows)} ready to proces.")
            
            for row in rows:
                msg = (
                    f"🔔 *NEW ARTICLE FOUND*\n\n"
                    f"📰 *RSS Source:* {row['category']}\n"
                    f"📂 *Category:* {row['category']}\n"
                    f"📅 *Date:* {row['published_at']}\n"
                    f"📌 *Title:* {row['title']}\n"
                    f"✍️ *Author:* {row['author'] or 'N/A'}\n"
                    f"🏷️ *Tags:* `{row['tags'] or 'N/A'}`\n\n"
                    f"🔗 [Read Article]({row['link']})\n"
                    f"🚦 *Status:* {row['status']}"
                )
                
                markup = types.InlineKeyboardMarkup()
                markup.add(
                    types.InlineKeyboardButton("✅ Approve", callback_data=f"approve|{row['guid']}"),
                    types.InlineKeyboardButton("🗑️ Reject", callback_data=f"reject|{row['guid']}")
                )

                bot.send_message(CHAT_ID, msg, parse_mode='Markdown', reply_markup=markup)
                # Sign like sended
                cursor.execute("UPDATE published SET tg_sent = 1 WHERE guid = ?", (row['guid'],))
                conn.commit()
                logging.info(f"Sended to Telegram: {row['title'][:40]}...")

            conn.close()
        except Exception as e:
            logging.error(f"Error in monitoring cycle: {e}")
        
        time.sleep(60)

if __name__ == "__main__":
    if not os.path.exists(DB_PATH):
        logging.critical(f"ALLERT: DB file in '{DB_PATH}' wasn't found! Check the Path.")
    
    threading.Thread(target=check_for_new_articles, daemon=True).start()
    logging.info("🤖 Content Manager Telegram started and polling...")
    
    try:
        bot.polling(none_stop=True)
    except Exception as e:
        logging.error(f"Erroe in bot polling: {e}")