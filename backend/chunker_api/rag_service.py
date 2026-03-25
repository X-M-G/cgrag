import logging
import traceback
from typing import List, Dict, Any, Optional, Type
import os, sys

from utils.promt.prompt import build_answer_strategy, format_strategy_text

# 确保可以导入项目根目录下的 promt 与 hybrid_retrieval_fusion
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))
from django.conf import settings
from .llm_service import get_llm_service
from chromadb.config import Settings

logger = logging.getLogger(__name__)

# 引入混合检索与画像 Prompt（尽量复用现成实现）
try:
    from langchain_chroma import Chroma
    from langchain_core.documents import Document
    from dashscope import MultiModalEmbedding
    from http import HTTPStatus
    from hybrid_retrieval_fusion import (
        BM25Indexer,
        CrossEncoderWrapper,
        HybridRetriever,
        HybridLCRetriever,
    )
    from utils.promt.prompt import (
        get_judge_prompt,
        get_rag_template,
        get_direct_template,
        get_no_context_template,
    )
    HYBRID_AVAILABLE = True
except Exception as e:
    logger.warning(f"混合检索或Prompt模块不可用，将降级: {e}")
    HYBRID_AVAILABLE = False

class TongyiEmbeddings:
    def __init__(self, api_key: str, model_name: str = "tongyi-embedding-vision-plus"):
        self.api_key = api_key
        self.model_name = model_name

    def _encode(self, payload: list) -> list:
        resp = MultiModalEmbedding.call(model=self.model_name, input=payload, api_key=self.api_key)
        if resp.status_code == HTTPStatus.OK:
            return [item.get("embedding", []) for item in resp.output.get("embeddings", [])]
        raise RuntimeError(f"通义向量接口失败: {resp.code} - {resp.message}")

    def embed_query(self, text: str) -> list:
        if not text:
            return []
        res = self._encode([{"text": text}])
        return res[0] if res else []

    def embed_documents(self, texts: list) -> list:
        if not texts:
            return []
        payload = [{"text": t} for t in texts]
        return self._encode(payload)

