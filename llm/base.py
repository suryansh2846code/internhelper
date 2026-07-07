from abc import ABC, abstractmethod


class BaseLLM(ABC):
    """All LLM backends implement this interface."""

    @abstractmethod
    def generate(self, system_prompt: str, user_prompt: str) -> str:
        """Return a generated text response."""
        ...
