"""
FastAPI RAG问答服务
提供流式问答接口，支持智能检索和直接对话
"""

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any, Type
import os
import shutil
from pathlib import Path
from dotenv import load_dotenv
from langchain_community.document_loaders import Docx2txtLoader, TextLoader, PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_chroma import Chroma
from langchain_community.chat_models import ChatZhipuAI, QianfanChatEndpoint
from langchain_openai import ChatOpenAI
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_core.documents import Document
import uvicorn
from uuid import uuid4
import json
from langchain_core.documents import Document
from typing import List, Dict, Any
import logging

logger = logging.getLogger(__name__)
from hybrid_retrieval_fusion import (
    BM25Indexer,
    CrossEncoderWrapper,
    HybridRetriever,
    HybridLCRetriever
)

# 导入Prompt模块
from utils.PromPt.prompt import (
    categorize_user_profile,
    get_judge_prompt,
    get_rag_template,
    get_direct_template,
    get_no_context_template
)

# 加载环境变量
load_dotenv()

# 定义知识库根目录
KNOWLEDGE_BASE_DIR = Path("KnowledgeBase")
os.makedirs(KNOWLEDGE_BASE_DIR, exist_ok=True)

# 初始化KNOWLEDGE_BASES为空
KNOWLEDGE_BASES = {}


# 持久化 KNOWLEDGE_BASES 到磁盘
def save_knowledge_bases():
    """将 KNOWLEDGE_BASES 保存到 JSON 文件"""
    try:
        config_file = KNOWLEDGE_BASE_DIR / "knowledge_bases.json"
        with open(config_file, "w", encoding="utf-8") as f:
            json.dump(KNOWLEDGE_BASES, f, ensure_ascii=False, indent=2)
        print(f"KNOWLEDGE_BASES 已保存到 {config_file}")
    except Exception as e:
        print(f"保存 KNOWLEDGE_BASES 失败: {str(e)}")


## jsonl to 知识库

def parse_jsonl_to_langchain_documents(jsonl_content: str) -> List[Document]:
    """
    将JSONL内容转换为LangChain Document对象

    Args:
        jsonl_content: JSONL格式字符串

    Returns:
        LangChain Document对象列表
    """
    documents = []

    try:
        for line_num, line in enumerate(jsonl_content.strip().split('\n'), 1):
            if not line.strip():
                continue

            try:
                chunk_data = json.loads(line)

                # 构造 LangChain Document对象
                doc = Document(
                    page_content=chunk_data.get('content', ''),
                    metadata={
                        'chunk_id': chunk_data.get('id'),
                        'source': chunk_data.get('metadata', {}).get('source_filename', ''),
                        'intro': chunk_data.get('metadata', {}).get('intro', ''),
                        'section': chunk_data.get('metadata', {}).get('section'),
                        'file_path': chunk_data.get('metadata', {}).get('source_file', ''),
                    }
                )

                # 移除None值
                doc.metadata = {k: v for k, v in doc.metadata.items() if v is not None}

                documents.append(doc)

            except json.JSONDecodeError as e:
                logger.warning(f"第 {line_num} 行JSON解析失败: {str(e)}")
                continue

        logger.info(f"成功解析 {len(documents)} 个文档块")
        return documents

    except Exception as e:
        logger.error(f"文档解析失败: {str(e)}")
        raise ValueError(f"JSONL格式错误: {str(e)}")


