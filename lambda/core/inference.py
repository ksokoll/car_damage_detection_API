"""
ML inference - ONNX model loading and damage prediction.

Handles model lifecycle, image preprocessing, and inference execution.
Optimized for CPU inference in AWS Lambda.
"""

import io
import numpy as np
import onnxruntime as ort
from pathlib import Path
from PIL import Image

from core.models import PredictionResult, InferenceError
from core.config import (
    MODEL_PATH,
    MODEL_PATH_LOCAL,
    MODEL_INPUT_SIZE,
    CONFIDENCE_THRESHOLD,
    CLASS_LABELS,
)


# --- Global model cache ---
# Lambda containers persist between invocations.
# Loading once and caching saves ~500ms per request.

_model_session: ort.InferenceSession | None = None


# --- Public API ---

def predict_damage(image_bytes: bytes) -> PredictionResult:
    """
    Predicts whether image shows vehicle damage.

    Assumes image already validated (format and quality checked).

    Raises:
        InferenceError: If model loading or inference fails.
    """
    try:
        model = _load_model()
        input_tensor = _preprocess(image_bytes)

        outputs = model.run(None, {"images": input_tensor})
        probabilities = _softmax(outputs[0][0])

        damage_prob = float(probabilities[0])
        whole_prob = float(probabilities[1])

        return PredictionResult(
            damage_detected=damage_prob > 0.5,
            confidence=max(damage_prob, whole_prob),
            probabilities={
                CLASS_LABELS[0]: round(damage_prob, 4),
                CLASS_LABELS[1]: round(whole_prob, 4),
            },
        )

    except InferenceError:
        raise
    except Exception as e:
        raise InferenceError(f"Inference failed: {e}")


def is_confidence_acceptable(result: PredictionResult) -> bool:
    """Whether prediction confidence meets minimum threshold."""
    return result.confidence >= CONFIDENCE_THRESHOLD


def get_prediction_summary(result: PredictionResult) -> str:
    """Human-readable prediction summary for API response."""
    label = "Damage detected" if result.damage_detected else "No damage detected"
    return f"{label} with {result.confidence:.1%} confidence"


def clear_model_cache() -> None:
    """Clears cached model. Used in testing only."""
    global _model_session
    _model_session = None


# --- Internal ---

def _load_model() -> ort.InferenceSession:
    """
    Loads ONNX model with global caching.

    Tries Lambda path first, falls back to local path for development.
    """
    global _model_session

    if _model_session is not None:
        return _model_session

    model_path = Path(MODEL_PATH)
    if not model_path.exists():
        model_path = Path(MODEL_PATH_LOCAL)

    if not model_path.exists():
        raise InferenceError(
            f"Model not found. Tried: {MODEL_PATH}, {MODEL_PATH_LOCAL}"
        )

    try:
        _model_session = ort.InferenceSession(
            str(model_path),
            providers=["CPUExecutionProvider"],
        )
        return _model_session
    except Exception as e:
        raise InferenceError(f"Failed to load model: {e}")


def _preprocess(image_bytes: bytes) -> np.ndarray:
    """
    Preprocesses image for YOLOv8 classification input.

    Pipeline:
    1. Decode → PIL Image
    2. Resize to MODEL_INPUT_SIZE
    3. Convert to RGB (handles PNG alpha)
    4. Normalize [0, 255] → [0.0, 1.0]
    5. Transpose HWC → CHW
    6. Add batch dimension → NCHW (1, 3, 224, 224)
    """
    try:
        img = Image.open(io.BytesIO(image_bytes))
        img = img.resize(MODEL_INPUT_SIZE, Image.Resampling.LANCZOS)
        img = img.convert("RGB")

        tensor = np.array(img, dtype=np.float32) / 255.0
        tensor = np.transpose(tensor, (2, 0, 1))
        tensor = np.expand_dims(tensor, axis=0)

        return tensor
    except Exception as e:
        raise InferenceError(f"Preprocessing failed: {e}")


def _softmax(logits: np.ndarray) -> np.ndarray:
    """Converts model logits to probabilities. Numerically stable."""
    exp = np.exp(logits - np.max(logits))
    return exp / exp.sum()