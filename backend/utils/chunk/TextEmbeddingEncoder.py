#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
文本嵌入编码器
使用阿里云百炼 text-embedding-v4 API 生成文本向量嵌入，并存储到 Chroma 数据库

功能：
- 支持纯文本的向量化
- 将嵌入向量存储到 Chroma 向量数据库
- 支持批量处理和查询
"""

import os
from typing import List, Dict, Optional, Any

try:
    import dashscope
    from dashscope import TextEmbedding
    from http import HTTPStatus
    DASHSCOPE_AVAILABLE = True
except ImportError:
    DASHSCOPE_AVAILABLE = False
    print("警告：dashscope 未安装，请运行: pip install dashscope")

try:
    import chromadb
    from chromadb.config import Settings
    CHROMADB_AVAILABLE = True
except ImportError:
    CHROMADB_AVAILABLE = False
    print("警告：chromadb 未安装，请运行: pip install chromadb")


class TextEmbeddingEncoder:
    """文本嵌入编码器，使用 text-embedding-v4"""
    
    def __init__(self, 
                 api_key: Optional[str] = None,
                 model: str = "text-embedding-v4",
                 dimension: int = 1024,
                 chroma_db_path: str = "./chroma_db",
                 collection_name: str = "text_embeddings"):
        """
        初始化文本嵌入编码器
        
        Args:
            api_key: 阿里云百炼 API Key，如果不提供则从环境变量 DASHSCOPE_API_KEY 读取
            model: 使用的模型名称，默认 text-embedding-v4
            dimension: 向量维度，默认 1024（可选：2048, 1536, 1024, 768, 512, 256, 128, 64）
            chroma_db_path: Chroma 数据库路径
            collection_name: Chroma 集合名称
        """
        if not DASHSCOPE_AVAILABLE:
            raise ImportError("需要安装 dashscope: pip install dashscope")
        
        if not CHROMADB_AVAILABLE:
            raise ImportError("需要安装 chromadb: pip install chromadb")
        
        # 设置 API Key
        if api_key:
            dashscope.api_key = api_key
        elif os.getenv("DASHSCOPE_API_KEY"):
            dashscope.api_key = os.getenv("DASHSCOPE_API_KEY")
        else:
            raise ValueError("请提供 API Key 或设置环境变量 DASHSCOPE_API_KEY")
        
        self.model = model
        self.dimension = dimension
        self.chroma_db_path = chroma_db_path
        self.collection_name = collection_name
        
        # 初始化 Chroma 客户端
        self._init_chroma_client()
    
    def _init_chroma_client(self):
        """初始化 Chroma 客户端和集合"""
        os.makedirs(self.chroma_db_path, exist_ok=True)
        
        # 创建 Chroma 客户端
        self.chroma_client = chromadb.PersistentClient(
            path=self.chroma_db_path,
            settings=Settings(
                anonymized_telemetry=False,
                allow_reset=True
            )
        )
        
        # 获取或创建集合
        try:
            self.collection = self.chroma_client.get_collection(
                name=self.collection_name
            )
        except:
            # 集合不存在，创建新集合
            self.collection = self.chroma_client.create_collection(
                name=self.collection_name,
                metadata={"description": "文本嵌入向量集合", "model": self.model}
            )
    
    def encode(self, texts: List[str]) -> List[Dict[str, Any]]:
        """
        对文本列表进行向量化编码
        
        Args:
            texts: 文本列表
            
        Returns:
            包含嵌入向量的结果列表，每个结果包含 'embedding' 和 'text_index'
        """
        if not texts:
            return []
        
        try:
            # 调用 text-embedding-v4 API
            resp = TextEmbedding.call(
                model=self.model,
                input=texts,
                dimension=self.dimension,
                text_type='document'  # 用于入库的文本类型
            )
            
            if resp.status_code == HTTPStatus.OK:
                embeddings = resp.output.get('embeddings', [])
                return embeddings
            else:
                error_msg = f"API调用失败: {resp.code} - {resp.message}"
                raise RuntimeError(error_msg)
        
        except Exception as e:
            raise RuntimeError(f"编码失败: {str(e)}")
    
    def encode_chunk(self, chunk: Dict) -> Optional[Dict]:
        """
        对单个分块进行编码
        
        Args:
            chunk: 分块字典，包含 'content' 和 'metadata'
            
        Returns:
            编码后的结果字典，包含 'embedding', 'content', 'metadata'
        """
        if not chunk.get('content'):
            return None
        
        try:
            embeddings = self.encode([chunk['content']])
            if not embeddings:
                return None
            
            embedding_data = embeddings[0]
            return {
                'embedding': embedding_data.get('embedding'),
                'content': chunk['content'],
                'metadata': chunk.get('metadata', {})
            }
        except Exception as e:
            print(f"编码分块失败: {e}")
            return None
    
    def save_to_chroma(self, encoded_chunks: List[Dict], metadatas: Optional[List[Dict]] = None):
        """
        将编码后的分块保存到 Chroma
        
        Args:
            encoded_chunks: 编码后的分块列表，每个包含 'embedding', 'content', 'metadata'
            metadatas: 可选的元数据列表
        """
        if not encoded_chunks:
            return
        
        # 准备数据
        ids = []
        embeddings = []
        documents = []
        metadata_list = []
        
        for i, chunk in enumerate(encoded_chunks):
            chunk_id = str(chunk.get('id', f"chunk_{i}"))
            embedding = chunk.get('embedding')
            content = chunk.get('content', '')
            metadata = chunk.get('metadata', {})
            
            # 过滤掉 metadata 中的 None 值（Chroma 不接受 None）
            if metadata:
                metadata = {k: v for k, v in metadata.items() if v is not None}
            
            if embedding:
                ids.append(chunk_id)
                embeddings.append(embedding)
                documents.append(content)
                metadata_list.append(metadata)
        
        if not ids:
            return
        
        try:
            # 批量添加到 Chroma
            self.collection.add(
                ids=ids,
                embeddings=embeddings,
                documents=documents,
                metadatas=metadata_list if metadata_list else None
            )
        except Exception as e:
            raise RuntimeError(f"保存到 Chroma 失败: {str(e)}")
    
    def process_and_store(self, 
                         chunks: List[Dict],
                         batch_size: int = 10,
                         metadatas: Optional[List[Dict]] = None):
        """
        批量处理分块并存储到 Chroma
        
        Args:
            chunks: 分块列表，每个包含 'id', 'content', 'metadata'
            batch_size: 批量大小
            metadatas: 可选的元数据列表
        """
        if not chunks:
            return
        
        # 提取所有文本内容
        texts = [chunk['content'] for chunk in chunks if chunk.get('content')]
        
        if not texts:
            return
        
        # 批量编码
        encoded_chunks = []
        for i in range(0, len(texts), batch_size):
            batch_texts = texts[i:i+batch_size]
            batch_embeddings = self.encode(batch_texts)
            
            # 合并编码结果和原始分块
            for j, embedding_data in enumerate(batch_embeddings):
                chunk_idx = i + j
                if chunk_idx < len(chunks):
                    chunk = chunks[chunk_idx]
                    encoded_chunks.append({
                        'id': chunk.get('id', f"chunk_{chunk_idx}"),
                        'embedding': embedding_data.get('embedding'),
                        'content': chunk['content'],
                        'metadata': chunk.get('metadata', {})
                    })
        
        # 保存到 Chroma
        self.save_to_chroma(encoded_chunks, metadatas)
    
    def query(self, 
              query_text: str,
              n_results: int = 5,
              where: Optional[Dict] = None) -> List[Dict]:
        """
        查询相似向量
        
        Args:
            query_text: 查询文本
            n_results: 返回结果数量
            where: 可选的过滤条件
            
        Returns:
            查询结果列表
        """
        # 首先对查询文本进行编码
        try:
            # 使用 query 类型进行查询编码
            resp = TextEmbedding.call(
                model=self.model,
                input=[query_text],
                dimension=self.dimension,
                text_type='query'  # 查询文本类型
            )
            
            if resp.status_code != HTTPStatus.OK:
                print(f"查询编码失败: {resp.code} - {resp.message}")
                return []
            
            embeddings = resp.output.get('embeddings', [])
            if not embeddings:
                return []
            
            query_embedding = embeddings[0].get('embedding')
        except Exception as e:
            print(f"查询编码失败: {e}")
            return []
        
        # 在 Chroma 中查询
        try:
            results = self.collection.query(
                query_embeddings=[query_embedding],
                n_results=n_results,
                where=where
            )
            
            # 格式化结果
            formatted_results = []
            if results.get('ids') and len(results['ids'][0]) > 0:
                for i in range(len(results['ids'][0])):
                    formatted_results.append({
                        'id': results['ids'][0][i],
                        'distance': results['distances'][0][i] if 'distances' in results else None,
                        'document': results['documents'][0][i] if 'documents' in results else None,
                        'metadata': results['metadatas'][0][i] if 'metadatas' in results else None
                    })
            
            return formatted_results
        
        except Exception as e:
            print(f"查询失败: {e}")
            return []


if __name__ == "__main__":
    """测试示例"""
    import os
    
    # 需要设置 API Key
    api_key = os.getenv("DASHSCOPE_API_KEY")
    if not api_key:
        print("请设置环境变量 DASHSCOPE_API_KEY")
        exit(1)
    
    # 初始化编码器
    encoder = TextEmbeddingEncoder(
        api_key=api_key,
        model="text-embedding-v4",
        dimension=1024,
        chroma_db_path="./chroma_db",
        collection_name="test_text_embeddings"
    )
    
    # 测试文本编码
    test_chunks = [
        {
            'id': 1,
            'content': '这是一个测试文本块',
            'metadata': {'file_name': 'test.txt', 'chunk_index': 1}
        },
        {
            'id': 2,
            'content': '这是另一个测试文本块',
            'metadata': {'file_name': 'test.txt', 'chunk_index': 2}
        }
    ]
    
    # 处理并存储
    encoder.process_and_store(test_chunks)
    print("✓ 编码和存储完成")
    
    # 测试查询
    results = encoder.query("测试", n_results=2)
    print(f"查询结果数量: {len(results)}")
    for result in results:
        print(f"ID: {result['id']}, 距离: {result['distance']}")

