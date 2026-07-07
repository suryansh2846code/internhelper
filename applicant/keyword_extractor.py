from llm import get_llm

_SYSTEM = """You extract concise Internshala search keywords from a student's resume.
Return ONLY a comma-separated list of 3-6 keywords. No explanation, no numbering.
Example output: python, data science, machine learning"""


def extract_keywords(resume_text: str, role_hint: str = "") -> list[str]:
    llm = get_llm()
    prompt = f"""Resume (first 3000 chars):
{resume_text[:3000]}

Target role: {role_hint or "general"}

Extract 3-6 Internshala search keywords that best match this resume and role.
Return ONLY comma-separated keywords."""

    raw = llm.generate(_SYSTEM, prompt)
    return [k.strip().lower() for k in raw.split(",") if k.strip()]
