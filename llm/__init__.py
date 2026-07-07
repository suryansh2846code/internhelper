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
    else:
        raise ValueError(f"Unknown LLM_PROVIDER: {provider}")
