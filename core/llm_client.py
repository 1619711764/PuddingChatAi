# LLM 客户端封装 v2
# 支持 OpenAI / Anthropic，统一接口，含流式输出和重试
# v2: 移除同步接口中多余的 stream_options 参数

import time
from openai import OpenAI, RateLimitError, APIConnectionError
from core.config import LLMConfig


class LLMClient:
    """统一的 LLM 调用接口"""

    def __init__(self, cfg: LLMConfig):
        if cfg.provider == "anthropic":
            raise NotImplementedError("Anthropic provider coming soon, use openai for now")

        self.cfg = cfg
        self.client = OpenAI(
            api_key=cfg.api_key,
            base_url=cfg.api_base or None,
        )
        self._input_tokens = 0
        self._output_tokens = 0
        self._total_calls = 0

    def chat(self, messages: list[dict], stream: bool = False, extra_body: dict = None):
        kwargs = dict(
            model=self.cfg.model,
            messages=messages,
            temperature=self.cfg.temperature,
            max_tokens=self.cfg.max_tokens,
            timeout=self.cfg.timeout,
            stream=stream,
        )
        if extra_body:
            kwargs["extra_body"] = extra_body

        self._total_calls += 1

        if stream:
            return self._chat_stream(kwargs)
        else:
            return self._chat_sync(kwargs)

    def _chat_sync(self, kwargs: dict) -> str:
        for attempt in range(3):
            try:
                resp = self.client.chat.completions.create(**kwargs)
                if resp.usage:
                    self._input_tokens += resp.usage.prompt_tokens
                    self._output_tokens += resp.usage.completion_tokens
                content = resp.choices[0].message.content
                return content or ""
            except (RateLimitError, APIConnectionError):
                if attempt < 2:
                    time.sleep(2 ** attempt)
                else:
                    raise

    def _chat_stream(self, kwargs: dict):
        for attempt in range(3):
            try:
                stream = self.client.chat.completions.create(**kwargs)
                for chunk in stream:
                    if chunk.choices and len(chunk.choices) > 0:
                        delta = chunk.choices[0].delta
                        if delta and delta.content:
                            yield delta.content
                return
            except (RateLimitError, APIConnectionError):
                if attempt < 2:
                    time.sleep(2 ** attempt)
                else:
                    raise

    @property
    def total_tokens(self):
        return self._input_tokens + self._output_tokens

    @property
    def total_calls(self):
        return self._total_calls