class RAGService:
    """
    RAG (Retrieval-Augmented Generation) 服务类
    负责处理检索和生成的完整流程
    """
    
    def __init__(
        self, 
        api_key: str, 
        model_name: str = "qwen3-omni-flash",
        encoder_model: str = "tongyi-embedding-vision-plus",
        chroma_db_path: str = "./chroma_db"
    ):
        """
        初始化 RAG 服务
        
        Args:
            api_key: 通义千问 API Key
            model_name: 使用的 LLM 模型名称
            encoder_model: 使用的编码器模型名称
            chroma_db_path: ChromaDB 数据库路径
        """
        self.api_key = api_key
        self.model_name = model_name
        self.encoder_model = encoder_model
        self.chroma_db_path = chroma_db_path
        
        # 初始化 LLM 服务
        self.llm = get_llm_service(api_key=api_key, model_name=model_name)
        
        # 延迟初始化编码器（只在需要时初始化）
        self._encoder = None

        # 混合检索依赖（延迟）
        self._hf_embeddings = None
        self._cross_encoder = None
        self._retriever_cache: Dict[str, HybridLCRetriever] = {}

        # 配置：从 settings 读取，提供默认值
        # 注意：RRF 分数通常在 0~0.2 左右（取决于 rrf_k / 候选规模），0.5 会导致几乎永远判定为“不相关”
        self.RELEVANCE_THRESHOLD: float = getattr(settings, 'RAG_RELEVANCE_THRESHOLD', 0.06)
        # CrossEncoder（bge-reranker）输出通常在 0~1，默认阈值更稳妥
        self.CE_RELEVANCE_THRESHOLD: float = getattr(settings, 'RAG_CE_RELEVANCE_THRESHOLD', 0.2)

        # 优先使用 settings.RERANKER_MODEL_NAME（在 backend/settings.py 中从环境变量 RAG_RERANKER_MODEL_NAME 读取）
        # 兼容旧写法：settings.RAG_RERANKER_MODEL_NAME
        reranker_model = getattr(settings, 'RAG_RERANKER_MODEL_NAME', None)
        # 若是相对路径且在 BASE_DIR 下存在，则解析为绝对路径；否则保留原值（允许传入 HuggingFace repo_id）
        try:
            from pathlib import Path
            base_dir = Path(getattr(settings, 'BASE_DIR', Path.cwd()))
            candidate = base_dir / reranker_model
            if isinstance(reranker_model, str) and not Path(reranker_model).is_absolute() and candidate.exists():
                reranker_model = str(candidate)
        except Exception:
            pass
        self.RERANKER_MODEL_NAME: str = reranker_model
    
    @property
    def encoder(self):
        """延迟加载编码器"""
        if self._encoder is None:
            try:
                from MultimodalEncoder import MultimodalEncoder
                # 初始化时不指定 collection_name，因为会在查询时动态传入
                self._encoder = MultimodalEncoder(
                    api_key=self.api_key,
                    model=self.encoder_model,
                    chroma_db_path=self.chroma_db_path
                )
            except ImportError:
                logger.error("MultimodalEncoder 不可用")
                raise ImportError("MultimodalEncoder is not available")
        return self._encoder

    # =============== 混合检索：内部工具方法 ===============
    def _get_embeddings(self):
        if not HYBRID_AVAILABLE:
            raise RuntimeError("混合检索依赖不可用")
        if self._hf_embeddings is None:
            self._hf_embeddings = TongyiEmbeddings(
                api_key=self.api_key,
                model_name=self.encoder_model
            )
        return self._hf_embeddings

    def _get_cross_encoder(self):
        if not HYBRID_AVAILABLE:
            raise RuntimeError("混合检索依赖不可用")
        if self._cross_encoder is None:
            self._cross_encoder = CrossEncoderWrapper(model_path=self.RERANKER_MODEL_NAME)
        return self._cross_encoder

    def _get_chroma_for_collection(self, collection_name: str) -> 'Chroma':
        if not HYBRID_AVAILABLE:
            raise RuntimeError("混合检索依赖不可用")
        return Chroma(
            collection_name=collection_name,
            embedding_function=self._get_embeddings(),
            persist_directory=self.chroma_db_path,
            client_settings=Settings(
                is_persistent=True,
                anonymized_telemetry=False,
                allow_reset=True
            )
        )

    def _get_bm25_indexer_dir(self, collection_name: str) -> str:
        # 与 promt 方案一致：每个集合一个 bm25 子目录
        import os
        bm25_dir = os.path.join(self.chroma_db_path, 'bm25', collection_name)
        os.makedirs(bm25_dir, exist_ok=True)
        return bm25_dir

    def _ensure_bm25_index(self, collection_name: str) -> 'BM25Indexer':
        bm25 = BM25Indexer(store_dir=self._get_bm25_indexer_dir(collection_name))
        if bm25.try_load():
            return bm25
        # 从 Chroma 读取所有文档，重建 BM25
        store = self._get_chroma_for_collection(collection_name)
        try:
            raw = store._collection.get(include=["documents", "metadatas"])
            docs: List[Document] = []
            for doc_content, meta in zip(raw.get('documents', []) or [], raw.get('metadatas', []) or []):
                docs.append(Document(page_content=doc_content or "", metadata=meta or {}))
            if docs:
                bm25.fit(docs)
                bm25.save()
                logger.info(f"已为集合 {collection_name} 新建 BM25 索引，文档数: {len(docs)}")
            else:
                bm25.save()  # 空索引也保存，保持一致
        except Exception as e:
            logger.warning(f"构建 BM25 索引失败（将以语义检索为主）：{e}")
            bm25.save()
        return bm25

    def _get_hybrid_retriever(self, collection_name: str, top_k: int) -> 'HybridLCRetriever':
        cache_key = (collection_name, top_k)
        if cache_key in self._retriever_cache:
            return self._retriever_cache[cache_key]
        store = self._get_chroma_for_collection(collection_name)
        bm25 = self._ensure_bm25_index(collection_name)
        retriever = HybridLCRetriever(HybridRetriever(
            vectorstore=store,
            bm25_indexer=bm25,
            cross_encoder=self._get_cross_encoder(),
            embeddings=self._get_embeddings(),
            m_for_rerank=80,
            top_k=top_k,
        ))
        self._retriever_cache[cache_key] = retriever
        return retriever

    def _format_docs(self, docs: List['Document']) -> str:
        parts = []
        for i, d in enumerate(docs, 1):
            s_fused = float(d.metadata.get('_s_fused', d.metadata.get('_rrf_score', 0.0)) or 0)
            s_ce = float(d.metadata.get('_s_ce_norm', 0.0) or 0)
            parts.append(f"[文档{i}] (融合分:{s_fused:.3f}, 重排分:{s_ce:.3f})\n内容: {d.page_content}\n")
        return "\n".join(parts)

    def _is_retrieval_relevant(self, docs: List['Document']) -> bool:
        if not docs:
            return False
        max_fused = 0.0
        max_ce = 0.0
        has_ce_score = False
        for d in docs:
            meta = d.metadata or {}
            fused = float(meta.get('_s_fused', meta.get('_rrf_score', 0.0)) or 0.0)
            ce = float(meta.get('_s_ce', 0.0) or 0.0)
            if '_s_ce' in meta:
                has_ce_score = True
            if fused > max_fused:
                max_fused = fused
            if ce > max_ce:
                max_ce = ce

        # 优先使用 CrossEncoder 的绝对分数判断；缺失时回退到融合分（RRF）
        if has_ce_score:
            return max_ce >= self.CE_RELEVANCE_THRESHOLD
        return max_fused >= self.RELEVANCE_THRESHOLD

    # =============== 现有多模态检索保留 ===============
    def retrieve_context(
        self, 
        query: str, 
        collection_names: List[str],
        top_k: int = 5,
        modality_filter: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        从一个或多个向量数据库集合中检索相关上下文（多模态编码器路径）。
        保留原实现。
        """
        all_results = []
        if not collection_names:
            logger.warning("没有提供要查询的集合")
            return []

        logger.info(f"正在从 {len(collection_names)} 个集合中检索问题: {query}")

        for name in collection_names:
            try:
                # 动态设置当前查询的集合
                self.encoder.set_collection(name)
                
                search_results = self.encoder.query(
                    query_text=query,
                    n_results=top_k,
                    modality_filter=modality_filter
                )
                if search_results:
                    all_results.extend(search_results)
            except Exception as e:
                # 如果集合不存在或查询失败，记录日志并继续
                logger.error(f"检索集合 '{name}' 失败: {e}")
                continue
        
        # 根据距离（distance）对所有结果进行排序，越小越好
        all_results.sort(key=lambda x: x.get('distance', float('inf')))
        
        # 返回最终的 top_k 个结果
        return all_results[:top_k]

    # =============== 新增：混合检索 + 用户画像模板 生成 ===============
    def _format_history(self, history: Optional[List[Dict[str, str]]]) -> str:
        if not history:
            return ""
        out = ["对话历史:"]
        for m in history:
            role = m.get('role', 'user')
            content = m.get('content', '')
            role_name = '用户' if role == 'user' else '助手'
            out.append(f"{role_name}:{content}")
        return "\n".join(out) + "\n\n"

    def _judge_need_kb(self, question: str, kb_desc: str) -> bool:
        try:
            if not HYBRID_AVAILABLE:
                return True
            prompt = get_judge_prompt(kb_desc, question)
            resp = self.llm.generate_answer(prompt, system_prompt="你是一个问题分类专家")
            txt = (resp or "").strip().upper()
            if "YES" in txt:
                return True
            if "NO" in txt:
                return False
            return True
        except Exception as e:
            logger.warning(f"判定是否需要知识库失败，回退关键词: {e}")
            patterns = ["你好", "您好", "hi", "hello", "介绍", "什么是"]
            kb_keywords = ["政策", "招生", "报名", "入学", "材料", "流程"]
            ql = question.lower()
            if any(p in ql or p in question for p in patterns):
                return False
            if any(k in question for k in kb_keywords):
                return True
            return len(question) >= 10

    def smart_answer_hybrid(
            self,
            question: str,
            collection_names: List[str],
            *,
            top_k: int = 10,
            debug: bool = False,
            history: Optional[List[Dict[str, str]]] = None,
            age_group: Optional[str] = None,
            role: Optional[str] = None,
            frequency: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        使用混合检索与画像驱动的模板生成答案。
        返回 { answer, docs, used_template }
        """
        if not HYBRID_AVAILABLE:
            raise RuntimeError("混合检索能力未就绪，请检查依赖与本地模型路径")
        if not collection_names:
            return {"answer": "未提供可用的知识库集合", "docs": []}

        # 聚合知识库描述（这里简化为集合名）
        kb_desc = ", ".join(collection_names)
        need_kb = self._judge_need_kb(question, kb_desc)

        # 3. 构造最新的用户画像策略 (核心逻辑)
        strategy = build_answer_strategy(
            role=role or "external",
            age_group=age_group or "youth",
            frequency=frequency or "normal"
        )
        print('strategy', strategy)
        strategy_text = format_strategy_text(strategy)
        print('strategy_text', strategy_text)

        # 4. 格式化上下文
        history_context = ""
        if history:
            h_lines = [f"{'用户' if m['role'] == 'user' else '助手'}: {m['content']}" for m in history]
            history_context = "【对话上下文】\n" + "\n".join(h_lines)
        history_ctx = self._format_history(history)

        chosen_docs: List[Document] = []
        context_str = ""
        used_template = "direct"

        debug_info: Dict[str, Any] = {}
        # if not is_strict and not need_kb:
        #     template = get_direct_template(profile)
        #     user_prompt = template.format(question=question, history_context=history_ctx)
        #     answer = self.llm.generate_answer(user_prompt, system_prompt="你是一个友好、专业的AI助手")
        #     if debug:
        #         debug_info = {
        #             "need_kb": need_kb,
        #             "is_strict": is_strict,
        #             "collections": collection_names,
        #             "docs_retrieved": 0,
        #             "rrf_threshold": self.RELEVANCE_THRESHOLD,
        #             "ce_threshold": self.CE_RELEVANCE_THRESHOLD,
        #             "used_template": used_template,
        #         }
        #     resp = {"answer": answer, "docs": [], "used_template": used_template}
        #     if debug:
        #         resp["debug"] = debug_info
        #     return resp

        # 需要走检索
        for name in collection_names:
            try:
                retriever = self._get_hybrid_retriever(name, top_k)
                docs = retriever.invoke(question)
                if docs:
                    chosen_docs.extend(docs)
            except Exception as e:
                logger.error(traceback.format_exc())
                logger.error(f"集合 {name} 检索失败: {e}")
                continue

        # 选前 top_k（跨知识库重排后截断）
        def _safe_float(v: Any, default: float = 0.0) -> float:
            try:
                return float(v)
            except (TypeError, ValueError):
                return default

        def _rank_key(d: Document) -> tuple[float, float, float, float]:
            meta = d.metadata or {}
            ce_raw = meta.get("_s_ce")
            ce_norm = _safe_float(meta.get("_s_ce_norm"), 0.0)
            ce_score = _safe_float(ce_raw, float("-inf")) if ce_raw is not None else float("-inf")
            primary = ce_score if ce_raw is not None else ce_norm
            fused = _safe_float(meta.get("_s_fused", meta.get("_rrf_score", 0.0)), 0.0)
            mmr = _safe_float(meta.get("_mmr_score", 0.0), 0.0)
            return (primary, fused, mmr, ce_norm)

        chosen_docs.sort(key=_rank_key, reverse=True)
        chosen_docs = chosen_docs[:top_k]
        
        print(f"[RAG][HYBRID] docs_after_retrieve={len(chosen_docs)}")
        for rank, d in enumerate(chosen_docs, 1):
            meta = d.metadata or {}
            file_name = meta.get("file_name") or meta.get("source") or meta.get("source_file") or "unknown"
            print(
                f"[RAG][HYBRID][DOC] #{rank} file={file_name} chunk={meta.get('chunk_id')} "
                f"rrf={meta.get('_rrf_score')} ce={meta.get('_s_ce')} ce_norm={meta.get('_s_ce_norm')} mmr={meta.get('_mmr_score')}"
            )
        
        # 基于相关文本的来源文件补充图片
        image_results: List[Dict[str, Any]] = []
        source_files = list({
            d.metadata.get('file_name')
            for d in chosen_docs
            if d.metadata.get('file_name')
        })
        if source_files:
            for name in collection_names:
                try:
                    self.encoder.set_collection(name)
                    final_where = {
                        "$and": [
                            {"file_name": {"$in": source_files}},
                            {"modality_type": "image"}
                        ]
                    }
                    imgs = self.encoder.query(
                        query_text=question,
                        n_results=min(3, top_k),
                        where=final_where
                    ) or []
                    image_results.extend(imgs)
                except Exception as e:
                    logger.error(f"图片检索集合 '{name}' 失败: {e}")
                    continue
            image_results.sort(key=lambda x: x.get('distance', float('inf')))
            image_results = image_results[:min(3, top_k)]
        is_relevant = self._is_retrieval_relevant(chosen_docs)
        if debug:
            max_fused = 0.0
            max_ce = 0.0
            for d in chosen_docs:
                meta = d.metadata or {}
                fused = float(meta.get('_s_fused', meta.get('_rrf_score', 0.0)) or 0.0)
                ce = float(meta.get('_s_ce', 0.0) or 0.0)
                if fused > max_fused:
                    max_fused = fused
                if ce > max_ce:
                    max_ce = ce
            debug_info = {
                "need_kb": need_kb,
                # "is_strict": is_strict,
                "collections": collection_names,
                "docs_retrieved": len(chosen_docs),
                "max_rrf": max_fused,
                "max_ce": max_ce,
                "rrf_threshold": self.RELEVANCE_THRESHOLD,
                "ce_threshold": self.CE_RELEVANCE_THRESHOLD,
                "is_relevant": is_relevant,
            }
        if is_relevant:
            context_str = "\n".join([f"[文档{i + 1}] {d.page_content}" for i, d in enumerate(chosen_docs)])
            final_user_prompt = get_rag_template(strategy_text).format(
                question=question,
                context=context_str,
                history_context=history_context
            )
            answer = self.llm.generate_answer(final_user_prompt, system_prompt="你是一个专业的政策问答助手")
        else:
            final_user_prompt = get_no_context_template(strategy_text).format(
                question=question,
                history_context=history_context
            )
            answer = self.llm.generate_answer(final_user_prompt, system_prompt="你是一个专业的政策问答助手")
        print(answer)

        docs_payload = [
            {
                "content": d.page_content,
                "metadata": {**d.metadata, "modality_type": "text"},
            } for d in chosen_docs
        ]
        images_payload = [
            {
                "content": "",
                "metadata": {**(r.get("metadata") or {}), "modality_type": "image"},
                "url": (r.get("metadata") or {}).get("image_url")
                        or (r.get("metadata") or {}).get("full_image_url")
                        or "",
                "distance": r.get("distance", 0),
            }
            for r in image_results
        ]

        return {
            "answer": answer,
            "docs": docs_payload + images_payload,  # 供 sources/模板使用
            "images": images_payload,               # 供前端直接展示
            "used_template": used_template,
            **({"debug": {**debug_info, "used_template": used_template}} if debug else {}),
        }

    def generate_title(self, user_question: str, assistant_answer: str) -> str:
        """
        根据第一轮问答生成对话标题。
        """
        system_prompt = "你是一个对话标题生成助手。"
        prompt = f"""请根据以下对话内容，生成一个简洁的、不超过10个字的标题。直接返回标题文本，不要包含任何多余的解释、引号或标点符号。

用户：{user_question}
助手：{assistant_answer}"""
        
        try:
            # 为保证性能，标题生成固定使用轻量级模型
            title_llm = get_llm_service(api_key=self.api_key, model_name="qwen3-omni-flash")
            title = title_llm.generate_answer(prompt, system_prompt=system_prompt)
            # 清理和截断标题
            title = title.strip().replace('"', '').replace("'", "").replace("标题：", "")
            return title[:50]  # 限制最大长度以适应数据库字段
        except Exception as e:
            logger.error(f"生成标题失败: {e}")
            # 如果LLM生成失败，回退到使用问题的前20个字符作为标题
            return user_question[:20] + ('...' if len(user_question) > 20 else '')
    
    def build_prompt(
        self, 
        question: str, 
        text_contexts: List[Dict[str, Any]],
        image_contexts: List[Dict[str, Any]] = None,
        system_prompt: str = None
    ) -> tuple[str, str]:
        """
        构建提示词
        
        Args:
            question: 用户问题
            text_contexts: 文本上下文列表
            image_contexts: 图片上下文列表
            system_prompt: 系统提示词（可选）
        
        Returns:
            (system_prompt, user_prompt) 元组
        """
        # 默认系统提示词
        if system_prompt is None:
            system_prompt = "你是一个专业的问答助手。请根据提供的参考资料回答用户的问题，确保答案准确、详细。如果参考资料中没有相关信息，请明确告知用户。"
        
        # 构建文本上下文
        context_parts = []
        if text_contexts:
            for i, ctx in enumerate(text_contexts):
                content = ctx.get('content', ctx.get('document', ''))
                context_parts.append(f"【参考资料{i+1}】\n{content}")
        
        # 如果有图片，添加图片信息
        if image_contexts:
            image_info_parts = []
            for i, img in enumerate(image_contexts):
                metadata = img.get('metadata', {})
                file_name = metadata.get('file_name', '未知')
                image_info_parts.append(f"- 图片{i+1}: {file_name}")
            
            if image_info_parts:
                context_parts.append(f"【相关图片】\n" + "\n".join(image_info_parts))
        
        # 构建完整的用户提示词
        if context_parts:
            context_text = "\n\n".join(context_parts)
            user_prompt = f"""参考资料：
{context_text}

用户问题：{question}

请根据参考资料提供准确、详细的回答。"""
        else:
            user_prompt = f"用户问题：{question}"
        
        return system_prompt, user_prompt
    
    def generate_answer(
        self, 
        question: str, 
        contexts: List[Dict[str, Any]],
        system_prompt: str = None
    ) -> str:
        """
        基于检索到的上下文生成答案
        
        Args:
            question: 用户问题
            contexts: 检索到的上下文列表
            system_prompt: 系统提示词（可选）
        
        Returns:
            生成的答案
        """
        # 分离文本和图片上下文
        text_contexts = [
            ctx for ctx in contexts 
            if ctx.get('metadata', {}).get('modality_type', 'text') == 'text'
        ]
        image_contexts = [
            ctx for ctx in contexts 
            if ctx.get('metadata', {}).get('modality_type') == 'image'
        ]
        
        # 构建提示词
        sys_prompt, user_prompt = self.build_prompt(
            question=question,
            text_contexts=text_contexts,
            image_contexts=image_contexts,
            system_prompt=system_prompt
        )
        
        # 调用 LLM 生成答案（有图则走多模态接口）
        try:
            logger.info(f"正在使用 {self.model_name} 生成答案...")
            image_urls = []
            for img in image_contexts:
                md = img.get('metadata', {})
                url = md.get('full_image_url') or md.get('image_url')
                if url:
                    image_urls.append(url)
            if image_urls:
                answer = self.llm.generate_answer_multimodal(
                    text=user_prompt,
                    image_urls=image_urls,
                    system_prompt=sys_prompt
                )
            else:
                answer = self.llm.generate_answer(
                    prompt=user_prompt,
                    system_prompt=sys_prompt
                )
            return answer
        except Exception as e:
            logger.error(f"生成答案失败: {e}")
            # 如果生成失败，返回检索到的文本作为备选答案
            if text_contexts:
                fallback_answer = "根据检索到的信息：\n\n" + "\n\n".join([
                    ctx.get('content', ctx.get('document', ''))[:200] + "..." 
                    for ctx in text_contexts[:3]
                ])
                return fallback_answer
            else:
                return "抱歉，生成答案时出现错误，请稍后重试。"
    
    def answer_question(
        self, 
        question: str,
        collection_names: List[str],
        top_k: int = 5,
        include_images: bool = True,
        system_prompt: str = None
    ) -> Dict[str, Any]:
        """
        完整的问答流程：检索 + 生成
        
        Args:
            question: 用户问题
            collection_names: 要查询的集合名称列表
            top_k: 检索结果数量
            include_images: 是否包含图片
            system_prompt: 系统提示词（可选）
        
        Returns:
            包含答案、来源和图片的字典
        """
        # 1. 采用“先文后图”的检索策略，避免知识库污染
        text_results_all: List[Dict[str, Any]] = []
        image_results_all: List[Dict[str, Any]] = []

        # --- 第一步：检索最相关的文本 --- #
        for name in collection_names:
            try:
                self.encoder.set_collection(name)
                text_res = self.encoder.query(
                    query_text=question,
                    n_results=top_k,
                    modality_filter='text'
                ) or []
                text_results_all.extend(text_res)
            except Exception as e:
                logger.error(f"文本检索集合 '{name}' 失败: {e}")
                continue

        # 排序并获取Top K的文本结果
        text_results_all.sort(key=lambda x: x.get('distance', float('inf')))
        text_results = text_results_all[:top_k]

        # --- 第二步：在相关文档中检索图片 --- #
        if include_images and text_results:
            # 提取相关文本的源文件名
            source_files = list(set(
                r.get('metadata', {}).get('file_name') 
                for r in text_results 
                if r.get('metadata', {}).get('file_name')
            ))
            
            if source_files:
                logger.info(f"将在以下相关文档中检索图片: {source_files}")
                # 在相同的集合中，根据源文件名过滤图片
                for name in collection_names:
                    try:
                        self.encoder.set_collection(name)
                        # 修复：确保当 where 和 modality_filter 同时存在时，使用 $and 操作符
                        final_where = {
                            "$and": [
                                {"file_name": {"$in": source_files}},
                                {"modality_type": "image"}
                            ]
                        }
                        img_res = self.encoder.query(
                            query_text=question,
                            n_results=min(3, top_k),
                            where=final_where
                        ) or []
                        image_results_all.extend(img_res)
                    except Exception as e:
                        logger.error(f"图片检索集合 '{name}' 失败: {e}")
                        continue

        # 排序与截断图片结果
        image_results_all.sort(key=lambda x: x.get('distance', float('inf')))
        image_results = image_results_all[:min(3, top_k)] if include_images else []

        if not text_results and not image_results:
            return {
                'answer': '抱歉，我没有找到相关的信息来回答您的问题。',
                'sources': [],
                'images': [],
                'metadata': {
                    'total_results': 0,
                    'text_results': 0,
                    'image_results': 0,
                    'collections_searched': len(collection_names)
                }
            }

        # 2. 组装文本和图片上下文
        text_contexts = []
        image_contexts = []

        for result in text_results:
            metadata = result.get('metadata', {})
            text_contexts.append({
                'content': result.get('document', ''),
                'metadata': metadata,
                'distance': result.get('distance', 0)
            })

        for result in image_results:
            metadata = result.get('metadata', {})
            image_contexts.append({
                'url': metadata.get('image_url') or metadata.get('full_image_url') or '',
                'metadata': metadata,
                'distance': result.get('distance', 0)
            })
        
        # 3. 生成答案（将文本与图片上下文合并传入）
        merged_contexts = []
        for ctx in text_contexts:
            merged_contexts.append({
                'document': ctx.get('content', ''),
                'metadata': {**ctx.get('metadata', {}), 'modality_type': 'text'},
                'distance': ctx.get('distance', 0)
            })
        for img in image_contexts:
            merged_contexts.append({
                'document': '',
                'metadata': {**img.get('metadata', {}), 'modality_type': 'image'},
                'distance': img.get('distance', 0)
            })

        answer = self.generate_answer(
            question=question,
            contexts=merged_contexts,
            system_prompt=system_prompt
        )
        
        # 4. 格式化返回结果
        return {
            'answer': answer,
            'sources': [
                (lambda _ctx: {
                    'content': _ctx['content'],  # 返回完整内容
                    'file_name': _ctx['metadata'].get('file_name') or _ctx['metadata'].get('original_file') or _ctx['metadata'].get('source_file') or '未知',
                    'chunk_id': _ctx['metadata'].get('chunk_id', ''),
                    'distance': _ctx['distance']
                })(ctx)
                for ctx in text_contexts
            ],
            'images': [
                {
                    'url': img['url'],
                    'file_name': img['metadata'].get('file_name', '未知'),
                    'distance': img['distance']
                }
                for img in image_contexts
            ],
            'metadata': {
                'model': self.model_name,
                'collections_searched': collection_names,
                'total_results': len(text_contexts) + len(image_contexts),
                'text_results': len(text_contexts),
                'image_results': len(image_contexts)
            }
        }