def create_kb_from_jsonl(
        file_path: str,
        kb_name: str,
        description: str = "",
        encoding: str = "utf-8"
) -> Dict[str, Any]:
    """
    从JSONL文件创建知识库(一步到位)

    Args:
        file_path: JSONL文件路径
        kb_name: 知识库名称
        description: 知识库描述(可选)
        encoding: 文件编码,默认utf-8

    Returns:
        创建结果字典,包含:
        - success: 是否成功
        - kb_name: 知识库名称
        - message: 结果消息
        - statistics: 统计信息
        - error: 错误信息(如果失败)

    Example:
        >>> result = create_kb_from_jsonl(
        ...     file_path="退役军人一件事答疑解惑_chunks.jsonl",
        ...     kb_name="veteran_service",
        ...     description="退役军人服务一件事政策问答知识库"
        ... )
        >>> print(result)
        {
            'success': True,
            'kb_name': 'veteran_service',
            'message': '成功创建知识库并添加 50 个文档',
            'statistics': {...}
        }
    """
    try:
        # 1. 验证文件存在
        file_path_obj = Path(file_path)
        if not file_path_obj.exists():
            raise FileNotFoundError(f"文件不存在: {file_path}")

        if not file_path_obj.suffix.lower() in ['.jsonl', '.json']:
            raise ValueError(f"不支持的文件格式: {file_path_obj.suffix}, 仅支持.jsonl或.json")

        logger.info(f"开始从文件创建知识库: {file_path}")
        logger.info(f"知识库名称: {kb_name}")

        # 2. 读取JSONL文件
        with open(file_path, 'r', encoding=encoding) as f:
            jsonl_content = f.read()

        logger.info(f"成功读取文件,大小: {len(jsonl_content)} 字节")

        # 3. 解析为LangChain Documents
        documents = parse_jsonl_to_langchain_documents(jsonl_content)

        if not documents:
            raise ValueError("未能从文件中解析出任何有效文档")

        logger.info(f"成功解析 {len(documents)} 个文档块")

        # 4. 检查知识库是否已存在
        if kb_name in KNOWLEDGE_BASES:
            logger.warning(f"知识库 '{kb_name}' 已存在,将删除并重新创建")
            delete_knowledge_base(kb_name)

        # 5. 创建知识库并添加文档
        result = create_kb_from_documents(
            kb_name=kb_name,
            documents=documents,
            description=description or f"从 {file_path_obj.name} 创建的知识库"
        )

        if result['success']:
            logger.info(f"✓ 知识库创建成功: {kb_name}")
            logger.info(f"  - 文档数量: {len(documents)}")
            logger.info(f"  - 描述: {description}")

            # 添加文件路径到元数据
            KNOWLEDGE_BASES[kb_name]['source_file'] = str(file_path_obj.absolute())
            save_knowledge_bases()

        return result

    except FileNotFoundError as e:
        error_msg = f"文件未找到: {str(e)}"
        logger.error(error_msg)
        return {
            'success': False,
            'kb_name': kb_name,
            'error': error_msg
        }

    except ValueError as e:
        error_msg = f"数据格式错误: {str(e)}"
        logger.error(error_msg)
        return {
            'success': False,
            'kb_name': kb_name,
            'error': error_msg
        }

    except Exception as e:
        error_msg = f"创建知识库失败: {str(e)}"
        logger.error(error_msg)
        logger.exception("详细错误信息:")

        # 清理可能创建的知识库
        try:
            if kb_name in KNOWLEDGE_BASES:
                delete_knowledge_base(kb_name)
                logger.info(f"已清理失败的知识库: {kb_name}")
        except:
            pass

        return {
            'success': False,
            'kb_name': kb_name,
            'error': error_msg
        }


# 文档解析
def parse_jsonl_to_langchain_documents(jsonl_content: str) -> List[Document]:
    """
    将JSONL内容转换为LangChain Document对象
    (这是业务逻辑层的数据转换,放在views.py)

    Args:
        jsonl_content: JSONL格式字符串

    Returns:
        LangChain Document对象列表
    """
    documents = []

    try:
        for line in jsonl_content.strip().split('\n'):
            if not line.strip():
                continue

            chunk_data = json.loads(line)

            # 构造LangChain Document对象
            doc = Document(
                page_content=chunk_data.get('content', ''),
                metadata={
                    'chunk_id': chunk_data.get('id'),
                    'source': chunk_data.get('metadata', {}).get('source_filename', ''),
                    'intro': chunk_data.get('metadata', {}).get('intro', ''),
                    'section': chunk_data.get('metadata', {}).get('section'),
                    'file_path': chunk_data.get('metadata', {}).get('source_file', ''),
                }
            )

            # 移除None值
            doc.metadata = {k: v for k, v in doc.metadata.items() if v is not None}

            documents.append(doc)

        logger.info(f"成功解析 {len(documents)} 个文档块")
        return documents

    except json.JSONDecodeError as e:
        logger.error(f"JSONL解析失败: {str(e)}")
        raise ValueError(f"JSONL格式错误: {str(e)}")
    except Exception as e:
        logger.error(f"文档解析失败: {str(e)}")
        raise


