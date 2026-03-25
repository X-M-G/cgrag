from typing import List, Dict
from chunker_api.models import ChatMessage, ChatSession


def get_session_last_n_dialogue_pairs(
    *,
    user,
    session_id,
    max_pairs: int = 10,
) -> List[Dict[str, str]]:
    """
    获取当前 session 的最近 N 组 (user -> assistant) 对话
    """

    # 1️⃣ 校验 session 属于当前用户
    try:
        session = ChatSession.objects.get(id=session_id, user=user)
    except ChatSession.DoesNotExist:
        return []

    # 2️⃣ 取该 session 最近的消息（多取一点，防止 role 不对齐）
    messages = list(
        ChatMessage.objects
        .filter(session=session)
        .order_by('-created_at')[: max_pairs * 4]
    )

    # 3️⃣ 按时间正序处理
    messages.reverse()

    dialogue = []
    i = 0
    while i < len(messages) - 1:
        cur = messages[i]
        nxt = messages[i + 1]

        if cur.role == 'user' and nxt.role == 'assistant':
            dialogue.append({'role': 'user', 'content': cur.content})
            dialogue.append({'role': 'assistant', 'content': nxt.content})

        i += 1

    # 4️⃣ 只保留最后 max_pairs 组
    return dialogue[-max_pairs * 2:]
