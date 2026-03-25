import sys
import time

from backend import settings


def stream_handle(text: str, delay: float = 0.01, chunk_size: int = 3) -> str:
    """
    模拟流式输出效果（按块输出）

    Args:
        text: 要输出的完整文本
        delay: 每个块输出的延迟时间（秒），默认 0.01 秒
        chunk_size: 每次输出的字符数，默认 3 个字符

    Returns:
        str: 返回原始文本
    """
    if not text:
        return text

    # 按块输出
    for i in range(0, len(text), chunk_size):
        chunk = text[i:i + chunk_size]
        print(chunk, end="", flush=True)
        time.sleep(delay)

    print()  # 最后换行
    return text


def stream_handle_by_word(text: str, delay: float = 0.05) -> str:
    """
    按词输出（更快的流式效果）

    Args:
        text: 要输出的完整文本
        delay: 每个词输出的延迟时间（秒），默认 0.02 秒

    Returns:
        str: 返回原始文本
    """
    if not text:
        return text

    # 简单按空格分词
    words = text.split(' ')

    for i, word in enumerate(words):
        if i > 0:
            print(' ', end="", flush=True)
        print(word, end="", flush=True)
        time.sleep(delay)

    print()  # 最后换行
    return text


def stream_handle_fast(text: str, delay: float = 0.05) -> str:
    """
    快速流式输出（按较大块输出）

    Args:
        text: 要输出的完整文本
        delay: 每个块输出的延迟时间（秒），默认 0.005 秒

    Returns:
        str: 返回原始文本
    """
    if not text:
        return text

    # 按 5-10 个字符一组输出
    chunk_size = 8

    for i in range(0, len(text), chunk_size):
        chunk = text[i:i + chunk_size]
        print(chunk, end="", flush=True)
        time.sleep(delay)

    print()  # 最后换行
    return text


# 使用示例
if __name__ == "__main__":

    # main.py
    from chunker_api.llm_service import get_llm_service

    # 1. 准备参数
    API_KEY = settings.DASHSCOPE_API_KEY
    MODEL_NAME = "qwen3-omni-flash"

    # 2. 获取服务实例
    llm = get_llm_service(api_key=API_KEY, model_name=MODEL_NAME)

    # 3. 调用 generate_answer
    try:
        prompt = "请问什么是RAG技术？"
        answer = llm.generate_answer(prompt)
        stream_answer = stream_handle_fast(answer)
    except Exception as e:
        print(f"调用失败: {e}")