# 从磁盘加载 KNOWLEDGE_BASES
def load_knowledge_bases():
    """从 JSON 文件加载 KNOWLEDGE_BASES"""
    global KNOWLEDGE_BASES
    config_file = KNOWLEDGE_BASE_DIR / "knowledge_bases.json"
    try:
        if os.path.exists(config_file):
            with open(config_file, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content:  # 检查文件是否为空
                    KNOWLEDGE_BASES = json.loads(content)
                    print(f"从 {config_file} 加载 KNOWLEDGE_BASES: {list(KNOWLEDGE_BASES.keys())}")
                else:
                    print(f"配置文件 {config_file} 为空,初始化 KNOWLEDGE_BASES 为空")
                    KNOWLEDGE_BASES = {}
        else:
            print(f"未找到配置文件 {config_file},初始化 KNOWLEDGE_BASES 为空")
            KNOWLEDGE_BASES = {}
    except json.JSONDecodeError as e:
        print(f"加载 KNOWLEDGE_BASES 失败,JSON 格式错误: {str(e)}")
        KNOWLEDGE_BASES = {}
    except Exception as e:
        print(f"加载 KNOWLEDGE_BASES 失败: {str(e)}")
        KNOWLEDGE_BASES = {}


# 配置
RELEVANCE_THRESHOLD = 0.5
BGE_MODEL_NAME = r"G:\models\bge-large-zh"
RERANKER_MODEL_NAME = r"G:\models\bge-reranker-large"

# 初始化embedding和cross_encoder
embedding_generator = HuggingFaceEmbeddings(
    model_name=BGE_MODEL_NAME,
    model_kwargs={'device': 'cuda'},
    encode_kwargs={'normalize_embeddings': True}
)
cross_encoder = CrossEncoderWrapper(model_path=RERANKER_MODEL_NAME)

# 在程序启动时加载 KNOWLEDGE_BASES
load_knowledge_bases()

# 缓存检索器
retriever_cache: Dict[str, HybridLCRetriever] = {}

# 模型配置
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
    # "ERNIE-Speed": {
    #     "class": QianfanChatEndpoint,
    #     "init_params": {
    #         "model": "ERNIE-Speed-128K",  # 或 "ERNIE-Speed-8K"
    #         "qianfan_ak": "your_api_key",  # 你的 API Key
    #         "qianfan_sk": "your_secret_key",  # 你的 Secret Key
    #     }
    # }

}


def create_chat_model(model_name: str, temperature: float = 0.5,
                      max_tokens: int = 4096, streaming: bool = True):
    """创建chat模型实例"""
    if model_name not in MODEL_CONFIGS:
        raise ValueError(f"模型 '{model_name}' 不支持")
    config = MODEL_CONFIGS[model_name]
    model_class: Type = config["class"]
    init_params = config["init_params"].copy()
    init_params["temperature"] = temperature
    init_params["max_tokens"] = max_tokens
    init_params["streaming"] = streaming
    return model_class(**init_params)


# 请求模型定义
class Message(BaseModel):
    role: str = Field(..., description="角色: user 或 assistant")
    content: str = Field(..., description="消息内容")


class QARequest(BaseModel):
    question: str = Field(..., description="用户问题", min_length=1)
    kb_name: str = Field(default="school_policy", description="知识库名称")
    model_name: str = Field(default="gpt-3.5-proxy", description="模型名称")
    temperature: float = Field(default=0.5, ge=0.0, le=2.0, description="温度参数")
    max_tokens: int = Field(default=4096, ge=1, le=32000, description="最大token数")
    history: Optional[List[Message]] = Field(default=None, description="对话历史")
    # 新增用户画像参数
    age: Optional[int] = Field(default=None, description="用户年龄")
    is_employee: Optional[bool] = Field(default=None, description="是否是内部员工: True (员工) 或 False (对公)")
    frequency: Optional[str] = Field(default=None, description="使用频率: new/active/senior")
    # 新增 QA 模式开关
    is_strict: bool = Field(default=False, description="QA模式: False (允许直接对话和知识库内回答) 或 True (仅回答知识库内问题，其余拒绝)")


