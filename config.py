import os
from dotenv import load_dotenv

load_dotenv()

INTERNSHALA_EMAIL = os.getenv("INTERNSHALA_EMAIL")
INTERNSHALA_PASSWORD = os.getenv("INTERNSHALA_PASSWORD")

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "anthropic")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

RESUME_PATH = os.getenv("RESUME_PATH", "./data/resume.txt")

SESSION_PATH = "./data/sessions/internshala_session.json"

INTERNSHALA_BASE_URL = "https://internshala.com"
