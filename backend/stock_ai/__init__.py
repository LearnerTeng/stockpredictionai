"""Modular stock prediction pipeline.

The package mirrors the production flow:
data -> features -> model -> scoring -> backtest -> notification -> manual order.
"""

from .pipeline import StockAiPipeline

__all__ = ["StockAiPipeline"]