# 检索相关函数
def get_retriever(kb_name: str) -> HybridLCRetriever:
    """获取检索器(带缓存)"""
    if kb_name in retriever_cache:
        return retriever_cache[kb_name]
    if kb_name not in KNOWLEDGE_BASES:
        raise ValueError(f"知识库 '{kb_name}' 不存在")
    config = KNOWLEDGE_BASES[kb_name]
    chroma_store = Chroma(
        collection_name=config["collection_name"],
        embedding_function=embedding_generator,
        persist_directory=config["chroma_dir"]
    )
    bm25_indexer = BM25Indexer(store_dir=config["bm25_dir"])
    if not bm25_indexer.try_load():
        # 如果BM25索引不存在,创建一个空的
        bm25_indexer.save()
    hybrid_retriever = HybridRetriever(
        vectorstore=chroma_store,
        bm25_indexer=bm25_indexer,
        cross_encoder=cross_encoder,
        embeddings=embedding_generator,
        m_for_rerank=80,
        top_k=5,
    )
    retriever = HybridLCRetriever(hybrid_retriever)
    retriever_cache[kb_name] = retriever
    return retriever


def is_retrieval_relevant(docs: List[Document], fusion_threshold: float = RELEVANCE_THRESHOLD) -> bool:
    """判断检索结果相关性"""
    if not docs:
        return False
    top_doc = docs[0]
    fusion_score = top_doc.metadata.get('_s_fused', 0)
    return fusion_score >= fusion_threshold


def format_docs(docs: List[Document]) -> str:
    """格式化文档"""
    formatted = []
    for i, doc in enumerate(docs, 1):
        score_fused = doc.metadata.get('_s_fused', 0)
        score_ce = doc.metadata.get('_s_ce_norm', 0)
        formatted.append(
            f"[文档{i}] (融合分:{score_fused:.3f}, 重排分:{score_ce:.3f})\n"
            f"内容: {doc.page_content}\n"
        )
    return "\n".join(formatted)


def check_if_kb_specific(question: str, kb_name: str, model_name: str, temperature: float, max_tokens: int) -> bool:
    """使用LLM判断问题类型"""
    kb_description = KNOWLEDGE_BASES.get(kb_name, {}).get("description", "特定领域的专业知识")
    judge_prompt = get_judge_prompt(kb_description, question)
    try:
        chat_judge = create_chat_model(model_name, temperature, max_tokens, streaming=False)
        response = chat_judge.invoke(judge_prompt)
        result = response.content.strip().upper()
        if "YES" in result:
            return True
        elif "NO" in result:
            return False
        return True  # 保守策略
    except Exception as e:
        print(f"LLM判断失败: {e},使用关键词回退")
        return fallback_keyword_check(question)


def fallback_keyword_check(question: str) -> bool:
    """关键词回退策略"""
    general_patterns = ["你好", "您好", "hi", "hello", "介绍", "什么是"]
    kb_keywords = ["政策", "招生", "报名", "入学", "材料", "流程"]
    question_lower = question.lower()
    for pattern in general_patterns:
        if pattern in question_lower or pattern in question:
            return False
    for keyword in kb_keywords:
        if keyword in question:
            return True
    return len(question) >= 10


def format_history(history: Optional[List[Message]]) -> str:
    """格式化对话历史"""
    if not history or len(history) == 0:
        return ""
    history_text = "对话历史:\n"
    for msg in history:
        role_name = "用户" if msg.role == "user" else "助手"
        history_text += f"{role_name}: {msg.content}\n"
    return history_text + "\n"


