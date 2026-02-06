import sqlite3
import telebot
import time
import threading
from telebot import types

API_TOKEN = 'xxx'
CHAT_ID = 123456789   # The bot will send here the messages
DB_PATH = 'published.db'

bot = telebot.TeleBot(API_TOKEN)

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    """Buttons select manager"""
    action, guid = call.data.split("|")
    conn = get_db_connection()
    cursor = conn.cursor()

    if action == "approve":
        cursor.execute("UPDATE published SET status = 'reviewed' WHERE guid = ?", (guid,))
        new_text = "✅ **APPROVED**\nThe article will publish on Nostr on next agent execution."
    else:
        cursor.execute("UPDATE published SET status = 'skipped' WHERE guid = ?", (guid,))
        new_text = "❌ **REJECTED**\nThe article will not publish."

    conn.commit()
    conn.close()
    
    bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
    bot.send_message(call.message.chat.id, f"{new_text}\n\nOriginal: {call.message.text[:50]}...", parse_mode='Markdown')

def check_for_new_articles():
    """Check and Send periodicaly records in 'draft' status, that aren't still sended to Telegram"""
    while True:
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            # Getting the articles that still not sended on Telegram
            cursor.execute("SELECT * FROM published WHERE status = 'draft' AND tg_sent = 0")
            rows = cursor.fetchall()

            for row in rows:
                msg = (
                    f"🔔 *NEW ARTICLE FOUNDED*\n\n"
                    f"📰 *RSS Source:* {row['category']}\n"
                    f"📂 *Category:* {row['category']}\n"
                    f"📅 *Data:* {row['published_at']}\n"
                    f"📌 *Tile:* {row['title']}\n"
                    f"✍️ *Author:* {row['author'] or 'N/A'}\n"
                    f"🏷️ Tags: `{row['tags'] or 'N/A'}\n\n"
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

            conn.close()
        except Exception as e:
            print(f"Errore nel monitoraggio: {e}")
        
        time.sleep(60)

if __name__ == "__main__":
    threading.Thread(target=check_for_new_articles, daemon=True).start()
    print("🤖 Content Manager Telegram started...")
    bot.polling(none_stop=True)