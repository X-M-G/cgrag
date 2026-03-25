import os
from openai import OpenAI
import logging

logger = logging.getLogger(__name__)

class BaseLLM:
    def __init__(self, api_key: str, model: str):
        if not api_key:
            raise ValueError("API key is required.")
        self.api_key = api_key
        self.model = model

    def generate_answer(self, prompt: str, system_prompt: str = None) -> str:
        raise NotImplementedError("This method should be implemented by subclasses.")

    def generate_answer_multimodal(self, text: str, image_urls: list[str] | None = None, system_prompt: str | None = None) -> str:
        """可选的多模态回答接口，默认回退为纯文本。"""
        # 默认回退到文本
        return self.generate_answer(prompt=text, system_prompt=system_prompt)

class QwenLLM(BaseLLM):
    def __init__(self, api_key: str, model: str = "qwen-plus"):
        super().__init__(api_key, model)
        self.client = OpenAI(
            api_key=self.api_key,
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        )

    def generate_answer(self, prompt: str, system_prompt: str = "You are a helpful assistant.") -> str:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ]
        try:
            completion = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
            )
            return completion.choices[0].message.content
        except Exception as e:
            logger.error(f"Error calling Qwen API: {e}")
            raise

    def generate_answer_multimodal(self, text: str, image_urls: list[str] | None = None, system_prompt: str | None = None) -> str:
        """向支持视觉的千问模型发送图文消息（OpenAI兼容接口流式示例实现）。"""
        system_prompt = system_prompt or "You are a helpful assistant."
        # content 顺序：先图片再文本，贴合官方示例
        user_content: list[dict] = []
        if image_urls:
            for url in image_urls:
                if not url:
                    continue
                user_content.append({
                    "type": "image_url",
                    "image_url": {"url": url}
                })
        user_content.append({"type": "text", "text": text})

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]
        try:
            # 参照官方示例：qwen3-omni-flash 需 stream=True
            stream_iter = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                modalities=["text"],
                stream=True,
                stream_options={"include_usage": True}
            )
            final_text_parts: list[str] = []
            for chunk in stream_iter:
                if hasattr(chunk, 'choices') and chunk.choices:
                    delta = chunk.choices[0].delta
                    # 兼容 delta 为对象或字典
                    content = getattr(delta, 'content', None) or (delta.get('content') if isinstance(delta, dict) else None)
                    if content:
                        final_text_parts.append(content)
            return ''.join(final_text_parts).strip()
        except Exception as e:
            logger.error(f"Error calling Qwen API (multimodal/stream): {e}")
            # 回退到非流式
            try:
                completion = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                )
                return completion.choices[0].message.content
            except Exception as e2:
                logger.error(f"Error fallback non-stream: {e2}")
                return self.generate_answer(text, system_prompt=system_prompt)

def get_llm_service(api_key: str, model_name: str = "qwen-plus"):
    """Factory function to get an LLM service instance."""
    # For now, we only have Qwen. This can be extended later.
    if "qwen" in model_name.lower():
        return QwenLLM(api_key=api_key, model=model_name)
    else:
        # Potentially support other models here in the future
        raise ValueError(f"Unsupported LLM model: {model_name}")

