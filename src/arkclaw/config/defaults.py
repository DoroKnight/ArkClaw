"""Defaults that are safe to use without external configuration."""

DEFAULT_PROVIDER = "fake"
DEFAULT_OPENAI_MODEL = "gpt-5-mini"
DEFAULT_DEEPSEEK_MODEL = "deepseek-v4-flash"
DEFAULT_OLLAMA_MODEL = "qwen3"
DEFAULT_PROVIDER_TIMEOUT_SECONDS = 30.0
DEFAULT_MAX_TURN_SECONDS = 90.0
DEFAULT_OPENAI_MAX_RETRIES = 2
DEFAULT_DEEPSEEK_MAX_RETRIES = 0
DEFAULT_OLLAMA_BASE_URL = "http://127.0.0.1:11434"
DEFAULT_MAX_OUTPUT_TOKENS = 1024
DEFAULT_STREAM = True

DEFAULT_SYSTEM_PROMPT = """\
You are ArkClaw, a concise and friendly personal desktop assistant.
Never claim that you observed the user's screen, microphone, files, or system state.
Never invent a tool result. Tool permissions are enforced by the application.
Do not expose or request hidden chain-of-thought.
"""