# 核心问答函数(流式输出,支持历史)
def smart_qa_stream(question: str, kb_name: str, model_name: str,
                    temperature: float, max_tokens: int,
                    history: Optional[List[Message]] = None,
                    age: Optional[int] = None,
                    is_employee: Optional[bool] = None,
                    frequency: Optional[str] = None,
                    is_strict: bool = True):
    """流式问答生成器(支持对话历史、用户画像和QA模式)"""
    try:
        # 获取用户画像
        profile = categorize_user_profile(age, is_employee, frequency)

        chat_streaming = create_chat_model(model_name, temperature, max_tokens, streaming=True)
        history_context = format_history(history)
        is_kb_specific = check_if_kb_specific(question, kb_name, model_name, temperature, max_tokens)
        if is_strict:
            # 第二种情况: 仅知识库内问题回答，其余拒绝
            if is_kb_specific:
                retriever = get_retriever(kb_name)
                retrieved_docs = retriever.invoke(question)
                if is_retrieval_relevant(retrieved_docs):
                    context = format_docs(retrieved_docs)
                    template = get_rag_template(profile)
                    prompt = ChatPromptTemplate.from_template(template)
                    chain = prompt | chat_streaming | StrOutputParser()
                    for chunk in chain.stream(
                            {"context": context, "question": question, "history_context": history_context}):
                        yield chunk
                else:
                    # 拒答
                    template = get_no_context_template(profile)
                    prompt = ChatPromptTemplate.from_template(template)
                    chain = prompt | chat_streaming | StrOutputParser()
                    for chunk in chain.stream({"question": question, "history_context": history_context}):
                        yield chunk
            else:
                # 非知识库内，直接拒答
                template = get_no_context_template(profile)
                prompt = ChatPromptTemplate.from_template(template)
                chain = prompt | chat_streaming | StrOutputParser()
                for chunk in chain.stream({"question": question, "history_context": history_context}):
                    yield chunk
        else:  # flexible (第一种情况，原逻辑)
            if not is_kb_specific:
                template = get_direct_template(profile)
                prompt = ChatPromptTemplate.from_template(template)
                chain = prompt | chat_streaming | StrOutputParser()
                for chunk in chain.stream({"question": question, "history_context": history_context}):
                    yield chunk
            else:
                retriever = get_retriever(kb_name)
                retrieved_docs = retriever.invoke(question)
                if is_retrieval_relevant(retrieved_docs):
                    context = format_docs(retrieved_docs)
                    template = get_rag_template(profile)
                    prompt = ChatPromptTemplate.from_template(template)
                    chain = prompt | chat_streaming | StrOutputParser()
                    for chunk in chain.stream(
                            {"context": context, "question": question, "history_context": history_context}):
                        yield chunk
                else:
                    template = get_no_context_template(profile)
                    prompt = ChatPromptTemplate.from_template(template)
                    chain = prompt | chat_streaming | StrOutputParser()
                    for chunk in chain.stream({"question": question, "history_context": history_context}):
                        yield chunk
    except Exception as e:
        yield f"错误: {str(e)}"


# 知识库存取管理接口
def load_file_to_docs(file_path: str):
    """根据文件类型加载文档"""
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".docx":
        loader = Docx2txtLoader(file_path)
    elif ext == ".pdf":
        loader = PyPDFLoader(file_path)
    elif ext in [".txt", ".md"]:
        loader = TextLoader(file_path, encoding="utf-8")
    else:
        raise ValueError(f"不支持的文件类型: {ext}")
    docs = loader.load()
    splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=100)
    split_docs = splitter.split_documents(docs)
    for d in split_docs:
        d.metadata["source"] = os.path.basename(file_path)
        d.metadata["file_path"] = os.path.abspath(file_path)
    return split_docs


def get_chroma_store(kb_name: str) -> Chroma:
    """获取或创建Chroma知识库"""
    if kb_name not in KNOWLEDGE_BASES:
        raise ValueError(f"知识库 '{kb_name}' 不存在")
    config = KNOWLEDGE_BASES[kb_name]
    return Chroma(
        collection_name=config["collection_name"],
        embedding_function=embedding_generator,
        persist_directory=config["chroma_dir"]
    )


def create_knowledge_base(kb_name: str, description: str = "", file_path: Optional[str] = None):
    """创建新的知识库(支持可选的文件路径)"""
    try:
        if kb_name in KNOWLEDGE_BASES:
            raise ValueError(f"知识库 '{kb_name}' 已存在")
        collection_name = f"hybrid_rag_{kb_name}"
        chroma_dir = str(KNOWLEDGE_BASE_DIR / kb_name / "chroma")
        bm25_dir = str(KNOWLEDGE_BASE_DIR / kb_name / "bm25")
        os.makedirs(chroma_dir, exist_ok=True)
        os.makedirs(bm25_dir, exist_ok=True)
        chroma_store = Chroma(
            collection_name=collection_name,
            embedding_function=embedding_generator,
            persist_directory=chroma_dir
        )
        bm25_indexer = BM25Indexer(store_dir=bm25_dir)
        bm25_indexer.save()
        KNOWLEDGE_BASES[kb_name] = {
            "collection_name": collection_name,
            "chroma_dir": chroma_dir,
            "bm25_dir": bm25_dir,
            "description": description,
            "file_path": None
        }
        print(f"成功创建知识库 [{kb_name}],描述: {description}")
        if file_path:
            add_file_to_kb(kb_name, file_path)
            KNOWLEDGE_BASES[kb_name]["file_path"] = file_path
        save_knowledge_bases()  # 保存 KNOWLEDGE_BASES
    except Exception as e:
        print(f"创建知识库失败: {e}")
        raise


