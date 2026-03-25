# -*- coding: utf-8 -*-
from typing import List
from sentence_transformers import CrossEncoder
import torch

class CrossEncoderWrapper:
    """基于 sentence-transformers 的 CrossEncoder（默认 BAAI/bge-reranker-large）"""

    def __init__(self, model_path: str = "BAAI/bge-reranker-large", batch_size: int = 16):
        self.batch_size = batch_size
        device = "cuda" if torch.cuda.is_available() else "cpu"
        
        # 兼容不同版本的初始化方式
        try:
            self.model = CrossEncoder(model_path, device=device)
        except Exception as e:
            try:
                self.model = CrossEncoder(model_name_or_path=model_path, device=device)
            except:
                self.model = CrossEncoder(model_name=model_path, device=device)

    def score(self, query: str, passages: List[str]) -> List[float]:
        if not passages:
            return []
        pairs = [(query, p) for p in passages]
        scores = self.model.predict(pairs, batch_size=self.batch_size)
        return [float(s) for s in scores]