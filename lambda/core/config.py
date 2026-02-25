import os
"""
Configuration for the car damage detection system.

All thresholds, limits, and weights in one place.
Change here, not in business logic modules.
"""

# --- Validation ---

MAX_FILE_SIZE_MB: float = 10.0
MIN_RESOLUTION: int = 320
ALLOWED_FORMATS: set[str] = {"JPEG", "PNG"}

# --- Quality Assessment ---

QUALITY_THRESHOLD: float = 0.4

QUALITY_WEIGHTS: dict[str, float] = {
    "sharpness": 0.5,
    "brightness": 0.3,
    "contrast": 0.2,
}

# Sharpness: Laplacian variance normalization ceiling
SHARPNESS_CEILING: float = 500.0

# Brightness: below/above these trigger warnings
BRIGHTNESS_LOW: float = 0.3
BRIGHTNESS_HIGH: float = 0.7

# Contrast: std dev normalization ceiling
CONTRAST_CEILING: float = 128.0
CONTRAST_LOW: float = 0.3

# --- Inference ---

CONFIDENCE_THRESHOLD: float = 0.7
MODEL_PATH: str = "/var/task/models/car_damage_v1.onnx"
MODEL_PATH_LOCAL: str = "models/car_damage_v1.onnx"
MODEL_INPUT_SIZE: tuple[int, int] = (224, 224)
CLASS_LABELS: dict[int, str] = {0: "damage", 1: "whole"}
MODEL_VERSION: str = "v1.0"

# --- Storage ---

DYNAMODB_TABLE: str = os.environ.get("DYNAMODB_TABLE", "claims")