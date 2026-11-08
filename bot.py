import logging
import os
import threading
import time
import re
import pdfplumber
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# --- Dummy Flask Server for Cloud Deployment ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Telegram Quiz Bot is running successfully!"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
# ---------------------------------------------

# In-memory storage for quiz state, scores, and timing
QUIZ_STATE = {}

def extract_questions_from_pdf(pdf_path):
    extracted_questions = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            full_text = ""
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    full_text += text + "\n"

            # Answer key section alag karna
            answer_dict = {}
            ans_split = re.split(r'Answer Key', full_text, flags=re.IGNORECASE)
            main_text = ans_split[0]
            answer_text = ans_split[1] if len(ans_split) > 1 else ""

            ans_matches = re.findall(r'Q(\d+)\s*[\(\[]?([1-4])[\)\]]?', answer_text)
            if not ans_matches:
                ans_matches = re.findall(r'Q(\d+)\s*[:\-]?\s*[\(\[]?([1-4])[\)\]]?', full_text)

            for q_no, ans_opt in ans_matches:
                answer_dict[int(q_no)] = int(ans_opt) - 1

            # Questions aur options extract karna
            q_blocks = re.split(r'(?=Q\d+\s)', main_text)

            for block in q_blocks:
                block = block.strip()
                if not block.startswith('Q'):
                    continue
                
                q_num_match = re.match(r'Q(\d+)', block)
                if not q_num_match:
                    continue
                q_no = int(q_num_match.group(1))

                lines = block.split('\n')
                q_lines = []
                options = []

                for line in lines:
                    opt_match = re.match(r'^\s*[\(\[]([1-4])[\)\]]\s*(.*)', line)
                    if opt_match:
                        options.append(opt_match.group(2).strip())
                    else:
                        if not re.match(r'^Q\d+', line):
                            q_lines.append(line)

                q_text = " ".join(q_lines).strip()
                q_text = re.sub(r'^Q\d+\s*', '', q_text)

                if q_text and len(options) >= 2:
                    correct_idx = answer_dict.get(q_no, 0)
                    extracted_questions.append({
                        "id": q_no,
                        "question": q_text,
                        "options": options[:4],
                        "answer": correct_idx
                    })
    except Exception as e:
        logger.error(f"Error parsing PDF: {e}")

    return extracted_questions

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Namaste! Mujhe PDF bhejiye, mai usse questions extract karke quiz shuru kar dunga."
    )

