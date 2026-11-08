import logging
import os
import threading
import pdfplumber
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

# Logging setup
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Dummy Flask Server for Cloud Deployment ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Telegram Quiz Bot is running successfully!"

def run_flask():
    # Render ya dusre platforms PORT environment variable dete hain
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
# ---------------------------------------------

# In-memory storage (Production ke liye Database use karein)
QUIZ_STATE = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Namaste! Mujhe ek PDF bhejiye jisme questions aur unke answers hon, taaki mai ek quiz create kar saku."
    )

# PDF Handle karne ka function
async def handle_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    document = update.message.document
    if not document or not document.file_name.endswith('.pdf'):
        await update.message.reply_text("Kripya ek valid PDF file bhejiye.")
        return

    file = await context.bot.get_file(document.file_id)
    file_path = f"./{document.file_name}"
    await file.download_to_drive(file_path)

    # PDF se text extract karna
    questions = extract_questions_from_pdf(file_path)
    
    if not questions:
        await update.message.reply_text("PDF se questions extract nahi ho paye. Kripya format check karein.")
        return

    QUIZ_STATE[update.effective_chat.id] = {
        "questions": questions,
        "current_q": 0,
        "scores": {},
        "times": {}
    }

    keyboard = [[InlineKeyboardButton("Start Quiz", callback_data="start_quiz")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(f"Total {len(questions)} questions mil gaye hain!", reply_markup=reply_markup)

def extract_questions_from_pdf(pdf_path):
    extracted_questions = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            full_text = ""
            for page in pdf.pages:
                full_text += page.extract_text() or ""
            
            # Dummy structure for demonstration:
            extracted_questions.append({
                "question": "What is the capital of India?",
                "options": ["Delhi", "Mumbai", "Kolkata", "Chennai"],
                "answer": 0 # Index of correct option
            })
    except Exception as e:
        logger.error(f"Error reading PDF: {e}")
    return extracted_questions

async def start_quiz_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    
    q_data = QUIZ_STATE.get(chat_id)
    if not q_data:
        await query.message.reply_text("Koi active quiz nahi mila. Dobara PDF bhejiye.")
        return

    current = q_data["current_q"]
    question_item = q_data["questions"][current]

    await context.bot.send_poll(
        chat_id=chat_id,
        question=question_item["question"],
        options=question_item["options"],
        type="quiz",
        correct_option_id=question_item["answer"],
        is_anonymous=False
    )

def main():
    # Flask server ko ek alag background thread me chalayein taaki bot aur server dono sath chalein
    server_thread = threading.Thread(target=run_flask)
    server_thread.daemon = True
    server_thread.start()

    # Apna Telegram Bot Token yahan dalein (Environment variable use karna behtar hai)
    TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN")
    
    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.Document.PDF, handle_pdf))
    application.add_handler(CallbackQueryHandler(start_quiz_callback, pattern="start_quiz"))

    print("Bot and Dummy Server are running...")
    application.run_polling()

if __name__ == "__main__":
    main()