def delete_knowledge_base(kb_name: str):
    """删除指定知识库,包括Chroma向量库和BM25索引"""
    try:
        if kb_name not in KNOWLEDGE_BASES:
            raise ValueError(f"知识库 '{kb_name}' 不存在")
        config = KNOWLEDGE_BASES[kb_name]
        chroma_store = Chroma(
            collection_name=config["collection_name"],
            embedding_function=embedding_generator,
            persist_directory=config["chroma_dir"]
        )
        chroma_store._collection.delete()
        print(f"已删除知识库 [{kb_name}] 的Chroma向量数据")
        if os.path.exists(config["chroma_dir"]):
            shutil.rmtree(config["chroma_dir"])
            print(f"已删除知识库 [{kb_name}] 的Chroma目录: {config['chroma_dir']}")
        if os.path.exists(config["bm25_dir"]):
            shutil.rmtree(config["bm25_dir"])
            print(f"已删除知识库 [{kb_name}] 的BM25索引目录: {config['bm25_dir']}")
        del KNOWLEDGE_BASES[kb_name]
        if kb_name in retriever_cache:
            del retriever_cache[kb_name]
        print(f"成功删除知识库 [{kb_name}]")
        save_knowledge_bases()  # 保存 KNOWLEDGE_BASES
    except Exception as e:
        print(f"删除知识库失败: {e}")
        raise


def add_file_to_kb(kb_name: str, file_path: str):
    """将文件添加到知识库"""
    try:
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"文件 {file_path} 不存在")
        print(f"开始将文件 [{file_path}] 添加到知识库 [{kb_name}]...")
        store = get_chroma_store(kb_name)
        docs = load_file_to_docs(file_path)
        store.add_documents(docs)
        bm25_indexer = BM25Indexer(store_dir=KNOWLEDGE_BASES[kb_name]["bm25_dir"])
        # 如果已有BM25索引,加载现有文档并追加
        if bm25_indexer.try_load():
            existing_docs = [bm25_indexer.id_to_document(doc_id) for doc_id in bm25_indexer._doc_ids]
            docs = existing_docs + docs  # 合并现有文档和新文档
        bm25_indexer.fit(docs)  # 使用fit方法重建索引
        bm25_indexer.save()
        # 更新KNOWLEDGE_BASES中的file_path
        KNOWLEDGE_BASES[kb_name]["file_path"] = file_path
        print(f"成功添加 {len(docs)} 个文档分块到知识库 [{kb_name}]。")
        save_knowledge_bases()  # 保存 KNOWLEDGE_BASES
    except Exception as e:
        print(f"添加文件失败: {e}")
        raise


def list_kb_files(kb_name: str):
    """列出知识库内所有文件"""
    try:
        store = get_chroma_store(kb_name)
        all_docs = store._collection.get(include=["metadatas"])
        sources = set()
        for m in all_docs["metadatas"]:
            if m and "source" in m:
                sources.add(m["source"])
        return list(sources)
    except Exception as e:
        print(f"获取文件列表失败: {e}")
        return []


def delete_file_from_kb(kb_name: str, file_name: str):
    """删除知识库中的指定文件"""
    try:
        store = get_chroma_store(kb_name)
        all_docs = store._collection.get(include=["ids", "metadatas"])
        delete_ids = [
            i for i, meta in zip(all_docs["ids"], all_docs["metadatas"])
            if meta and meta.get("source") == file_name
        ]
        if not delete_ids:
            print(f"未找到文件: {file_name}")
            return
        store._collection.delete(ids=delete_ids)
        bm25_indexer = BM25Indexer(store_dir=KNOWLEDGE_BASES[kb_name]["bm25_dir"])
        if bm25_indexer.try_load():
            remaining_docs = [bm25_indexer.id_to_document(doc_id) for doc_id in bm25_indexer._doc_ids
                              if bm25_indexer._doc_map[doc_id]["meta"].get("source") != file_name]
            if remaining_docs:
                bm25_indexer.fit(remaining_docs)
            else:
                bm25_indexer._bm25 = None
                bm25_indexer._doc_ids = []
                bm25_indexer._doc_map = {}
                bm25_indexer._corpus_tokens = []
            bm25_indexer.save()
        # 如果删除了文件,更新file_path为None(如果这是唯一文件)
        if not list_kb_files(kb_name):
            KNOWLEDGE_BASES[kb_name]["file_path"] = None
        print(f"已删除文件 [{file_name}] 的 {len(delete_ids)} 条向量。")
        save_knowledge_bases()
    except Exception as e:
        print(f"删除文件失败: {e}")


