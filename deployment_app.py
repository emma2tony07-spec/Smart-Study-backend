from flask import Flask, request, jsonify
from flask_cors import CORS
import google.generativeai as genai
import json
import os
import re
import smtplib
import threading
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime
from werkzeug.utils import secure_filename

app = Flask(__name__)
CORS(app)

# ═══════════════════════════════════════════════════════════════
#  CONFIGURATION — loaded from environment variables
#  Never hard-code secrets. Set these in your deployment platform:
#    Render → Environment tab
#    Railway → Variables tab
#    Local   → create a .env file and use python-dotenv
# ═══════════════════════════════════════════════════════════════
GMAIL_ADDRESS  = os.environ.get("GMAIL_ADDRESS",  "")
GMAIL_APP_PASS = os.environ.get("GMAIL_APP_PASS", "")
FROM_NAME      = os.environ.get("FROM_NAME",      "StudyOS")
APP_URL        = os.environ.get("APP_URL",         "https://your-app.onrender.com")

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
AI_MODEL       = os.environ.get("AI_MODEL",       "gemini-2.0-flash")

# File uploads — use /tmp on cloud platforms (ephemeral but fine for temp files)
BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.environ.get("UPLOAD_FOLDER", os.path.join(BASE_DIR, "temp_uploads"))
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

ALLOWED_EXTENSIONS = {"pdf", "txt", "docx"}
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024  # 20 MB

# Configure Gemini
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
else:
    print("⚠️  GEMINI_API_KEY not set — AI endpoints will fail")

# Reminder state (in-memory — resets on restart, acceptable for MVP)
pending_reminders = {}
reminder_lock     = threading.Lock()


# ═══════════════════════════════════════════════════════════════
#  UTILS
# ═══════════════════════════════════════════════════════════════
def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def fmt_date(dt):
    """Cross-platform date format (no %-d which is Linux-only)."""
    # e.g. "Saturday, April 5, 2026"
    return dt.strftime("%A, %B {d}, %Y").replace("{d}", str(dt.day))


def fmt_time(dt):
    """Cross-platform 12-hour time (no %-I which is Linux-only)."""
    # e.g. "9:05 AM"
    hour = dt.hour % 12 or 12
    return f"{hour}:{dt.strftime('%M')} {'AM' if dt.hour < 12 else 'PM'}"


# ═══════════════════════════════════════════════════════════════
#  EMAIL
# ═══════════════════════════════════════════════════════════════
TYPE_LABELS = {
    "reading":    {"label": "Reading Session",  "emoji": "📖"},
    "quiz":       {"label": "Quiz",             "emoji": "✏️"},
    "assignment": {"label": "Assignment",       "emoji": "📝"},
    "revision":   {"label": "Revision Session", "emoji": "🔄"},
}


def build_email_html(to_name, task, course_name, subject_line, intro_line):
    cfg      = TYPE_LABELS.get(task.get("type", ""), {"label": task.get("type", "Task"), "emoji": "📚"})
    task_dt  = datetime.fromisoformat(f"{task['date']}T{task['time']}")
    date_str = fmt_date(task_dt)
    time_str = fmt_time(task_dt)
    duration = int(task.get("duration", 30))
    dur_str  = f"{duration // 60} hour{'s' if duration > 60 else ''}" if duration >= 60 else f"{duration} minutes"
    course_row = (f'<p style="margin:0 0 8px;color:#A09A92;font-size:14px">'
                  f'<strong style="color:#F0EDE8">📚 Course:</strong> {course_name}</p>') if course_name else ""
    notes_row  = (f'<p style="margin:0 0 8px;color:#A09A92;font-size:14px">'
                  f'<strong style="color:#F0EDE8">💬 Notes:</strong> {task["notes"]}</p>') if task.get("notes") else ""

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/></head>
<body style="margin:0;padding:0;background:#0D0D0D;font-family:'Helvetica Neue',Helvetica,Arial,sans-serif">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#0D0D0D;padding:40px 20px">
    <tr><td align="center">
      <table width="560" cellpadding="0" cellspacing="0"
             style="background:#141414;border-radius:16px;overflow:hidden;border:1px solid rgba(255,255,255,0.08)">
        <tr>
          <td style="background:#9B1D20;padding:28px 36px">
            <p style="margin:0 0 10px;display:inline-block;background:rgba(255,255,255,0.18);
               border-radius:8px;padding:4px 12px;font-size:11px;color:white;font-weight:700;
               letter-spacing:0.08em;text-transform:uppercase">{subject_line}</p>
            <h1 style="margin:0;color:white;font-size:24px;font-weight:700;letter-spacing:-0.02em">
              {cfg['emoji']} {cfg['label']} Time!
            </h1>
          </td>
        </tr>
        <tr>
          <td style="padding:32px 36px">
            <p style="margin:0 0 24px;font-size:15px;color:#A09A92;line-height:1.6">
              Hi <strong style="color:#F0EDE8">{to_name}</strong>, {intro_line}
            </p>
            <div style="background:#1C1C1C;border-radius:12px;padding:20px 24px;
                        border-left:4px solid #9B1D20;margin-bottom:28px">
              <h2 style="margin:0 0 14px;color:#F0EDE8;font-size:17px;font-weight:600">{task['title']}</h2>
              <p style="margin:0 0 8px;color:#A09A92;font-size:14px">
                <strong style="color:#F0EDE8">📅 When:</strong> {date_str} at {time_str}
              </p>
              <p style="margin:0 0 8px;color:#A09A92;font-size:14px">
                <strong style="color:#F0EDE8">⏱ Duration:</strong> {dur_str}
              </p>
              {course_row}
              {notes_row}
            </div>
            <div style="text-align:center">
              <a href="{APP_URL}"
                 style="display:inline-block;background:#9B1D20;color:white;
                        text-decoration:none;padding:13px 32px;border-radius:10px;
                        font-size:15px;font-weight:600;letter-spacing:-0.01em">
                Open StudyOS →
              </a>
            </div>
          </td>
        </tr>
        <tr>
          <td style="padding:18px 36px;border-top:1px solid rgba(255,255,255,0.06)">
            <p style="margin:0;font-size:12px;color:#6B6560;text-align:center">
              StudyOS · Sent because you scheduled a study task.
            </p>
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""


