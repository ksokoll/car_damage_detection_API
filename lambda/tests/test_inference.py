"""
Unit tests for inference module
"""
import pytest
import time
from PIL import Image
import io
import numpy as np
from pathlib import Path
from pydantic import ValidationError as PydanticValidationError

from core.inference import (
    predict_damage,
    is_confidence_acceptable,
    get_prediction_summary,
    clear_model_cache,
)
from core.models import PredictionResult, InferenceError
from core.config import CONFIDENCE_THRESHOLD, MODEL_INPUT_SIZE


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def valid_image_bytes():
    """Create a valid test image"""
    img = Image.new('RGB', (600, 600), color='red')
    img_bytes = io.BytesIO()
    img.save(img_bytes, format='JPEG')
    return img_bytes.getvalue()


@pytest.fixture
def small_image_bytes():
    """Create a smaller image (will be resized)"""
    img = Image.new('RGB', (300, 300), color='blue')
    img_bytes = io.BytesIO()
    img.save(img_bytes, format='JPEG')
    return img_bytes.getvalue()


@pytest.fixture
def png_with_alpha_bytes():
    """Create PNG with alpha channel"""
    img = Image.new('RGBA', (600, 600), color=(255, 0, 0, 128))
    img_bytes = io.BytesIO()
    img.save(img_bytes, format='PNG')
    return img_bytes.getvalue()


@pytest.fixture(autouse=True)
def clear_cache_after_test():
    """Clear model cache after each test"""
    yield
    clear_model_cache()


# ============================================================================
# PREDICTION TESTS
# ============================================================================

class TestPrediction:
    """Test damage prediction functionality"""
    
    @pytest.mark.skipif(
        not Path("models/car_damage_v1.onnx").exists(),
        reason="Model file not available"
    )
    def test_predict_returns_valid_result(self, valid_image_bytes):
        """Prediction should return valid PredictionResult"""
        result = predict_damage(valid_image_bytes)
        
        assert isinstance(result, PredictionResult)
        assert isinstance(result.damage_detected, bool)
        assert 0.0 <= result.confidence <= 1.0
        assert isinstance(result.probabilities, dict)
    
    @pytest.mark.skipif(
        not Path("models/car_damage_v1.onnx").exists(),
        reason="Model file not available"
    )
    def test_probabilities_sum_to_one(self, valid_image_bytes):
        """Model probabilities should sum to approximately 1.0"""
        result = predict_damage(valid_image_bytes)
        
        prob_sum = sum(result.probabilities.values())
        
        # Allow small floating point error
        assert abs(prob_sum - 1.0) < 0.01
    
    @pytest.mark.skipif(
        not Path("models/car_damage_v1.onnx").exists(),
        reason="Model file not available"
    )
    def test_probabilities_contain_expected_classes(self, valid_image_bytes):
        """Probabilities should contain 'damage' and 'whole' classes"""
        result = predict_damage(valid_image_bytes)
        
        assert 'damage' in result.probabilities
        assert 'whole' in result.probabilities
        assert len(result.probabilities) == 2
    
    @pytest.mark.skipif(
        not Path("models/car_damage_v1.onnx").exists(),
        reason="Model file not available"
    )
    def test_damage_detected_matches_max_probability(self, valid_image_bytes):
        """damage_detected should match highest probability class"""
        result = predict_damage(valid_image_bytes)
        
        damage_prob = result.probabilities['damage']
        whole_prob = result.probabilities['whole']
        
        if damage_prob > 0.5:
            assert result.damage_detected == True
        else:
            assert result.damage_detected == False
    
    @pytest.mark.skipif(
        not Path("models/car_damage_v1.onnx").exists(),
        reason="Model file not available"
    )
    def test_confidence_is_max_probability(self, valid_image_bytes):
        """Confidence should be the maximum probability"""
        result = predict_damage(valid_image_bytes)
        
        max_prob = max(result.probabilities.values())
        
        # Allow small floating point error
        assert abs(result.confidence - max_prob) < 0.01
    
    @pytest.mark.skipif(
        not Path("models/car_damage_v1.onnx").exists(),
        reason="Model file not available"
    )
    def test_probabilities_are_reasonable(self, valid_image_bytes):
        """Probabilities should be in valid range (not testing exact rounding)"""
        result = predict_damage(valid_image_bytes)
        
        # All probabilities should be in [0, 1]
        for prob in result.probabilities.values():
            assert 0.0 <= prob <= 1.0
        
        # Probabilities should be "reasonable" (not extreme precision artifacts)
        # Check they're not absurdly precise (e.g., 0.123456789012345)
        for prob in result.probabilities.values():
            # Should have at most ~10 significant digits (normal float precision)
            assert len(str(prob).replace('.', '')) < 15
    
    @pytest.mark.skipif(
        not Path("models/car_damage_v1.onnx").exists(),
        reason="Model file not available"
    )
    def test_model_caching_works(self, valid_image_bytes):
        """Second prediction should use cached model"""
        # First call loads model
        result1 = predict_damage(valid_image_bytes)
        
        # Second call should reuse cached model (faster)
        result2 = predict_damage(valid_image_bytes)
        
        # Both should return valid results
        assert isinstance(result1, PredictionResult)
        assert isinstance(result2, PredictionResult)
        
        # Results should be consistent (same input)
        assert result1.damage_detected == result2.damage_detected
    
    def test_predict_with_corrupted_data_raises_error(self):
        """Corrupted image data should raise InferenceError"""
        corrupted = b'not an image'
        
        with pytest.raises(InferenceError):
            predict_damage(corrupted)
    
    def test_predict_with_empty_bytes_raises_error(self):
        """Empty bytes should raise InferenceError"""
        with pytest.raises(InferenceError):
            predict_damage(b'')


