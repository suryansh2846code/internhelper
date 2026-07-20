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

# Pacing to avoid Internshala throttling the account. Rapid, back-to-back Apply
# clicks get the session temporarily blocked (redirected to registration), so we
# pause between listings during classification and between bulk applications.
SEARCH_CLASSIFY_DELAY = float(os.getenv("SEARCH_CLASSIFY_DELAY", "1.5"))
APPLY_DELAY = float(os.getenv("APPLY_DELAY", "5"))
