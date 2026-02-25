"""
Image validation - format, size, resolution, and quality assessment.

All pre-inference checks in a single module. Ensures images are
suitable for ML processing before consuming inference resources.
"""

import io
import cv2
import numpy as np
from PIL import Image

from core.models import ValidationResult, QualityMetrics, ValidationError
from core.config import (
    MAX_FILE_SIZE_MB,
    MIN_RESOLUTION,
    ALLOWED_FORMATS,
    QUALITY_THRESHOLD,
    QUALITY_WEIGHTS,
    SHARPNESS_CEILING,
    BRIGHTNESS_LOW,
    BRIGHTNESS_HIGH,
    CONTRAST_CEILING,
    CONTRAST_LOW,
)


def validate_image(image_bytes: bytes) -> ValidationResult:
    """
    Validates image format, size, resolution, and quality.

    Performs all pre-inference checks in order:
    1. File size
    2. Format
    3. Resolution
    4. Quality

    Returns ValidationResult with is_valid=False for rejections.
    Raises ValidationError only for fundamentally corrupt data.
    """
    size_bytes = len(image_bytes)
    size_mb = size_bytes / (1024 * 1024)

    if size_mb > MAX_FILE_SIZE_MB:
        return ValidationResult(
            is_valid=False,
            error_message=f"Image too large: {size_mb:.1f}MB (max {MAX_FILE_SIZE_MB}MB)",
            size_bytes=size_bytes,
        )

    try:
        img = Image.open(io.BytesIO(image_bytes))
        img.verify()
        img = Image.open(io.BytesIO(image_bytes))
    except Exception:
        return ValidationResult(
            is_valid=False,
            error_message="Invalid image - file is corrupted or not an image",
        )

    if img.format not in ALLOWED_FORMATS:
        return ValidationResult(
            is_valid=False,
            error_message=f"Unsupported format: {img.format} (only {', '.join(ALLOWED_FORMATS)} allowed)",
            format=img.format,
            size_bytes=size_bytes,
        )

    width, height = img.size
    if width < MIN_RESOLUTION or height < MIN_RESOLUTION:
        return ValidationResult(
            is_valid=False,
            error_message=f"Resolution too low: {width}x{height} (minimum {MIN_RESOLUTION}x{MIN_RESOLUTION})",
            format=img.format,
            size_bytes=size_bytes,
            resolution=(width, height),
        )

    quality = _assess_quality(image_bytes)

    return ValidationResult(
        is_valid=True,
        format=img.format,
        size_bytes=size_bytes,
        resolution=(width, height),
        quality=quality,
    )


def is_quality_acceptable(result: ValidationResult) -> bool:
    """Whether image quality meets minimum threshold for inference."""
    return result.quality.overall >= QUALITY_THRESHOLD


def get_quality_feedback(result: ValidationResult) -> str:
    """Human-readable quality feedback for API response."""
    if not result.quality.issues:
        return "Image quality is good."
    return "Please improve: " + "; ".join(result.quality.issues)


def _assess_quality(image_bytes: bytes) -> QualityMetrics:
    """
    Measures technical image quality using OpenCV.

    Sharpness:  Laplacian variance (edge detection)
    Brightness: Mean pixel value distance from optimal midpoint
    Contrast:   Pixel value standard deviation
    """
    nparr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    sharpness = min(cv2.Laplacian(gray, cv2.CV_64F).var() / SHARPNESS_CEILING, 1.0)

    mean_brightness = np.mean(gray) / 255
    brightness = 1.0 - abs(mean_brightness - 0.5) * 2

    contrast = min(float(np.std(gray)) / CONTRAST_CEILING, 1.0)

    overall = (
        sharpness * QUALITY_WEIGHTS["sharpness"]
        + brightness * QUALITY_WEIGHTS["brightness"]
        + contrast * QUALITY_WEIGHTS["contrast"]
    )

    issues: list[str] = []
    if sharpness < QUALITY_THRESHOLD:
        issues.append("Image too blurry - hold camera steady")
    if mean_brightness < BRIGHTNESS_LOW:
        issues.append("Image too dark - use flash or better lighting")
    elif mean_brightness > BRIGHTNESS_HIGH:
        issues.append("Image too bright - avoid direct sunlight")
    if contrast < CONTRAST_LOW:
        issues.append("Low contrast - ensure good lighting conditions")

    return QualityMetrics(
        overall=overall,
        sharpness=sharpness,
        brightness=brightness,
        contrast=contrast,
        issues=issues,
    )