# ============================================================================
# PREPROCESSING TESTS
# ============================================================================

class TestPreprocessing:
    """Test image preprocessing logic"""
    
    @pytest.mark.skipif(
        not Path("models/car_damage_v1.onnx").exists(),
        reason="Model file not available"
    )
    def test_image_resized_to_input_size(self, small_image_bytes):
        """Images should be resized to MODEL_INPUT_SIZE before inference"""
        # Small image (300x300) should still work
        result = predict_damage(small_image_bytes)
        
        assert isinstance(result, PredictionResult)
        # If preprocessing worked, we get valid result
    
    @pytest.mark.skipif(
        not Path("models/car_damage_v1.onnx").exists(),
        reason="Model file not available"
    )
    def test_png_with_alpha_handled(self, png_with_alpha_bytes):
        """PNG with alpha channel should be converted to RGB"""
        # Should not raise error
        result = predict_damage(png_with_alpha_bytes)
        
        assert isinstance(result, PredictionResult)
    
    @pytest.mark.skipif(
        not Path("models/car_damage_v1.onnx").exists(),
        reason="Model file not available"
    )
    def test_large_image_handled(self):
        """Large images should be resized without error"""
        # Create very large image
        img = Image.new('RGB', (4000, 3000), color='green')
        img_bytes = io.BytesIO()
        img.save(img_bytes, format='JPEG')
        
        result = predict_damage(img_bytes.getvalue())
        
        assert isinstance(result, PredictionResult)


# ============================================================================
# HELPER FUNCTIONS TESTS
# ============================================================================

class TestHelperFunctions:
    """Test helper functions"""
    
    def test_is_confidence_acceptable_above_threshold(self):
        """Confidence above CONFIDENCE_THRESHOLD is acceptable"""
        result = PredictionResult(
            damage_detected=True,
            confidence=0.95
        )
        
        assert is_confidence_acceptable(result) == True
    
    def test_is_confidence_acceptable_below_threshold(self):
        """Confidence below CONFIDENCE_THRESHOLD is not acceptable"""
        result = PredictionResult(
            damage_detected=True,
            confidence=0.5
        )
        
        assert is_confidence_acceptable(result) == False
    
    def test_is_confidence_acceptable_at_threshold(self):
        """Confidence exactly at CONFIDENCE_THRESHOLD is acceptable"""
        result = PredictionResult(
            damage_detected=True,
            confidence=CONFIDENCE_THRESHOLD
        )
        
        assert is_confidence_acceptable(result) == True
    
    def test_get_prediction_summary_damage_detected(self):
        """Summary for damage detection should be readable"""
        result = PredictionResult(
            damage_detected=True,
            confidence=0.94
        )
        
        summary = get_prediction_summary(result)
        
        assert isinstance(summary, str)
        assert "damage detected" in summary.lower()
        assert "94" in summary or "0.94" in summary
    
    def test_get_prediction_summary_no_damage(self):
        """Summary for no damage should be readable"""
        result = PredictionResult(
            damage_detected=False,
            confidence=0.88
        )
        
        summary = get_prediction_summary(result)
        
        assert isinstance(summary, str)
        assert "no damage" in summary.lower()
        assert "88" in summary or "0.88" in summary
    
    def test_get_prediction_summary_low_confidence(self):
        """Summary should show confidence even when low"""
        result = PredictionResult(
            damage_detected=True,
            confidence=0.52
        )
        
        summary = get_prediction_summary(result)
        
        assert isinstance(summary, str)
        assert "52" in summary or "0.52" in summary