def build_email_text(to_name, task, course_name, intro_line):
    cfg      = TYPE_LABELS.get(task.get("type", ""), {"label": task.get("type", "Task"), "emoji": "📚"})
    task_dt  = datetime.fromisoformat(f"{task['date']}T{task['time']}")
    duration = int(task.get("duration", 30))
    dur_str  = f"{duration // 60}h" if duration >= 60 else f"{duration}m"
    lines = [
        f"Hi {to_name}, {intro_line}", "",
        f"{cfg['emoji']} {cfg['label']}: {task['title']}",
        f"📅 {fmt_date(task_dt)} at {fmt_time(task_dt)} ({dur_str})",
    ]
    if course_name:   lines.append(f"📚 Course: {course_name}")
    if task.get("notes"): lines.append(f"💬 Notes: {task['notes']}")
    lines += ["", f"Open StudyOS: {APP_URL}", "", "— StudyOS"]
    return "\n".join(lines)


def send_email(to_address, to_name, subject, task, course_name,
               subject_line_badge, intro_line):
    if not GMAIL_ADDRESS or not GMAIL_APP_PASS:
        print("⚠️  Gmail not configured — skipping email")
        return False
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = f"{FROM_NAME} <{GMAIL_ADDRESS}>"
        msg["To"]      = to_address
        msg.attach(MIMEText(build_email_text(to_name, task, course_name, intro_line), "plain"))
        msg.attach(MIMEText(build_email_html(to_name, task, course_name, subject_line_badge, intro_line), "html"))
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_ADDRESS, GMAIL_APP_PASS)
            server.sendmail(GMAIL_ADDRESS, to_address, msg.as_string())
        print(f"📧 Sent → {to_address} | {subject}")
        return True
    except smtplib.SMTPAuthenticationError:
        print("❌ Gmail auth failed — check GMAIL_ADDRESS / GMAIL_APP_PASS env vars")
        return False
    except Exception as e:
        print(f"❌ Email error: {e}")
        return False


# ═══════════════════════════════════════════════════════════════
#  REMINDER BACKGROUND THREAD
#  Note: in-memory state resets on server restart.
#  For persistent reminders across restarts, store in Firebase/DB.
# ═══════════════════════════════════════════════════════════════
def reminder_checker():
    print("⏰ Reminder thread started")
    while True:
        time.sleep(60)
        now = datetime.now()
        with reminder_lock:
            for task_id, entry in list(pending_reminders.items()):
                if entry["reminder_sent"]:
                    continue
                task = entry["task"]
                if not task.get("date") or not task.get("time"):
                    continue
                try:
                    task_dt  = datetime.fromisoformat(f"{task['date']}T{task['time']}")
                    diff_min = (task_dt - now).total_seconds() / 60
                    if 0 <= diff_min <= 5:
                        print(f"⏰ Reminder: {task['title']}")
                        send_email(
                            to_address        = entry["user_email"],
                            to_name           = entry["user_name"],
                            subject           = f"⏰ Starting soon: {task['title']} at {fmt_time(task_dt)}",
                            task              = task,
                            course_name       = entry.get("course_name"),
                            subject_line_badge= "5-Minute Reminder",
                            intro_line        = f"your <strong style='color:#F0EDE8'>{task['title']}</strong> session starts in about 5 minutes."
                        )
                        entry["reminder_sent"] = True
                    elif diff_min < 0:
                        entry["reminder_sent"] = True
                except Exception as e:
                    print(f"Reminder error for {task_id}: {e}")


