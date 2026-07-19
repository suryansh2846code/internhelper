import os
from dotenv import load_dotenv

load_dotenv()

INTERNSHALA_EMAIL = os.getenv("INTERNSHALA_EMAIL")
INTERNSHALA_PASSWORD = os.getenv("INTERNSHALA_PASSWORD")

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "anthropic")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
LOCAL_MODEL_PATH = os.getenv("LOCAL_MODEL_PATH", "./models/my_model")
LOCAL_MODEL_TYPE = os.getenv("LOCAL_MODEL_TYPE", "huggingface")

RESUME_PATH = os.getenv("RESUME_PATH", "./data/resume.txt")

SESSION_PATH = "./data/sessions/internshala_session.json"

INTERNSHALA_BASE_URL = "https://internshala.com"

# Internshala blocks headless browsers at the apply step, so search/apply must
# run headed. Playwright drives the browser over the DevTools protocol, so it
# does not need OS focus — when a valid session exists we launch the window,
# then hand focus straight back to whatever app you were using (macOS). The
# window opens in the background instead of switching away from your work.
# Set BROWSER_FOREGROUND=true in .env to keep the window focused (debugging).
BROWSER_FOREGROUND = os.getenv("BROWSER_FOREGROUND", "false").strip().lower() in ("1", "true", "yes", "on")
