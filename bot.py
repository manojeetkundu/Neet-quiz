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
        "Namaste! {user.firstname} Quiz Karna hai? to der kis baat ki! Mujhe ek PDF bhejiye jisme questions aur unke answers hon, mai quiz create kar deta hu."
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

import re

def extract_questions_from_pdf(pdf_path):
    extracted_questions = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            full_text = ""
            # Saare pages ka text collect karein
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    full_text += text + "\n"

            # 1. Questions aur Answers section ko alag karne ki koshish
            # Aam taur par answer key 'Answer Key', 'Answers', ya last ke pages par hoti hai
            answer_dict = {}
            answer_split_pattern = re.compile(r'(?:Answer Key|Answers|Solutions).*', re.IGNORECASE | re.DOTALL)
            split_match = answer_split_pattern.search(full_text)
            
            main_text = full_text
            answer_text = ""
            
            if split_match:
                # Agar answer section mil gaya, toh use alag kar lo
                main_text = full_text[:split_match.start()]
                answer_text = full_text[split_match.start():]
                
                # Answer key se mapping banana (jaise Q1 -> A, Q2 -> B)
                # Matches patterns like "1. A" ya "Q1: B" ya "1) C"
                ans_matches = re.findall(r'(\d+)[).\s:]+([A-Da-d])', answer_text)
                for q_no, ans in ans_matches:
                    # A=0, B=1, C=2, D=3 index map karna
                    ans_idx = ord(ans.upper()) - ord('A')
                    answer_dict[int(q_no)] = ans_idx

            # 2. Questions aur Options extract karna
            # Maankar chal rahe hain ki questions "1.", "2." se shuru hote hain
            question_blocks = re.split(r'\n(?=\s*\d+\.\s)', main_text)
            
            q_counter = 1
            for block in question_blocks:
                block = block.strip()
                if not block:
                    continue
                
                # Options (A), (B), (C), (D) ya (a), (b), (c), (d) ko dhoondhna
                lines = block.split('\n')
                q_lines = []
                options = []
                
                for line in lines:
                    # Agar line option se shuru hoti hai toh options list me daalein
                    if re.match(r'^\s*[\(\[]?[A-Da-d][\)\]\.]', line):
                        # Option letter hata kar sirf text rakhna
                        clean_opt = re.sub(r'^\s*[\(\[]?[A-Da-d][\)\]\.]\s*', '', line)
                        options.append(clean_opt)
                    else:
                        q_lines.append(line)
                
                q_text = " ".join(q_lines).strip()
                # Agar regex se options alag nahi hue toh fallback options
                if len(options) < 2:
                    options = ["Option A", "Option B", "Option C", "Option D"]
                
                # Agar answer key me is question ka answer hai toh woh use karo, warna default 0
                correct_ans_idx = answer_dict.get(q_counter, 0)
                
                if q_text:
                    extracted_questions.append({
                        "question": q_text,
                        "options": options[:4], # Sirf pehle 4 options rakhein
                        "answer": correct_ans_idx
                    })
                    q_counter += 1

    except Exception as e:
        print(f"Error parsing PDF: {e}")
        
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
