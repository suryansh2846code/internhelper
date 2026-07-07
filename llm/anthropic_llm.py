import anthropic
from llm.base import BaseLLM
import config


class AnthropicLLM(BaseLLM):
    def __init__(self, model: str = "claude-opus-4-8"):
        self.client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        self.model = model

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        message = self.client.messages.create(
            model=self.model,
            max_tokens=1024,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        return message.content[0].text
