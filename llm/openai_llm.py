from openai import OpenAI
from llm.base import BaseLLM
import config


class OpenAILLM(BaseLLM):
    def __init__(self, model: str = "gpt-4o"):
        self.client = OpenAI(api_key=config.OPENAI_API_KEY)
        self.model = model

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=1024,
        )
        return response.choices[0].message.content
