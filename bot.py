import logging
import os
import threading
import time
import re
import fitz  # PyMuPDF library for high-quality image cropping
import pdfplumber
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
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

SAVED_QUIZZES = {}  # {user_id: {quiz_name: {"questions": [...], "images": [...]}}}
QUIZ_STATE = {}     # {chat_id: active_quiz_data}
TEMP_PDF_DATA = {}  # {user_id: data}

def process_pdf_to_images_and_questions(pdf_path):
    extracted_data = []
    images_dir = "./quiz_images"
    os.makedirs(images_dir, exist_ok=True)

    try:
        # PyMuPDF (fitz) ka use karke PDF ko pages me load karna
        doc = fitz.open(pdf_path)
        
        # Sath hi pdfplumber se text aur answer key nikalna
        with pdfplumber.open(pdf_path) as pdf:
            full_text = ""
            for page in pdf.pages:
                full_text += (page.extract_text() or "") + "\n"

            answer_dict = {}
            ans_split = re.split(r'Answer Key', full_text, flags=re.IGNORECASE)
            main_text = ans_split[0]
            answer_text = ans_split[1] if len(ans_split) > 1 else ""

            ans_matches = re.findall(r'Q(\d+)\s*[\(\[]?([1-4])[\)\]]?', answer_text)
            for q_no, ans_opt in ans_matches:
                answer_dict[int(q_no)] = int(ans_opt) - 1

        # Har page par text blocks dhoondh kar questions extract karna aur image crop karna
        q_counter = 1
        for page_num in range(len(doc)):
            page = doc[page_num]
            
            # PyMuPDF se text blocks nikalna
            blocks = page.get_text("blocks")
            # Blocks ko vertical/horizontal order me sort karna
            blocks.sort(key=lambda b: (b[1], b[0]))

            for b in blocks:
                block_text = b[4]
                if block_text.strip().startswith("Q") or re.search(r'Q\d+', block_text):
                    # Question ka text clean karna
                    q_text_clean = re.sub(r'\[\d{4}.*?\]', '', block_text).strip()
                    
                    # Options extract karne ke liye choti regex
                    options = ["Option 1", "Option 2", "Option 3", "Option 4"] # Default fallback
                    
                    # Image crop coordinates (x0, y0, x1, y1)
                    rect = fitz.Rect(b[0], b[1], b[2], b[3])
                    pix = page.get_pixmap(clip=rect, dpi=150) # High quality crop
                    img_path = os.path.join(images_dir, f"q_{q_counter}_{time.time()}.png")
                    pix.save(img_path)

                    correct_idx = answer_dict.get(q_counter, 0)
                    extracted_data.append({
                        "id": q_counter,
                        "image_path": img_path,
                        "options": ["Option (1)", "Option (2)", "Option (3)", "Option (4)"], # Ya text options
                        "answer": correct_idx
                    })
                    q_counter += 1

    except Exception as e:
        logger.error(f"Error processing PDF images: {e}")

    return extracted_data

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = (
        "🌟 **Welcome to Ultimate Quiz Bot!** 🌟\n\n"
        "Aap apni study PDFs yahan bhejiye. Main har question ki **saaf image** crop karke ek professional visual quiz taiyar kar dunga!\n\n"
        "📌 **Quick Guide:**\n"
        "• **PDF bhejiye** - Naya visual quiz banane ke liye\n"
        "• `/savequiz <Name>` - Quiz save karne ke liye\n"
        "• `/myquizzes` - Saved quizzes khelne ke liye\n"
        "• `/stop` - Quiz rokne ke liye"
    )
    keyboard = [[KeyboardButton("📚 My Saved Quizzes"), KeyboardButton("❓ Help")]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode="Markdown")

