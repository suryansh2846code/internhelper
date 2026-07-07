from groq import Groq
from llm.base import BaseLLM
import config


class GroqLLM(BaseLLM):
    def __init__(self, model: str = "llama-3.3-70b-versatile"):
        self.client = Groq(api_key=config.GROQ_API_KEY)
        self.model = model

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_prompt},
            ],
            max_tokens=1024,
        )
        return response.choices[0].message.content
