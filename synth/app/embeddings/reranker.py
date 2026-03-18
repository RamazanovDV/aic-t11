from abc import ABC, abstractmethod
from typing import Any
import numpy as np


class BaseReranker(ABC):
    @abstractmethod
    def filter(
        self,
        results: list[dict[str, Any]],
        top_k: int,
    ) -> list[dict[str, Any]]:
        pass


class NoOpReranker(BaseReranker):
    def filter(
        self,
        results: list[dict[str, Any]],
        top_k: int,
    ) -> list[dict[str, Any]]:
        return results[:top_k]


class RelativeReranker(BaseReranker):
    def __init__(self, multiplier: float = 1.5):
        self.multiplier = multiplier

    def filter(
        self,
        results: list[dict[str, Any]],
        top_k: int,
    ) -> list[dict[str, Any]]:
        if not results:
            return []

        best_distance = results[0].get("distance", float("inf"))
        threshold_distance = best_distance * self.multiplier

        filtered = [
            r for r in results
            if r.get("distance", float("inf")) <= threshold_distance
        ]
        return filtered[:top_k]


class FixedThresholdReranker(BaseReranker):
    def __init__(self, threshold: float = 0.3):
        self.threshold = threshold

    def filter(
        self,
        results: list[dict[str, Any]],
        top_k: int,
    ) -> list[dict[str, Any]]:
        filtered = [
            r for r in results
            if r.get("similarity", 0) >= self.threshold
        ]
        return filtered[:top_k]


class StatisticalReranker(BaseReranker):
    def __init__(self, std_multiplier: float = 2.0):
        self.std_multiplier = std_multiplier

    def filter(
        self,
        results: list[dict[str, Any]],
        top_k: int,
    ) -> list[dict[str, Any]]:
        if len(results) < 3:
            return results[:top_k]

        distances = [r.get("distance", 0) for r in results]
        mean_dist = np.mean(distances)
        std_dist = np.std(distances)

        threshold = mean_dist + self.std_multiplier * std_dist

        filtered = [
            r for r in results
            if r.get("distance", float("inf")) <= threshold
        ]
        return filtered[:top_k]


def create_reranker(reranker_type: str, config: dict[str, Any]) -> BaseReranker:
    reranker_type = reranker_type.lower()

    if reranker_type == "relative":
        return RelativeReranker(
            multiplier=config.get("multiplier", 1.5),
        )
    elif reranker_type == "fixed":
        return FixedThresholdReranker(
            threshold=config.get("threshold", 0.3),
        )
    elif reranker_type == "statistical":
        return StatisticalReranker(
            std_multiplier=config.get("std_multiplier", 2.0),
        )
    else:
        return NoOpReranker()


def apply_reranker(
    results: list[dict[str, Any]],
    reranker_config: dict[str, Any],
    top_k: int,
    query: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not results:
        return [], {"type": "none", "before_count": 0, "filtered_count": 0}

    reranker_type = reranker_config.get("type", "none")

    if reranker_type == "none" or not reranker_type:
        return results[:top_k], {"type": "none", "before_count": len(results), "filtered_count": 0, "after_count": len(results[:top_k])}

    if query:
        for r in results:
            r["_query"] = query

    reranker = create_reranker(reranker_type, reranker_config)

    before_count = len(results)
    filtered = reranker.filter(results, top_k)
    filtered_count = before_count - len(filtered)

    meta = {
        "type": reranker_type,
        "before_count": before_count,
        "filtered_count": filtered_count,
        "after_count": len(filtered),
    }

    return filtered, meta
