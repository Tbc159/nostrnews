import sqlite3
import telebot
from telebot import types

API_TOKEN = 'IL_TUO_TELEGRAM_BOT_TOKEN'
CHAT_ID = 'IL_TUO_USER_ID_O_CHAT_ID' # The bot will send here the messages
DB_PATH = 'published.db'

bot = telebot.TeleBot(API_TOKEN)

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    """Buttons select manager"""
    data = call.data.split("|")
    action = data[0]
    guid = data[1]

    conn = get_db_connection()
    cursor = conn.cursor()

    if action == "approve":
        cursor.execute("UPDATE published SET status = 'reviewed' WHERE guid = ?", (guid,))
        bot.answer_callback_query(call.id, "✅ Nostr Approved!")
        bot.edit_message_caption(chat_id=call.message.chat.id, message_id=call.message.message_id, 
                                 caption=call.message.caption + "\n\n✨ STATUS: REVIEWED")
    
    elif action == "reject":
        cursor.execute("UPDATE published SET status = 'deleted' WHERE guid = ?", (guid,))
        bot.answer_callback_query(call.id, "❌ Refused.")
        bot.edit_message_caption(chat_id=call.message.chat.id, message_id=call.message.message_id, 
                                 caption=call.message.caption + "\n\n🗑️ STATUS: DELETED")

    conn.commit()
    conn.close()

def send_new_records():
    """Send records in 'draft' status, that aren't still sended to Telegram"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Selezioniamo i draft (puoi aggiungere una colonna 'tg_sent' nel DB se vuoi evitare duplicati)
    cursor.execute("SELECT * FROM published WHERE status = 'draft' LIMIT 5")
    rows = cursor.fetchall()

    for row in rows:
        text = (
            f"📰 *RSS Source:* {row['category']}\n"
            f"📂 *Category:* {row['category']}\n"
            f"📅 *Data:* {row['published_at']}\n"
            f"📌 *Tile:* {row['title']}\n"
            f"✍️ *Author:* {row['author']}\n"
            f"🏷️ *Tags:* {row['tags']}\n"
            f"🔗 [Read Article]({row['link']})\n"
            f"🚦 *Status:* {row['status']}"
        )

        # Buttons Creation
        markup = types.InlineKeyboardMarkup(row_width=2)
        btn_approve = types.InlineKeyboardButton("✅ Approve", callback_data=f"approve|{row['guid']}")
        btn_reject = types.InlineKeyboardButton("❌ Reject", callback_data=f"reject|{row['guid']}")
        markup.add(btn_approve, btn_reject)

        bot.send_message(CHAT_ID, text, parse_mode='Markdown', reply_markup=markup)

    conn.close()

if __name__ == "__main__":
    print("Bot waiting to send records...")
    send_new_records()
    bot.polling()