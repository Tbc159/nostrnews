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

CONFIG_FILE = 'chat_id.txt'
API_TOKEN = 'xxx'
DB_PATH = os.path.expanduser('~/nostrnews/published.db')
bot = telebot.TeleBot(API_TOKEN)

def get_target_chat_id():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            try:
                return int(f.read().strip())
            except: return None
    return None

def save_target_chat_id(chat_id):
    with open(CONFIG_FILE, 'w') as f:
        f.write(str(chat_id))

@bot.message_handler(commands=['setchat'])
def set_chat(message):
    save_target_chat_id(message.chat.id)
    bot.reply_to(message, f"🎯 Configured Chat! I'll send the news here. (ID: {message.chat.id})")

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
        data = call.data.split("|")
        action = data[0]
        db_id = data[1]

        conn = get_db_connection()
        cursor = conn.cursor()

        if action == "apr":
            cursor.execute("UPDATE published SET status = 'reviewed' WHERE id = ?", (db_id,))
            status_display = "✅ **APPROVED**\nThe article will publish on Nostr on next execution."
            logging.info(f"Approved Article (ID: {db_id})")
        elif action == "rej":
            cursor.execute("UPDATE published SET status = 'rejected' WHERE id = ?", (db_id,))
            status_display = "❌ **REJECTED**\nThe article will not be published."
            logging.info(f"ALERT: Article Rejected (ID: {db_id})")
        else:
            logging.warning(f"Can't manage action: {action}")
            conn.close()
            return

        conn.commit()
        
        cursor.execute("SELECT title FROM published WHERE id = ?", (db_id,))
        article = cursor.fetchone()
        title = article['title'] if article else "Unknown"
        
        logging.info(f"{status_text}: {title} (ID: {db_id})")
        conn.close()

        if row:
            # 3. Ricostruisci il messaggio originale con il NUOVO Status
            updated_msg = (
                f"🔔 *ARTICLE PROCESSED*\n\n"
                f"📂 *Category:* {row['category']}\n"
                f"📅 *Date:* {row['published_at']}\n"
                f"📌 *Title:* {row['title']}\n"
                f"✍️ *Author:* {row['author'] or 'N/A'}\n"
                f"🏷️ *Tags:* `{row['tags'] or 'N/A'}`\n\n"
                f"🔗 [Read Article]({row['link']})\n"
                f"🚦 *Status:* {status_display}"
            )

            # 4. Sovrascrive il messaggio originale (rimuovendo anche i bottoni)
            bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text=updated_msg,
                parse_mode='Markdown',
                reply_markup=None # Rimuove i bottoni
            )

    except Exception as e:
        logging.error(f"Error in callback handler: {e}", exc_info=True)

def check_for_new_articles():
    logging.info(f"Monitoring DB thread started: {DB_PATH}")
    while True:
        target_id = get_target_chat_id()
        if not target_id:
            time.sleep(10)
            continue
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            # Getting the articles that still not sended on Telegram
            cursor.execute("SELECT * FROM published WHERE status = 'draft' AND tg_sent = 0")
            rows = cursor.fetchall()
            conn.close()

            if rows:
                logging.info(f"Articles found: {len(rows)} ready to process.")
            
            for row in rows:
                try:
                    db_id = row['id']
                    msg = (
                        f"🔔 *NEW ARTICLE FOUND*\n\n"
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
                        types.InlineKeyboardButton("✅ Approve", callback_data=f"apr|{db_id}"),
                        types.InlineKeyboardButton("🗑️ Reject", callback_data=f"rej|{db_id}")
                    )

                    bot.send_message(target_id, msg, parse_mode='Markdown', reply_markup=markup)
                    
                    # Sign like sended
                    conn_update = get_db_connection()
                    conn_update.execute("UPDATE published SET tg_sent = 1 WHERE id = ?", (db_id,))
                    conn_update.commit()
                    conn_update.close()
                    
                    logging.info(f"Sent to Telegram: ID {db_id}")
                    time.sleep(2)

                except telebot.apihelper.ApiTelegramException as e:
                    if e.error_code == 429:
                        retry_after = e.result_json.get('parameters', {}).get('retry_after', 30)
                        logging.warning(f"⚠️ Flood limit! Sleeping for {retry_after}s")
                        time.sleep(retry_after + 1)
                    else:
                        logging.error(f"Telegram API Error: {e}")

        except Exception as e:
            logging.error(f"Error in monitoring loop: {e}")
        
        time.sleep(120)

if __name__ == "__main__":
    if not os.path.exists(DB_PATH):
        logging.critical(f"ALERT: DB file not found in {DB_PATH}")
    
    threading.Thread(target=check_for_new_articles, daemon=True).start()
    logging.info("🤖 Content Manager Telegram started...")
    
    while True:
        try:
            bot.polling(none_stop=True)
        except Exception as e:
            logging.error(f"Polling error: {e}")
            time.sleep(5)