def list_all_knowledge_bases() -> List[Dict[str, str]]:
    """列出所有知识库及其描述"""
    try:
        return [
            {"name": name, "description": config.get("description", "")}
            for name, config in KNOWLEDGE_BASES.items()
        ]
    except Exception as e:
        print(f"获取知识库列表失败: {e}")
        return []


# FastAPI 应用初始化
app = FastAPI(title="RAG问答服务", version="1.0.0")


@app.on_event("startup")
async def startup_event():
    """应用启动时的初始化操作"""
    print("=" * 60)
    print("FastAPI RAG问答服务启动中...")
    print(f"当前工作目录: {os.getcwd()}")
    print(f"知识库根目录: {KNOWLEDGE_BASE_DIR.absolute()}")
    print(f"正在加载知识库配置...")
    load_knowledge_bases()
    print(f"加载完成后 KNOWLEDGE_BASES 内容: {KNOWLEDGE_BASES}")  # 添加这行
    print(f"可用模型: {list(MODEL_CONFIGS.keys())}")
    print(f"可用知识库: {list(KNOWLEDGE_BASES.keys())}")
    print("=" * 60)


# API端点
@app.post("/qa")
def question_answer(request: QARequest):
    load_knowledge_bases()
    """流式问答接口(支持对话历史)"""
    try:
        print("开始生成流式响应...")
        return StreamingResponse(
            smart_qa_stream(
                request.question,
                request.kb_name,
                request.model_name,
                request.temperature,
                request.max_tokens,
                request.history,
                request.age,
                request.is_employee,
                request.frequency,
                request.is_strict  # 新增
            ),
            media_type="text/plain; charset=utf-8"
        )
    except HTTPException as he:
        print(f"HTTP异常: {he.detail}")
        raise he
    except Exception as e:
        import traceback
        print(f"问答处理失败: {str(e)}")
        print(f"完整错误信息:\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
def health_check():
    """健康检查接口"""
    return {
        "status": "ok",
        "available_models": list(MODEL_CONFIGS.keys()),
        "available_knowledge_bases": list(KNOWLEDGE_BASES.keys())
    }


@app.get("/knowledge_bases")
def get_all_knowledge_bases():
    load_knowledge_bases()
    """列出所有知识库及其描述"""
    try:
        kb_list = list_all_knowledge_bases()
        return {"knowledge_bases": kb_list}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取知识库列表失败: {str(e)}")


@app.delete("/knowledge_bases/{kb_name}")
def delete_knowledge_base_endpoint(kb_name: str):
    """删除指定知识库"""
    try:
        delete_knowledge_base(kb_name)
        return {"message": f"知识库 '{kb_name}' 已成功删除"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"删除知识库失败: {str(e)}")


@app.post("/knowledge_bases")
def create_knowledge_base_endpoint(kb_name: str, description: str = "", file_path: Optional[str] = None):
    """创建新的知识库"""
    try:
        create_knowledge_base(kb_name, description, file_path)
        return {"message": f"知识库 '{kb_name}' 已成功创建", "description": description}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"创建知识库失败: {str(e)}")


@app.post("/knowledge_bases/{kb_name}/files")
def add_file_to_knowledge_base(kb_name: str, file_path: str):
    """向知识库添加文件"""
    try:
        add_file_to_kb(kb_name, file_path)
        return {"message": f"文件 '{file_path}' 已成功添加到知识库 '{kb_name}'"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"添加文件失败: {str(e)}")


@app.get("/knowledge_bases/{kb_name}/files")
def list_knowledge_base_files(kb_name: str):
    """列出知识库中的所有文件"""
    try:
        files = list_kb_files(kb_name)
        return {"kb_name": kb_name, "files": files}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取文件列表失败: {str(e)}")


