from llm.base import BaseLLM
import config


class LocalLLM(BaseLLM):
    """
    Plug-in point for your self-trained model.

    Set LOCAL_MODEL_TYPE in .env to one of:
      - huggingface  (loads from LOCAL_MODEL_PATH via transformers pipeline)
      - ollama       (calls a local Ollama server)
      - custom       (override _load_model and generate yourself)
    """

    def __init__(self):
        self.model_type = config.LOCAL_MODEL_TYPE
        self.model_path = config.LOCAL_MODEL_PATH
        self._model = self._load_model()

    def _load_model(self):
        if self.model_type == "huggingface":
            return self._load_huggingface()
        elif self.model_type == "ollama":
            return None  # handled in generate via HTTP
        elif self.model_type == "custom":
            raise NotImplementedError("Implement _load_model for your custom model")
        else:
            raise ValueError(f"Unknown LOCAL_MODEL_TYPE: {self.model_type}")

    def _load_huggingface(self):
        from transformers import pipeline
        return pipeline("text-generation", model=self.model_path)

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        if self.model_type == "huggingface":
            prompt = f"{system_prompt}\n\n{user_prompt}"
            result = self._model(prompt, max_new_tokens=512, do_sample=True)
            return result[0]["generated_text"][len(prompt):]

        elif self.model_type == "ollama":
            import urllib.request, json
            payload = json.dumps({
                "model": self.model_path,
                "prompt": f"{system_prompt}\n\n{user_prompt}",
                "stream": False,
            }).encode()
            req = urllib.request.Request(
                "http://localhost:11434/api/generate",
                data=payload,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req) as resp:
                return json.loads(resp.read())["response"]

        raise NotImplementedError