# Start thread (safe for both Flask dev server and Gunicorn)
threading.Thread(target=reminder_checker, daemon=True).start()


# ═══════════════════════════════════════════════════════════════
#  AI — GEMINI
# ═══════════════════════════════════════════════════════════════
def call_gemini(messages, expect_json=True):
    system_instruction = None
    prompt_parts = []
    for msg in messages:
        if msg["role"] == "system":
            system_instruction = msg["content"]
        elif msg["role"] == "user":
            prompt_parts.append(msg["content"])

    model = genai.GenerativeModel(
        model_name=AI_MODEL,
        system_instruction=system_instruction,
        generation_config=genai.types.GenerationConfig(
            temperature=0.7,
            response_mime_type="application/json" if expect_json else "text/plain",
        )
    )
    response = model.generate_content("\n\n".join(prompt_parts))
    content  = response.text
    if expect_json:
        clean = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip())
        return json.loads(clean)
    return content


def ai_detect_chapters(text):
    return call_gemini([
        {"role": "system", "content": (
            "You are an expert document analyser. Detect logical chapter/section boundaries. "
            'Return ONLY valid JSON: {"chapters": [{"title": "string", "content": "string"}]} '
            "Include full relevant text per chapter. Do not summarise."
        )},
        {"role": "user", "content": text[:20000]}
    ])


def ai_summarize_and_question(text):
    return call_gemini([
        {"role": "system", "content": (
            "You are an expert tutor. Given study material:\n"
            "1. Write a concise summary (3-5 sentences).\n"
            "2. Generate exactly 3 practice questions.\n"
            'Return ONLY valid JSON: {"summary": "string", "questions": ["string","string","string"]}'
        )},
        {"role": "user", "content": text[:15000]}
    ])


def ai_grade_answer(chapter_text, student_answer):
    return call_gemini([
        {"role": "system", "content": (
            "You are a strict but fair academic evaluator. "
            "Evaluate the answer for accuracy, depth, and key concepts. "
            'Return ONLY valid JSON: {"score": <integer 0-10>, "feedback": "string"} '
            "Score: 0-5=poor, 6-7=adequate, 8-9=good, 10=excellent. "
            "Feedback: specific and constructive, 2-3 sentences."
        )},
        {"role": "user", "content": f"Chapter:\n{chapter_text[:12000]}\n\nStudent Answer:\n{student_answer}"}
    ])