@app.delete("/knowledge_bases/{kb_name}/files/{file_name}")
def delete_knowledge_base_file(kb_name: str, file_name: str):
    """从知识库中删除指定文件"""
    try:
        delete_file_from_kb(kb_name, file_name)
        return {"message": f"文件 '{file_name}' 已从知识库 '{kb_name}' 中删除"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"删除文件失败: {str(e)}")


# rag_api.py 中添加以下函数

def add_documents_batch(kb_name: str, documents: List[Document]) -> Dict[str, Any]:
    """
    批量添加文档到知识库(核心函数)
    直接操作Chroma和BM25索引

    Args:
        kb_name: 知识库名称
        documents: LangChain Document对象列表

    Returns:
        添加结果字典
    """
    try:
        if kb_name not in KNOWLEDGE_BASES:
            raise ValueError(f"知识库 '{kb_name}' 不存在")

        # 1. 添加到Chroma向量数据库
        chroma_store = get_chroma_store(kb_name)
        chroma_store.add_documents(documents)
        print(f"成功添加 {len(documents)} 个文档到Chroma数据库")

        # 2. 更新BM25索引
        bm25_dir = KNOWLEDGE_BASES[kb_name]["bm25_dir"]
        bm25_indexer = BM25Indexer(store_dir=bm25_dir)

        # 加载现有索引
        existing_docs = []
        if bm25_indexer.try_load():
            existing_docs = [
                bm25_indexer.id_to_document(doc_id)
                for doc_id in bm25_indexer._doc_ids
            ]

        # 合并并重建索引
        all_docs = existing_docs + documents
        bm25_indexer.fit(all_docs)
        bm25_indexer.save()
        print(f"成功更新BM25索引,当前共 {len(all_docs)} 个文档")

        # 3. 保存配置
        save_knowledge_bases()

        return {
            'success': True,
            'message': f'成功添加 {len(documents)} 个文档',
            'documents_added': len(documents),
            'total_documents': len(all_docs)
        }

    except Exception as e:
        print(f"添加文档失败: {str(e)}")
        return {
            'success': False,
            'error': str(e)
        }


def create_kb_from_documents(kb_name: str, documents: List[Document],
                             description: str = "") -> Dict[str, Any]:
    """
    从Document列表创建知识库(一步到位)

    Args:
        kb_name: 知识库名称
        documents: Document对象列表
        description: 知识库描述

    Returns:
        创建结果
    """
    try:
        # 1. 创建空知识库
        create_knowledge_base(kb_name, description, file_path=None)

        # 2. 批量添加文档
        result = add_documents_batch(kb_name, documents)

        if not result['success']:
            # 失败则删除知识库
            delete_knowledge_base(kb_name)
            raise Exception(result.get('error'))

        return {
            'success': True,
            'kb_name': kb_name,
            'message': f'成功创建知识库并添加 {len(documents)} 个文档',
            'statistics': result
        }

    except Exception as e:
        print(f"创建知识库失败: {str(e)}")
        return {
            'success': False,
            'error': str(e)
        }


# jsonl2kb
@app.post("/knowledge_bases/from_jsonl")
def create_kb_from_jsonl_endpoint(
        file_path: str,
        kb_name: str,
        description: str = "",
        encoding: str = "utf-8"
):
    """
    从JSONL文件创建知识库的API端点

    POST /knowledge_bases/from_jsonl
    {
        "file_path": "/path/to/file.jsonl",
        "kb_name": "my_knowledge_base",
        "description": "知识库描述",
        "encoding": "utf-8"
    }
    """
    try:
        result = create_kb_from_jsonl(
            file_path=file_path,
            kb_name=kb_name,
            description=description,
            encoding=encoding
        )

        if result['success']:
            return result
        else:
            raise HTTPException(
                status_code=400,
                detail=result.get('error', '创建知识库失败')
            )

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"服务器错误: {str(e)}"
        )


# 启动服务
if __name__ == "__main__":
    print("=" * 60)
    print("FastAPI RAG问答服务启动中...")
    print(f"可用模型: {list(MODEL_CONFIGS.keys())}")
    print(f"可用知识库: {list(KNOWLEDGE_BASES.keys())}")
    print("=" * 60)
    uvicorn.run(app, host="0.0.0.0", port=9800, log_level="info")