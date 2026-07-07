from llm.base import BaseLLM
import config


def get_llm() -> BaseLLM:
    provider = config.LLM_PROVIDER
    if provider == "anthropic":
        from llm.anthropic_llm import AnthropicLLM
        return AnthropicLLM()
    elif provider == "openai":
        from llm.openai_llm import OpenAILLM
        return OpenAILLM()
    elif provider == "groq":
        from llm.groq_llm import GroqLLM
        return GroqLLM()
    elif provider == "local":
        from llm.local_llm import LocalLLM
        return LocalLLM()
    else:
        raise ValueError(f"Unknown LLM_PROVIDER: {provider}")