async def handle_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    document = update.message.document
    if not document or not document.file_name.endswith('.pdf'):
        await update.message.reply_text("Kripya ek valid PDF file bhejiye.")
        return

    file = await context.bot.get_file(document.file_id)
    file_path = f"./{document.file_name}"
    await file.download_to_drive(file_path)

    questions = extract_questions_from_pdf(file_path)
    
    if not questions:
        await update.message.reply_text("PDF se questions extract nahi ho paye.")
        return

    chat_id = update.effective_chat.id
    QUIZ_STATE[chat_id] = {
        "questions": questions,
        "current_q": 0,
        "scores": {},
        "question_start_time": time.time(),
        "active": True
    }

    keyboard = [[InlineKeyboardButton("Start Quiz", callback_data="start_quiz")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(f"Total {len(questions)} questions mil gaye hain!", reply_markup=reply_markup)

async def start_quiz_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id

    q_data = QUIZ_STATE.get(chat_id)
    if not q_data or not q_data["active"]:
        await query.message.reply_text("Koi active quiz nahi mila.")
        return

    q_data["question_start_time"] = time.time()
    await send_question(chat_id, context)

async def send_question(chat_id, context):
    q_data = QUIZ_STATE.get(chat_id)
    if not q_data:
        return

    idx = q_data["current_q"]
    questions = q_data["questions"]

    if idx >= len(questions):
        await show_leaderboard(chat_id, context)
        return

    q = questions[idx]
    keyboard = []
    for i, opt in enumerate(q["options"]):
        keyboard.append([InlineKeyboardButton(f"{i+1}. {opt}", callback_data=f"ans_{idx}_{i}")])
    
    keyboard.append([InlineKeyboardButton("Check My Status", callback_data=f"status_{chat_id}")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    msg = f"**Question {idx+1}/{len(questions)}**\n\n{q['question']}"
    await context.bot.send_message(chat_id=chat_id, text=msg, reply_markup=reply_markup, parse_mode="Markdown")

async def answer_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data.split("_")
    q_idx = int(data[1])
    selected_opt = int(data[2])
    
    chat_id = query.message.chat_id
    user_id = query.from_user.id
    user_name = query.from_user.first_name

    q_data = QUIZ_STATE.get(chat_id)
    if not q_data or not q_data["active"]:
        await query.answer("Yeh quiz active nahi hai!", show_alert=True)
        return

    questions = q_data["questions"]
    if q_idx != q_data["current_q"]:
        await query.answer("Yeh question purana ho chuka hai!", show_alert=True)
        return

    time_taken = time.time() - q_data["question_start_time"]
    correct_opt = questions[q_idx]["answer"]

    if user_id not in q_data["scores"]:
        q_data["scores"][user_id] = {"name": user_name, "score": 0, "correct": 0, "incorrect": 0, "times": []}

    user_record = q_data["scores"][user_id]
    user_record["times"].append(time_taken)

    if selected_opt == correct_opt:
        user_record["score"] += 4
        user_record["correct"] += 1
        await query.answer("Sahi jawab! (+4)", show_alert=False)
    else:
        user_record["score"] -= 1
        user_record["incorrect"] += 1
        await query.answer("Galat jawab! (-1)", show_alert=False)

    q_data["current_q"] += 1
    q_data["question_start_time"] = time.time()

    try:
        await query.message.delete()
    except Exception:
        pass

    await send_question(chat_id, context)

async def show_leaderboard(chat_id, context):
    q_data = QUIZ_STATE.get(chat_id)
    if not q_data:
        return
    
    q_data["active"] = False
    scores = q_data["scores"]

    if not scores:
        await context.bot.send_message(chat_id=chat_id, text="Kisi ne bhi quiz attempt nahi kiya.")
        return

    sorted_users = sorted(
        scores.values(), 
        key=lambda x: (x["score"], -sum(x["times"]) if x["times"] else 0), 
        reverse=True
    )

    leaderboard_text = "🏆 **Quiz Leaderboard** 🏆\n\n"
    for rank, u in enumerate(sorted_users, 1):
        avg_time = sum(u["times"]) / len(u["times"]) if u["times"] else 0
        leaderboard_text += f"{rank}. **{u['name']}** - Score: `{u['score']}` | Avg Time: `{avg_time:.2f}s`\n"

    keyboard = [[InlineKeyboardButton("Check Personal Status", callback_data=f"global_status_{chat_id}")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await context.bot.send_message(chat_id=chat_id, text=leaderboard_text, reply_markup=reply_markup, parse_mode="Markdown")

async def status_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    chat_id = query.message.chat_id

    q_data = QUIZ_STATE.get(chat_id)
    if not q_data:
        await query.answer("Koi data available nahi hai.", show_alert=True)
        return

    user_record = q_data["scores"].get(user_id)
    if not user_record:
        await query.answer("Aapne is quiz me participate nahi kiya hai!", show_alert=True)
        return

    avg_time = sum(user_record["times"]) / len(user_record["times"]) if user_record["times"] else 0
    
    status_msg = (
        f"📊 Aapka Personal Status:\n\n"
        f"Naam: {user_record['name']}\n"
        f"Total Score: {user_record['score']}\n"
        f"Sahi: {user_record['correct']}\n"
        f"Galat: {user_record['incorrect']}\n"
        f"Average Time: {avg_time:.2f} seconds"
    )
    await query.answer(status_msg, show_alert=True)

def main():
    server_thread = threading.Thread(target=run_flask)
    server_thread.daemon = True
    server_thread.start()

    TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN")
    
    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.Document.PDF, handle_pdf))
    application.add_handler(CallbackQueryHandler(start_quiz_callback, pattern="^start_quiz$"))
    application.add_handler(CallbackQueryHandler(answer_callback, pattern="^ans_"))
    application.add_handler(CallbackQueryHandler(status_callback, pattern="^(status_|global_status_)"))

    print("Bot and Dummy Server are running...")
    application.run_polling()

if __name__ == "__main__":
    main()
