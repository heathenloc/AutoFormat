"""Offline quality, cost, and load evaluation primitives."""

from brief_parser.evaluation.dataset import (
    GoldenDatasetSource,
    default_golden_dataset_path,
    load_golden_dataset,
)
from brief_parser.evaluation.evaluator import evaluate_dataset
from brief_parser.evaluation.models import (
    EvaluationReport,
    GoldenCase,
    GoldenDataset,
    PredictionRecord,
    PricingTable,
    ReleaseThresholds,
)

__all__ = [
    "EvaluationReport",
    "GoldenCase",
    "GoldenDataset",
    "GoldenDatasetSource",
    "PredictionRecord",
    "PricingTable",
    "ReleaseThresholds",
    "default_golden_dataset_path",
    "evaluate_dataset",
    "load_golden_dataset",
]
