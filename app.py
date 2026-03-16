import json
import traceback
import os
import logging
from flask import Flask, request, jsonify
from flask_cors import CORS
import urllib.request

# -----------------------------
# CONFIGURATION
# -----------------------------
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "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")
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
YOUR_SITE_URL = os.environ.get("SITE_URL", "https://your-app.onrender.com")
YOUR_APP_NAME = "SmartStudy"

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# -----------------------------
# HELPER FUNCTIONS
# -----------------------------

def call_openrouter(messages):
    """Call OpenRouter API with given messages and return JSON-decoded response."""
    try:
        data = json.dumps({
            "model": "nvidia/nemotron-3-nano-30b-a3b:free",  # Free model for testing
            "messages": messages,
            "temperature": 0.7,
            "response_format": {"type": "json_object"}
        }).encode("utf-8")

        req = urllib.request.Request(OPENROUTER_API_URL, data=data)
        req.add_header("Content-Type", "application/json")
        req.add_header("Authorization", f"Bearer {OPENROUTER_API_KEY}")
        req.add_header("HTTP-Referer", YOUR_SITE_URL)
        req.add_header("X-Title", YOUR_APP_NAME)

        with urllib.request.urlopen(req, timeout=60) as response:
            result = json.loads(response.read().decode())
            content = result["choices"][0]["message"]["content"]
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                return {"summary": content, "questions": ["Could not parse questions."]}
    except Exception as e:
        logger.error(f"OpenRouter API error: {str(e)}")
        raise

def detect_chapters(text):
    """Ask AI to detect chapters and return structured JSON."""
    messages = [
        {"role": "system", "content": (
            "You are an expert document analyzer. "
            "Detect logical chapter boundaries. "
            "Return strictly JSON in format: { 'chapters': [ { 'title': string, 'content': string } ] } "
            "Do not summarize the content, only structure chapters."
        )},
        {"role": "user", "content": text[:20000]}
    ]
    return call_openrouter(messages)

def summarize_chapter(text):
    """Ask AI to summarize a single chapter and generate practice questions."""
    messages = [
        {"role": "system", "content": (
            "You are an expert tutor. Provide a concise summary and 3 practice questions with answers. "
            "Return JSON: { 'summary': string, 'questions': array of strings }"
        )},
        {"role": "user", "content": text[:15000]}
    ]
    return call_openrouter(messages)

def grade_answer(chapter_text, student_answer):
    """Ask AI to grade the student's answer for a chapter."""
    messages = [
        {"role": "system", "content": (
            "You are a strict but fair academic evaluator. "
            "Evaluate the student's answer based on the chapter content. "
            "Return JSON: { 'feedback': string, 'score': integer 0-10 }"
        )},
        {"role": "user", "content": f"Chapter Content:\n{chapter_text[:15000]}\n\nStudent Answer:\n{student_answer}"}
    ]
    return call_openrouter(messages)

# -----------------------------
# ROUTES
# -----------------------------

@app.route('/', methods=['GET'])
def home():
    return jsonify({
        "status": "online",
        "message": "SmartStudy API is running",
        "endpoints": {
            "/analyze": "POST - Send text to detect chapters",
            "/summarize": "POST - Send text to get summary and questions",
            "/grade": "POST - Grade student answer",
            "/health": "GET - Health check"
        }
    })

@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "healthy"}), 200

@app.route('/analyze', methods=['POST'])
def analyze():
    """Receive raw text and detect chapters."""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No JSON data provided"}), 400

        text = data.get('text', '').strip()
        if not text:
            return jsonify({"error": "Missing 'text' field"}), 400

        result = detect_chapters(text)
        return jsonify(result), 200

    except Exception as e:
        logger.error(f"Error in /analyze: {traceback.format_exc()}")
        return jsonify({"error": str(e)}), 500

@app.route('/summarize', methods=['POST'])
def summarize():
    """Receive raw text and return summary and practice questions."""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No JSON data provided"}), 400

        text = data.get('text', '').strip()
        if not text:
            return jsonify({"error": "Missing 'text' field"}), 400

        result = summarize_chapter(text)
        return jsonify(result), 200

    except Exception as e:
        logger.error(f"Error in /summarize: {traceback.format_exc()}")
        return jsonify({"error": str(e)}), 500

@app.route('/grade', methods=['POST'])
def grade():
    """Grade student's answer."""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No JSON data provided"}), 400

        chapter_text = data.get('chapter_text', '').strip()
        answer = data.get('answer', '').strip()

        if not chapter_text or not answer:
            return jsonify({"error": "Missing 'chapter_text' or 'answer'"}), 400

        result = grade_answer(chapter_text, answer)
        return jsonify(result), 200

    except Exception as e:
        logger.error(f"Error in /grade: {traceback.format_exc()}")
        return jsonify({"error": str(e)}), 500

# -----------------------------
# MAIN
# -----------------------------
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
