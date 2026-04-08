from .candle_features import calculate_candle_features
from .lse_heuristic_agent import LseHeuristicAgent
from .protocol import TechnicalAgentProtocol

__all__ = [
    "LseHeuristicAgent",
    "TechnicalAgentProtocol",
    "calculate_candle_features",
    "LlmTechnicalAgent",
]


def __getattr__(name: str):
    """``LlmTechnicalAgent`` подгружается лениво (нужен ``langchain_core``)."""
    if name == "LlmTechnicalAgent":
        from .llm_technical_agent import LlmTechnicalAgent

        return LlmTechnicalAgent
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return list(__all__)