async def handle_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    document = update.message.document
    if not document or not document.file_name.endswith('.pdf'):
        await update.message.reply_text("⚠️ Kripya ek valid PDF file bhejiye.")
        return

    msg = await update.message.reply_text("🖼️ PDF scan ho rahi hai aur har question ki high-quality images crop ki ja rahi hain...")
    
    file = await context.bot.get_file(document.file_id)
    file_path = f"./{document.file_name}"
    await file.download_to_drive(file_path)

    questions = process_pdf_to_images_and_questions(file_path)
    
    if not questions:
        await msg.edit_text("❌ PDF se questions crop nahi ho paye.")
        return

    user_id = update.effective_user.id
    TEMP_PDF_DATA[user_id] = questions

    await msg.edit_text(
        f"✅ **Success!** Total `{len(questions)}` questions ki images crop ho chuki hain.\n\n"
        "Ab is quiz ko save karne ke liye yeh command bhejiye:\n"
        "`/savequiz Quiz_Name`",
        parse_mode="Markdown"
    )

async def save_quiz_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in TEMP_PDF_DATA:
        await update.message.reply_text("⚠️ Pehle koi PDF bhejiye!")
        return

    if not context.args:
        await update.message.reply_text("⚠️ Kripya quiz ka naam dein. Example: `/savequiz Chemistry_Visual`", parse_mode="Markdown")
        return

    quiz_name = "_".join(context.args)
    if user_id not in SAVED_QUIZZES:
        SAVED_QUIZZES[user_id] = {}

    SAVED_QUIZZES[user_id][quiz_name] = TEMP_PDF_DATA[user_id]
    del TEMP_PDF_DATA[user_id]

    keyboard = [[InlineKeyboardButton(f"🚀 Start '{quiz_name}' Now", callback_data=f"start_saved_{quiz_name}")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        f"🎉 Visual Quiz **'{quiz_name}'** safaltapoorvak save ho gaya hai!",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def list_saved_quizzes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    quizzes = SAVED_QUIZZES.get(user_id, {})

    if not quizzes:
        await update.message.reply_text("📭 Aapne abhi tak koi quiz save nahi kiya hai.")
        return

    keyboard = []
    for q_name in quizzes.keys():
        keyboard.append([InlineKeyboardButton(f"📖 {q_name}", callback_data=f"start_saved_{q_name}")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("📂 **Aapke Saved Visual Quizzes:**", reply_markup=reply_markup, parse_mode="Markdown")

async def start_saved_quiz_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    quiz_name = query.data.replace("start_saved_", "")
    user_id = query.from_user.id
    chat_id = query.message.chat_id

    questions = SAVED_QUIZZES.get(user_id, {}).get(quiz_name)
    if not questions:
        await query.message.reply_text("⚠️ Yeh quiz nahi mila.")
        return

    QUIZ_STATE[chat_id] = {
        "quiz_name": quiz_name,
        "questions": questions,
        "current_q": 0,
        "scores": {},
        "question_start_time": time.time(),
        "active": True
    }

    await query.message.reply_text(f"🚀 Visual Quiz **'{quiz_name}'** shuru ho raha hai!", parse_mode="Markdown")
    await send_question(chat_id, context)

async def stop_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id in QUIZ_STATE and QUIZ_STATE[chat_id]["active"]:
        QUIZ_STATE[chat_id]["active"] = False
        await update.message.reply_text("🛑 Quiz rok diya gaya hai.")
    else:
        await update.message.reply_text("⚠️ Yahan koi active quiz nahi hai.")

async def send_question(chat_id, context):
    q_data = QUIZ_STATE.get(chat_id)
    if not q_data or not q_data["active"]:
        return

    idx = q_data["current_q"]
    questions = q_data["questions"]

    if idx >= len(questions):
        await show_leaderboard(chat_id, context)
        return

    q = questions[idx]
    keyboard = [
        [
            InlineKeyboardButton("(1)", callback_data=f"ans_{idx}_0"),
            InlineKeyboardButton("(2)", callback_data=f"ans_{idx}_1"),
            InlineKeyboardButton("(3)", callback_data=f"ans_{idx}_2"),
            InlineKeyboardButton("(4)", callback_data=f"ans_{idx}_3")
        ],
        [InlineKeyboardButton("👤 Check My Status", callback_data=f"status_{chat_id}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    q_data["question_start_time"] = time.time()
    
    # Text ke bajay image bhejna
    with open(q["image_path"], "rb") as photo:
        await context.bot.send_photo(
            chat_id=chat_id,
            photo=photo,
            caption=f"🎯 **Quiz: {q_data['quiz_name']}** | Question {idx+1}/{len(questions)}",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )

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
        await query.answer("⚠️ Yeh quiz active nahi hai!", show_alert=True)
        return

    questions = q_data["questions"]
    if q_idx != q_data["current_q"]:
        await query.answer("⚠️ Yeh question purana ho chuka hai!", show_alert=True)
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
        await query.answer("✨ Sahi jawab! (+4)", show_alert=False)
    else:
        user_record["score"] -= 1
        user_record["incorrect"] += 1
        await query.answer("❌ Galat jawab! (-1)", show_alert=False)

    q_data["current_q"] += 1

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
        await context.bot.send_message(chat_id=chat_id, text="📊 Kisi ne attempt nahi kiya.")
        return

    sorted_users = sorted(
        scores.values(), 
        key=lambda x: (x["score"], -sum(x["times"]) if x["times"] else 0), 
        reverse=True
    )

    leaderboard_text = f"🏆 **Leaderboard: {q_data['quiz_name']}** 🏆\n\n"
    for rank, u in enumerate(sorted_users, 1):
        avg_time = sum(u["times"]) / len(u["times"]) if u["times"] else 0
        medal = "🥇" if rank == 1 else "🥈" if rank == 2 else "🥉" if rank == 3 else f"{rank}."
        leaderboard_text += f"{medal} **{u['name']}** — Score: `{u['score']}` | Avg Time: `{avg_time:.2f}s`\n"

    keyboard = [[InlineKeyboardButton("📊 Check Personal Status", callback_data=f"global_status_{chat_id}")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await context.bot.send_message(chat_id=chat_id, text=leaderboard_text, reply_markup=reply_markup, parse_mode="Markdown")

async def status_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    chat_id = query.message.chat_id

    q_data = QUIZ_STATE.get(chat_id)
    if not q_data:
        await query.answer("⚠️ Koi data nahi mila.", show_alert=True)
        return

    user_record = q_data["scores"].get(user_id)
    if not user_record:
        await query.answer("⚠️ Aapne participate nahi kiya!", show_alert=True)
        return

    avg_time = sum(user_record["times"]) / len(user_record["times"]) if user_record["times"] else 0
    
    status_msg = (
        f"📊 Aapka Status:\n"
        f"👤 {user_record['name']}\n"
        f"🎯 Score: {user_record['score']}\n"
        f"✅ Sahi: {user_record['correct']} | ❌ Galat: {user_record['incorrect']}\n"
        f"⏱️ Avg Time: {avg_time:.2f}s"
    )
    await query.answer(status_msg, show_alert=True)

def main():
    server_thread = threading.Thread(target=run_flask)
    server_thread.daemon = True
    server_thread.start()

    TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN")
    
    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stop", stop_quiz))
    application.add_handler(CommandHandler("myquizzes", list_saved_quizzes))
    application.add_handler(CommandHandler("savequiz", save_quiz_command))
    application.add_handler(MessageHandler(filters.Document.PDF, handle_pdf))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    application.add_handler(CallbackQueryHandler(start_saved_quiz_callback, pattern="^start_saved_"))
    application.add_handler(CallbackQueryHandler(answer_callback, pattern="^ans_"))
    application.add_handler(CallbackQueryHandler(status_callback, pattern="^(status_|global_status_)"))

    print("Visual Quiz Bot is running with image cropping...")
    application.run_polling()

if __name__ == "__main__":
    main()
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "📚 My Saved Quizzes":
        await list_saved_quizzes(update, context)
    elif text == "❓ Help":
        await start(update, context)
