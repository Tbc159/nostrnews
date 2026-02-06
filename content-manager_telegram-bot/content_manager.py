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
                content = f.read().strip()
                return int(content) if content else None
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

def process_tag_update(message, db_id, original_msg_id):
    new_tags = message.text.strip()
    chat_id = message.chat.id
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE published SET tags = ? WHERE id = ?", (new_tags, db_id))
        conn.commit()
        cursor.execute("SELECT * FROM published WHERE id = ?", (db_id,))
        article = cursor.fetchone()
        conn.close()

        # Pulizia messaggi di servizio
        try:
            bot.delete_message(chat_id, message.message_id)
            bot.delete_message(chat_id, message.reply_to_message.message_id)
        except: pass

        # Aggiorna il messaggio originale con i nuovi tag e rimetti i bottoni
        msg_text = (
            f"📝 *PENDING REVIEW (Tags Updated)*\n\n"
            f"📌 *Title:* {article['title']}\n"
            f"📂 *Category:* {article['category']}\n"
            f"✍️ *Author:* {article['author'] or 'N/A'}\n"
            f"🏷️ *Tags:* `{new_tags}`\n\n"
            f"🔗 [Read Article]({article['link']})"
        )
        
        markup = types.InlineKeyboardMarkup()
        markup.row(
            types.InlineKeyboardButton("✅ Approve", callback_data=f"apr|{db_id}"),
            types.InlineKeyboardButton("🗑️ Reject", callback_data=f"rej|{db_id}")
        )
        markup.row(types.InlineKeyboardButton("🏷️ Edit Tags Again", callback_data=f"tag|{db_id}"))

        bot.edit_message_text(
            chat_id=chat_id,
            message_id=original_msg_id,
            text=msg_text,
            parse_mode='Markdown',
            reply_markup=markup
        )

    except Exception as e:
        logging.error(f"Error in tag update: {e}")
        bot.send_message(chat_id, "❌ Errore durante l'aggiornamento dei tag.")

@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    try:
        data = call.data.split("|")
        action = data[0]
        db_id = data[1]

        conn = get_db_connection()
        cursor = conn.cursor()

        # 1. Recuperiamo prima i dati dell'articolo
        cursor.execute("SELECT * FROM published WHERE id = ?", (db_id,))
        article = cursor.fetchone()

        if not article:
            logging.warning(f"Article ID {db_id} not found in DB.")
            bot.answer_callback_query(call.id, "Error: Article not found.")
            conn.close()
            return

        # 2. Gestione Azioni e definizione dello Status Display
        if action == "apr":
            cursor.execute("UPDATE published SET status = 'reviewed' WHERE id = ?", (db_id,))
            status_display = "✅ APPROVED (Will be published on Nostr)"
            logging.info(f"Approved Article: {article['title']} (ID: {db_id})")
        elif action == "rej":
            cursor.execute("UPDATE published SET status = 'skipped' WHERE id = ?", (db_id,))
            status_display = "❌ REJECTED (Will not be published)"
            logging.info(f"Rejected Article: {article['title']} (ID: {db_id})")
        elif action == "tag":
            msg = bot.send_message(
                call.message.chat.id, 
                "✍️ Send new tags comma separated, for this article:",
                reply_markup=types.ForceReply(selective=True)
            )
            # Passiamo sia l'ID del DB che l'ID del messaggio originale da aggiornare
            bot.register_next_step_handler(msg, process_tag_update, db_id, call.message.message_id)
            bot.answer_callback_query(call.id)
        else:
            conn.close()
            return

        conn.commit()
        conn.close()

        # 3. Ricostruzione messaggio (Usiamo i dati salvati in 'article')
        updated_msg = (
            f"🔔 *ARTICLE MANAGED*\n\n"
            f"📅 *Date:* {article['published_at']}\n"
            f"📌 *Title:* {article['title']}\n"
            f"🚦 *Status:* {status_display}"
        )

        # 4. Update del messaggio Telegram
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=updated_msg,
            parse_mode='Markdown',
            disable_web_page_preview=False,
            reply_markup=None # Rimuove i bottoni
        )
        
        bot.answer_callback_query(call.id, "Action updated!")

    except Exception as e:
        logging.error(f"Error in callback handler: {e}", exc_info=True)

def check_for_new_articles():
    logging.info(f"Monitoring DB thread started (Sequential Mode): {DB_PATH}")
    while True:
        target_id = get_target_chat_id()
        if not target_id:
            time.sleep(10)
            continue
            
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) as count FROM published WHERE status = 'draft' AND tg_sent = 1")
            pending_count = cursor.fetchone()['count']
            
            if pending_count > 0:
                conn.close()
                time.sleep(120)
                continue

            cursor.execute("SELECT * FROM published WHERE status = 'draft' AND tg_sent = 0 ORDER BY published_at ASC LIMIT 1")
            row = cursor.fetchone()
            conn.close()

            if row:
                db_id = row['id']
                msg = (
                    f"📝 *PENDING REVIEW*\n\n"
                    f"📌 *Title:* {row['title']}\n"
                    f"📂 *Category:* {row['category']}\n"
                    f"✍️ *Author:* {row['author'] or 'N/A'}\n"
                    f"🏷️ *Tags:* `{row['tags'] or 'N/A'}`\n\n"
                    f"🔗 [Read Article]({row['link']})"
                )
                
                markup = types.InlineKeyboardMarkup()
                markup.row(
                    types.InlineKeyboardButton("✅ Approve", callback_data=f"apr|{db_id}"),
                    types.InlineKeyboardButton("🗑️ Reject", callback_data=f"rej|{db_id}")
                )
                markup.row(
                    types.InlineKeyboardButton("🏷️ Edit Tags", callback_data=f"tag|{db_id}")
                )

                bot.send_message(target_id, msg, parse_mode='Markdown', reply_markup=markup)
                
                conn_update = get_db_connection()
                conn_update.execute("UPDATE published SET tg_sent = 1 WHERE id = ?", (db_id,))
                conn_update.commit()
                conn_update.close()
                logging.info(f"Sent article ID {db_id} for review.")

        except Exception as e:
            logging.error(f"Error in monitoring loop: {e}")
        
        time.sleep(60)

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