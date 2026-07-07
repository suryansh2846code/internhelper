from llm import get_llm

SYSTEM_PROMPT = """You are helping a college student apply for internships on Internshala.
Given their resume and a job description, write concise, genuine answers to application questions.
Keep answers under 150 words unless the question explicitly asks for more.
Sound like a motivated student — not a polished corporate professional.
Never fabricate skills or experiences not present in the resume."""


def generate_answers(job_title: str, company: str, jd: str, resume: str, questions: list[str]) -> dict[str, str]:
    llm = get_llm()
    answers = {}
    for question in questions:
        user_prompt = f"""
Resume:
{resume}

Company: {company}
Role: {job_title}
Job Description:
{jd}

Application Question:
{question}

Write a focused, honest answer to this question based solely on the resume above.
"""
        answers[question] = llm.generate(SYSTEM_PROMPT, user_prompt).strip()
    return answers
