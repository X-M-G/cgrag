# rag_system.py

import os
import json
from typing import Dict, Any, Type, List
from dotenv import load_dotenv
from langchain_community.document_loaders import Docx2txtLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_chroma import Chroma
from langchain_community.chat_models import ChatZhipuAI
from langchain_openai import ChatOpenAI
from langchain_core.callbacks.manager import CallbackManager
from langchain_core.callbacks.streaming_stdout import StreamingStdOutCallbackHandler
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough
from langchain_core.prompts import ChatPromptTemplate
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_core.documents import Document
import sys
from pathlib import Path
import shutil

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# 导入混合检索组件
from hybrid_retrieval_fusion import (
    BM25Indexer,
    CrossEncoderWrapper,
    HybridRetriever,
    HybridLCRetriever
)

# ======================================================
# 模型配置
# ======================================================
MODEL_CONFIGS: Dict[str, Dict[str, Any]] = {
    "local-qwen": {
        "class": ChatOpenAI,
        "init_params": {
            "model": "qwen-1.5b",
            "api_key": "EMPTY",
            "base_url": "http://localhost:8080/v1",
        }
    },
    "gpt-3.5-proxy": {
        "class": ChatOpenAI,
        "init_params": {
            "model": "gpt-3.5-turbo",
            "api_key": "sk-hIrMwbu18ckorz0VMC1exrEx9REdIU5YD1BCcIAhNZ7bMLBh",
            "base_url": "https://api.chatanywhere.tech/v1",
        }
    },
    "glm-4": {
        "class": ChatZhipuAI,
        "init_params": {
            "model": "glm-4",
            "api_key": "fbadee75e10040b8984ab843dd15ce62.9uQjLLwLChvncIa0",
        }
    }
}


def create_chat_model1(model_name: str, temperature: float = 0.5):
    if model_name not in MODEL_CONFIGS:
        raise ValueError(f"模型 '{model_name}' 未配置。")
    config = MODEL_CONFIGS[model_name]
    model_class: Type = config["class"]
    init_params = config["init_params"].copy()
    init_params["streaming"] = True
    init_params["temperature"] = temperature
    init_params["callbacks"] = [StreamingStdOutCallbackHandler()]
    return model_class(**init_params)

def create_chat_model(model_name: str, temperature: float = 0.5, max_tokens: int = None):
    """
    根据模型名称创建对应的 chat 模型实例（支持流式输出和最大token限制）

    参数:
        model_name: 模型名称，必须在 MODEL_CONFIGS 中定义
        temperature: 温度参数
        max_tokens: 最大输出token数，可选，默认为None（不限制）

    返回:
        初始化好的 chat 模型实例
    """
    if model_name not in MODEL_CONFIGS:
        raise ValueError(
            f"模型 '{model_name}' 未在 MODEL_CONFIGS 中配置。\n"
            f"可用模型: {list(MODEL_CONFIGS.keys())}"
        )

    config = MODEL_CONFIGS[model_name]
    model_class: Type = config["class"]

    # 复制基础参数
    init_params = config["init_params"].copy()

    # 添加流式输出和温度参数
    init_params["streaming"] = True
    init_params["temperature"] = temperature
    init_params["callbacks"] = [StreamingStdOutCallbackHandler()]

    # 添加 max_tokens 参数（如果提供）
    if max_tokens is not None:
        init_params["max_tokens"] = max_tokens

    # 初始化并返回模型
    return model_class(**init_params)

# ======================================================
# 配置
# ======================================================
load_dotenv()

BGE_MODEL_NAME = r"G:\models\bge-large-zh"
RERANKER_MODEL_NAME = r"G:\models\bge-reranker-large"

KB_CONFIG_FILE = "kb_config.json"


# 全局组件
embedding_generator = HuggingFaceEmbeddings(
    model_name=BGE_MODEL_NAME,
    model_kwargs={'device': 'cuda'},
    encode_kwargs={'normalize_embeddings': True}
)

cross_encoder = CrossEncoderWrapper(model_path=RERANKER_MODEL_NAME)

text_splitter = RecursiveCharacterTextSplitter(
    chunk_size=500,
    chunk_overlap=100,
    separators=["\n\n", "\n", "。", "！", "？", "；", "，", " ", ""]
)




# 函数：删除知识库
def delete_kb(kb_name: str):
    config = KNOWLEDGE_BASES.get(kb_name)
    if not config:
        print(f"知识库 '{kb_name}' 不存在。")
        return
    chroma_store = Chroma(collection_name=config["collection_name"])
    chroma_store.delete_collection()
    if os.path.exists(config["bm25_dir"]):
        shutil.rmtree(config["bm25_dir"])
    del KNOWLEDGE_BASES[kb_name]
    save_kb_config()
    print(f"知识库 '{kb_name}' 删除。")


# 函数：获取检索器
def get_retriever(kb_name: str):
    config = KNOWLEDGE_BASES.get(kb_name)
    if not config:
        raise ValueError(f"知识库 '{kb_name}' 不存在。")
    chroma_store = Chroma(
        collection_name=config["collection_name"],
        embedding_function=embedding_generator,
    )
    bm25_indexer = BM25Indexer(store_dir=config["bm25_dir"])
    if not bm25_indexer.try_load():
        raise FileNotFoundError(f"未找到BM25索引: {config['bm25_dir']}")
    hybrid_retriever = HybridRetriever(
        vectorstore=chroma_store,
        bm25_indexer=bm25_indexer,
        cross_encoder=cross_encoder,
        embeddings=embedding_generator,
        m_for_rerank=80,
        top_k=5,
    )
    return HybridLCRetriever(hybrid_retriever)


# 函数：进行流式问答
def streaming_qa(kb_name: str, question: str, model_name: str = "gpt-3.5-proxy", temperature: float = 0.5):
    retriever = get_retriever(kb_name)
    chat = create_chat_model(model_name, temperature)
    template = """你是一个专业的政策问答助手。请根据以下检索到的上下文信息，准确回答用户的问题。

检索到的相关内容：
{context}

用户问题：{question}

回答要求：
1. 仅基于提供的上下文信息回答
2. 如果上下文中没有相关信息，请明确说明"根据提供的资料，我无法回答这个问题"
3. 回答要准确、简洁、易懂
4. 如果有具体的政策条款或步骤，请分点列出

你的回答："""
    prompt = ChatPromptTemplate.from_template(template)

    def format_docs(docs):
        formatted = []
        for i, doc in enumerate(docs, 1):
            source = doc.metadata.get('source', '未知')
            ce_norm = doc.metadata.get('_s_ce_norm', 0)
            rrf = doc.metadata.get('_rrf_score', 0)
            formatted.append(
                f"[文档{i}] (RRF:{rrf:.3f}, CE:{ce_norm:.3f})\n"
                f"内容: {doc.page_content}\n"
            )
        return "\n".join(formatted)

    rag_chain = (
            {"context": retriever | format_docs, "question": RunnablePassthrough()}
            | prompt
            | chat
            | StrOutputParser()
    )
    print(f"问题: {question}")
    print("回答:")
    rag_chain.invoke(question)
    print()  # 换行