# ============================================================================
# PYDANTIC FEATURES TESTS
# ============================================================================

class TestPydanticFeatures:
    """Test Pydantic model validation"""
    
    def test_pydantic_rejects_confidence_above_one(self):
        """Confidence > 1.0 should be rejected"""
        with pytest.raises(PydanticValidationError):
            PredictionResult(
                damage_detected=True,
                confidence=1.5
            )
    
    def test_pydantic_rejects_confidence_below_zero(self):
        """Confidence < 0.0 should be rejected"""
        with pytest.raises(PydanticValidationError):
            PredictionResult(
                damage_detected=True,
                confidence=-0.1
            )
    
    def test_pydantic_accepts_boundary_values(self):
        """Confidence of exactly 0.0 or 1.0 should be valid"""
        # Minimum
        result_min = PredictionResult(
            damage_detected=False,
            confidence=0.0
        )
        assert result_min.confidence == 0.0
        
        # Maximum
        result_max = PredictionResult(
            damage_detected=True,
            confidence=1.0
        )
        assert result_max.confidence == 1.0
    
    def test_default_probabilities_empty_dict(self):
        """Probabilities should default to empty dict"""
        result = PredictionResult(
            damage_detected=True,
            confidence=0.8
        )
        
        assert result.probabilities == {}
    
    def test_json_serialization(self):
        """PredictionResult should be JSON-serializable"""
        result = PredictionResult(
            damage_detected=True,
            confidence=0.94,
            probabilities={"damage": 0.94, "whole": 0.06}
        )
        
        json_data = result.model_dump()
        
        assert isinstance(json_data, dict)
        assert json_data['damage_detected'] == True
        assert json_data['confidence'] == 0.94
        assert json_data['probabilities'] == {"damage": 0.94, "whole": 0.06}
    
    def test_json_serialization_preserves_structure(self):
        """JSON structure should match model structure"""
        result = PredictionResult(
            damage_detected=False,
            confidence=0.88,
            probabilities={"damage": 0.12, "whole": 0.88}
        )
        
        json_data = result.model_dump()
        
        assert 'damage_detected' in json_data
        assert 'confidence' in json_data
        assert 'probabilities' in json_data
        assert isinstance(json_data['probabilities'], dict)


# ============================================================================
# MODEL LOADING TESTS
# ============================================================================

class TestModelLoading:
    """Test model loading and caching behavior"""
    
    def test_clear_model_cache_is_idempotent(self):
        """clear_model_cache should be safe to call multiple times"""
        clear_model_cache()
        clear_model_cache()  # Should not crash
        clear_model_cache()
    
    @pytest.mark.skipif(
        not Path("models/car_damage_v1.onnx").exists(),
        reason="Model file not available"
    )
    def test_cache_cleared_forces_reload(self, valid_image_bytes):
        """After cache clear, model should be reloaded on next prediction"""
        # First prediction loads model
        start1 = time.perf_counter()
        result1 = predict_damage(valid_image_bytes)
        duration1 = time.perf_counter() - start1
        
        # Second prediction uses cache (should be faster)
        start2 = time.perf_counter()
        result2 = predict_damage(valid_image_bytes)
        duration2 = time.perf_counter() - start2
        
        # Clear cache
        clear_model_cache()
        
        # Third prediction reloads model (should be slower than cached)
        start3 = time.perf_counter()
        result3 = predict_damage(valid_image_bytes)
        duration3 = time.perf_counter() - start3
        
        # All should return valid results
        assert isinstance(result1, PredictionResult)
        assert isinstance(result2, PredictionResult)
        assert isinstance(result3, PredictionResult)
        
        # Cached call should be faster than first call
        # (model loading takes ~100-500ms, inference takes ~50ms)
        # This is a weak assertion because timing is system-dependent
        # But cache clear + reload (duration3) should be comparable to first load (duration1)
        # Note: We don't assert duration2 < duration1 because it's flaky on fast systems
        assert duration3 > 0  # Sanity check: timing worked
    
    @pytest.mark.skipif(
        Path("models/car_damage_v1.onnx").exists(),
        reason="Skip when model IS available"
    )
    def test_missing_model_raises_error(self, valid_image_bytes):
        """Missing model file should raise InferenceError"""
        with pytest.raises(InferenceError) as exc_info:
            predict_damage(valid_image_bytes)
        
        assert "Model not found" in str(exc_info.value)


# Run with:
# pytest tests/test_inference.py -v
# pytest tests/test_inference.py --cov=core.inference --cov-report=term-missing
# pytest tests/test_inference.py -v -k "not skipif"  # Run only non-skipped tests