# ── Text extraction ────────────────────────────────────────────
def extract_text_from_pdf(filepath):
    try:
        import fitz
        doc  = fitz.open(filepath)
        text = "\n".join(page.get_text() for page in doc)
        doc.close()
        if text.strip(): return text
    except ImportError:
        pass
    except Exception as e:
        print(f"pymupdf error: {e}")
    try:
        import PyPDF2
        with open(filepath, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            text = "\n".join((p.extract_text() or "") for p in reader.pages)
        if text.strip(): return text
    except Exception as e:
        print(f"PyPDF2 error: {e}")
    return None


def extract_text_from_txt(filepath):
    for enc in ("utf-8", "latin-1"):
        try:
            with open(filepath, "r", encoding=enc) as f:
                return f.read()
        except UnicodeDecodeError:
            continue
    return None


def extract_text_from_docx(filepath):
    try:
        import docx
        doc  = docx.Document(filepath)
        text = "\n".join(p.text for p in doc.paragraphs)
        return text if text.strip() else None
    except Exception as e:
        print(f"DOCX error: {e}")
        return None


def get_text(filepath):
    ext = filepath.rsplit(".", 1)[1].lower()
    if ext == "pdf":  return extract_text_from_pdf(filepath)
    if ext == "txt":  return extract_text_from_txt(filepath)
    if ext == "docx": return extract_text_from_docx(filepath)
    return None


# ═══════════════════════════════════════════════════════════════
#  ROUTES
# ═══════════════════════════════════════════════════════════════
@app.route("/analyze", methods=["POST"])
def analyze_file():
    try:
        if "file" not in request.files:
            return jsonify({"error": "No file uploaded"}), 400
        file = request.files["file"]
        if not file.filename or not allowed_file(file.filename):
            return jsonify({"error": "Invalid or unsupported file type"}), 400

        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        file.save(filepath)

        text = get_text(filepath)
        try: os.remove(filepath)
        except: pass

        if not text or len(text.strip()) < 50:
            return jsonify({"error": "Could not extract text. For PDFs install pymupdf."}), 400

        result   = ai_detect_chapters(text)
        chapters = result.get("chapters", [])
        if not chapters:
            raise ValueError("AI returned no chapters")

        return jsonify({"chapters": chapters, "total_chapters": len(chapters)})

    except json.JSONDecodeError:
        return jsonify({"error": "AI returned invalid JSON. Please try again."}), 500
    except Exception as e:
        print(f"❌ /analyze: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/summarize", methods=["POST"])
def summarize():
    try:
        file = request.files.get("file")
        if not file:
            return jsonify({"error": "No file provided"}), 400
        text = file.read().decode("utf-8", errors="ignore")
        if not text.strip():
            return jsonify({"error": "Empty chapter content"}), 400

        result = ai_summarize_and_question(text)
        return jsonify({
            "summary":   result.get("summary",   "No summary available."),
            "questions": result.get("questions", [])
        })
    except json.JSONDecodeError:
        return jsonify({"error": "AI returned invalid JSON. Please try again."}), 500
    except Exception as e:
        print(f"❌ /summarize: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/grade", methods=["POST"])
def grade():
    try:
        chapter_text   = request.form.get("chapter_text", "").strip()
        student_answer = request.form.get("answer",        "").strip()
        if not student_answer:
            return jsonify({"error": "No answer provided"}), 400

        result   = ai_grade_answer(chapter_text, student_answer)
        score    = max(0, min(10, int(result.get("score", 5))))
        feedback = result.get("feedback", "Good effort. Keep studying!")
        return jsonify({"score": score, "feedback": feedback})

    except json.JSONDecodeError:
        return jsonify({"error": "AI returned invalid JSON. Please try again."}), 500
    except Exception as e:
        print(f"❌ /grade: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/send-confirmation", methods=["POST"])
def send_confirmation():
    try:
        data        = request.get_json()
        task        = data.get("task")
        user_email  = data.get("user_email", "").strip()
        user_name   = data.get("user_name",  "Student")
        course_name = data.get("course_name", None)

        if not task or not user_email:
            return jsonify({"error": "Missing task or user_email"}), 400
        if not task.get("date") or not task.get("time"):
            return jsonify({"ok": True, "message": "No time set — email skipped"}), 200

        task_dt  = datetime.fromisoformat(f"{task['date']}T{task['time']}")
        time_str = fmt_time(task_dt)

        send_email(
            to_address        = user_email,
            to_name           = user_name,
            subject           = f"✅ Task Scheduled: {task['title']} at {time_str}",
            task              = task,
            course_name       = course_name,
            subject_line_badge= "Task Confirmed",
            intro_line        = f"your task <strong style='color:#F0EDE8'>{task['title']}</strong> has been scheduled."
        )

        task_id = task.get("id", str(time.time()))
        with reminder_lock:
            pending_reminders[task_id] = {
                "task":          task,
                "user_email":    user_email,
                "user_name":     user_name,
                "course_name":   course_name,
                "reminder_sent": False
            }

        return jsonify({"ok": True, "message": "Confirmation sent, reminder scheduled"})

    except Exception as e:
        print(f"❌ /send-confirmation: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/cancel-reminder", methods=["POST"])
def cancel_reminder():
    try:
        data    = request.get_json()
        task_id = data.get("task_id")
        if task_id:
            with reminder_lock:
                pending_reminders.pop(task_id, None)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status":            "healthy",
        "model":             AI_MODEL,
        "gmail_configured":  bool(GMAIL_ADDRESS and GMAIL_APP_PASS),
        "gemini_configured": bool(GEMINI_API_KEY),
        "pending_reminders": len(pending_reminders),
        "app_url":           APP_URL,
    })


# ═══════════════════════════════════════════════════════════════
#  ENTRY POINT
#  For production, run with Gunicorn (see Procfile):
#    gunicorn app:app
#  For local dev:
#    python app.py
# ═══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("=" * 60)
    print("🚀 StudyOS Backend  (dev mode)")
    print(f"🤖 Model  : {AI_MODEL}")
    print(f"📧 Gmail  : {'✅ ' + GMAIL_ADDRESS if GMAIL_ADDRESS else '⚠️  Not set (GMAIL_ADDRESS env var)'}")
    print(f"🔑 Gemini : {'✅ Set' if GEMINI_API_KEY else '⚠️  Not set (GEMINI_API_KEY env var)'}")
    print(f"🌐 URL    : http://localhost:5000")
    print("=" * 60)
    app.run(debug=False, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
