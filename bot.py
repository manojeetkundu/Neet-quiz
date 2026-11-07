import logging
import sqlite3
import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from pypdf import PdfReader
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# Logging setup
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# --- DUMMY HTTP SERVER FOR RENDER (Port handling) ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is alive and running!")

def run_dummy_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    server.serve_forever()

# Background thread mein server start kar rahe hain
threading.Thread(target=run_dummy_server, daemon=True).start()

# --- DATABASE SETUP ---
def init_db():
    conn = sqlite3.connect('neet_bot.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            score INTEGER DEFAULT 0,
            attempted INTEGER DEFAULT 0,
            correct INTEGER DEFAULT 0,
            incorrect INTEGER DEFAULT 0
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# Global variables
user_progress = {}
DYNAMIC_QUESTIONS = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    conn = sqlite3.connect('neet_bot.db')
    cursor = conn.cursor()
    cursor.execute('INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)', (user.id, user.username))
    conn.commit()
    conn.close()
    
    await update.message.reply_text(
        f"👋 Namaste {user.first_name}!\n\n"
        "📄 **NEET Smart Quiz Bot** tyaar hai!\n"
        "Aap mujhe koi bhi PDF file bhejein, aur phir `/quiz` type karke ek-ek karke sawal hal karein!\n\n"
        "🚀 /quiz - Test shuru karein\n"
        "📊 /stats - Apni performance dekhein"
    )

# PDF Handler
async def handle_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global DYNAMIC_QUESTIONS
    message = update.message
    
    if not message.document:
        await message.reply_text("⚠️ Kripya ek valid PDF file bhejein!")
        return
        
    file = await message.document.get_file()
    file_path = "downloaded_neet.pdf"
    await file.download_to_drive(file_path)
    
    await message.reply_text("📥 PDF mil gayi hai! Questions extract ho rahe hain... 🔄")
    
    try:
        reader = PdfReader(file_path)
        text = ""
        for page in reader.pages:
            extracted = page.extract_text()
            if extracted:
                text += extracted + "\n"
                
        raw_questions = text.split("Q.") 
        extracted_q = {}
        
        for i, q_block in enumerate(raw_questions[1:], start=1):
            lines = q_block.strip().split("\n")
            if len(lines) >= 5:
                q_text = lines[0]
                options = lines[1:5]
                
                extracted_q[i] = {
                    "question": f"📖 Q{i}. {q_text}",
                    "options": [opt.strip() for opt in options],
                    "correct": 0,  
                    "explanation": "💡 NCERT based conceptual solution."
                }
                
        if extracted_q:
            DYNAMIC_QUESTIONS = extracted_q
            await message.reply_text(f"✅ Success! Total **{len(DYNAMIC_QUESTIONS)}** questions load ho gaye hain.\nAb `/quiz` type karke test shuru karein! 🎯")
        else:
            await message.reply_text("⚠️ PDF se questions extract nahi ho paye.")
            
    except Exception as e:
        await message.reply_text(f"❌ Error aa gayi: {str(e)}")

# Quiz Shuru Karne Ka Command
async def start_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not DYNAMIC_QUESTIONS:
        await update.message.reply_text("⚠️ Pehle koi PDF file bhej kar questions load karein!")
        return
        
    user_progress[user_id] = 1
    await send_question(update.effective_chat.id, user_id, context)

async def send_question(chat_id, user_id, context):
    q_index = user_progress[user_id]
    
    if q_index > len(DYNAMIC_QUESTIONS):
        await context.bot.send_message(chat_id=chat_id, text="🎉 Test samaapt hua! Apni performance dekhne ke liye /stats type karein.")
        return
        
    q_data = DYNAMIC_QUESTIONS[q_index]
    
    keyboard = []
    for idx, opt in enumerate(q_data["options"]):
        keyboard.append([InlineKeyboardButton(opt, callback_data=f"ans_{q_index}_{idx}")])
        
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await context.bot.send_message(
        chat_id=chat_id,
        text=f"{q_data['question']}",
        reply_markup=reply_markup
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data_parts = query.data.split("_")
    q_index = int(data_parts[1])
    selected_option = int(data_parts[2])
    user_id = query.from_user.id
    
    q_data = DYNAMIC_QUESTIONS[q_index]
    correct_option = q_data["correct"]
    is_correct = (selected_option == correct_option)
    
    conn = sqlite3.connect('neet_bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT score, attempted, correct, incorrect FROM users WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    
    if row:
        score, attempted, correct, incorrect = row
        attempted += 1
        if is_correct:
            score += 4
            correct += 1
            result_text = "✅ Sahi Jawab! (+4 marks)"
        else:
            score -= 1
            incorrect += 1
            result_text = f"❌ Galat Jawab! (-1 mark). Sahi option tha: {q_data['options'][correct_option]}"
            
        cursor.execute('''
            UPDATE users SET score = ?, attempted = ?, correct = ?, incorrect = ? WHERE user_id = ?
        ''', (score, attempted, correct, incorrect, user_id))
        conn.commit()
    conn.close()
    
    await query.edit_message_text(text=f"{query.message.text}\n\n{result_text}\n{q_data['explanation']}")
    
    user_progress[user_id] = q_index + 1
    await send_question(query.message.chat_id, user_id, context)

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conn = sqlite3.connect('neet_bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT score, attempted, correct, incorrect FROM users WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    conn.close()
    
    if row:
        score, attempted, correct, incorrect = row
        accuracy = (correct / attempted * 100) if attempted > 0 else 0
        
        stats_msg = (
            f"📊 **Aapki Performance Report** 📈\n\n"
            f"🎯 Total Score: `{score}` marks\n"
            f"📝 Total Attempted: `{attempted}`\n"
            f"✅ Correct (+4): `{correct}`\n"
            f"❌ Incorrect (-1): `{incorrect}`\n"
            f"⚡ Accuracy: `{accuracy:.2f}%`"
        )
        await update.message.reply_text(stats_msg, parse_mode="Markdown")
    else:
        await update.message.reply_text("⚠️ Pehle /start type karke registration karein!")

if __name__ == '__main__':
    # Render ke Environment Variable se token uthayega
    TOKEN = os.environ.get("BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN")
    
    app = ApplicationBuilder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("quiz", start_quiz))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(MessageHandler(filters.Document.PDF, handle_pdf))
    app.add_handler(CallbackQueryHandler(button_handler))
    
    print("✨ Clean NEET Quiz Bot successfully run ho raha hai!")
    app.run_polling()
