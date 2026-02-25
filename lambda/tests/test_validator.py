"""
Unit tests for validator module (Pydantic version)
"""
import pytest
from PIL import Image, ImageDraw
import io
from pydantic import ValidationError as PydanticValidationError
from core.validator import (
    validate_image,
    is_quality_acceptable,
    get_quality_feedback,
    ValidationError,
    ValidationResult,
    QualityMetrics,
    MAX_FILE_SIZE_MB,
    MIN_RESOLUTION,
)


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def valid_jpeg_bytes():
    """Create a valid JPEG image for testing"""
    img = Image.new('RGB', (600, 600), color='red')
    img_bytes = io.BytesIO()
    img.save(img_bytes, format='JPEG')
    return img_bytes.getvalue()


@pytest.fixture
def valid_png_bytes():
    """Create a valid PNG image for testing"""
    img = Image.new('RGB', (600, 600), color='blue')
    img_bytes = io.BytesIO()
    img.save(img_bytes, format='PNG')
    return img_bytes.getvalue()


@pytest.fixture
def small_image_bytes():
    """Create image below resolution threshold"""
    img = Image.new('RGB', (300, 300), color='green')
    img_bytes = io.BytesIO()
    img.save(img_bytes, format='JPEG')
    return img_bytes.getvalue()


# ============================================================================
# FORMAT VALIDATION TESTS
# ============================================================================

class TestFormatValidation:
    """Test format validation logic"""
    
    def test_valid_jpeg(self, valid_jpeg_bytes):
        """Valid JPEG should pass format checks"""
        result = validate_image(valid_jpeg_bytes)
        
        assert result.is_valid == True
        assert result.format == 'JPEG'
        assert result.error_message is None
        assert result.resolution == (600, 600)
        assert isinstance(result.quality, QualityMetrics)
    
    def test_valid_png(self, valid_png_bytes):
        """Valid PNG should pass format checks"""
        result = validate_image(valid_png_bytes)
        
        assert result.is_valid == True
        assert result.format == 'PNG'
        assert result.error_message is None
    
    def test_resolution_too_low(self, small_image_bytes):
        """Image below MIN_RESOLUTION should fail"""
        result = validate_image(small_image_bytes)
        
        assert result.is_valid == False
        assert "Resolution too low" in result.error_message
        assert result.resolution == (300, 300)
        assert f"{MIN_RESOLUTION}x{MIN_RESOLUTION}" in result.error_message
    
    def test_corrupted_data(self):
        """Corrupted data should fail gracefully"""
        corrupted = b'not an image at all'
        result = validate_image(corrupted)
        
        assert result.is_valid == False
        assert "Invalid image" in result.error_message or "corrupted" in result.error_message.lower()
    
    def test_file_too_large(self):
        """File exceeding MAX_FILE_SIZE_MB should fail"""
        # Create data slightly over limit
        large_size_bytes = int((MAX_FILE_SIZE_MB + 0.1) * 1024 * 1024)
        large_data = b'x' * large_size_bytes
        
        result = validate_image(large_data)
        
        assert result.is_valid == False
        assert "too large" in result.error_message.lower()
        assert result.size_bytes == large_size_bytes
    
    def test_unsupported_format_gif(self):
        """GIF format should be rejected"""
        # Create a GIF image
        img = Image.new('RGB', (600, 600), color='purple')
        img_bytes = io.BytesIO()
        img.save(img_bytes, format='GIF')
        
        result = validate_image(img_bytes.getvalue())
        
        assert result.is_valid == False
        assert "Unsupported format" in result.error_message
        assert "GIF" in result.error_message
        assert result.format == 'GIF'
    
    def test_unsupported_format_bmp(self):
        """BMP format should be rejected"""
        # Create a BMP image
        img = Image.new('RGB', (600, 600), color='yellow')
        img_bytes = io.BytesIO()
        img.save(img_bytes, format='BMP')
        
        result = validate_image(img_bytes.getvalue())
        
        assert result.is_valid == False
        assert "Unsupported format" in result.error_message
        assert "BMP" in result.error_message
        assert result.format == 'BMP'
    
    def test_size_bytes_set_on_success(self, valid_jpeg_bytes):
        """size_bytes should be populated on successful validation"""
        result = validate_image(valid_jpeg_bytes)
        
        assert result.is_valid == True
        assert result.size_bytes is not None
        assert result.size_bytes == len(valid_jpeg_bytes)
        assert result.size_bytes > 0


# ============================================================================
# QUALITY ASSESSMENT TESTS
# ============================================================================

class TestQualityAssessment:
    """Test quality assessment logic"""
    
    def test_quality_metrics_present(self, valid_jpeg_bytes):
        """Quality metrics should be calculated and valid"""
        result = validate_image(valid_jpeg_bytes)
        
        assert result.is_valid == True
        
        # Check QualityMetrics structure
        quality = result.quality
        assert isinstance(quality, QualityMetrics)
        
        # All metrics should be in valid range [0, 1]
        assert 0.0 <= quality.overall <= 1.0
        assert 0.0 <= quality.sharpness <= 1.0
        assert 0.0 <= quality.brightness <= 1.0
        assert 0.0 <= quality.contrast <= 1.0
        
        # Issues should be a list
        assert isinstance(quality.issues, list)
    
    def test_solid_color_has_low_quality(self):
        """Solid color image should have low sharpness and contrast"""
        # Solid mid-gray: no edges, no contrast
        img = Image.new('RGB', (600, 600), color=(128, 128, 128))
        img_bytes = io.BytesIO()
        img.save(img_bytes, format='JPEG')
        
        result = validate_image(img_bytes.getvalue())
        
        assert result.is_valid == True
        
        # Solid color = very low sharpness (no edges)
        assert result.quality.sharpness < 0.3
        
        # Mid-gray = good brightness score
        assert result.quality.brightness > 0.7
        
        # Overall quality should be low
        assert result.quality.overall < 0.5
    
    def test_dark_image_detected(self):
        """Dark image should be flagged in issues"""
        # Very dark image
        img = Image.new('RGB', (600, 600), color=(10, 10, 10))
        img_bytes = io.BytesIO()
        img.save(img_bytes, format='JPEG')
        
        result = validate_image(img_bytes.getvalue())
        
        assert result.is_valid == True
        assert len(result.quality.issues) > 0
        assert any('dark' in issue.lower() for issue in result.quality.issues)
    
    def test_bright_image_detected(self):
        """Bright image should be flagged in issues"""
        # Very bright image
        img = Image.new('RGB', (600, 600), color=(250, 250, 250))
        img_bytes = io.BytesIO()
        img.save(img_bytes, format='JPEG')
        
        result = validate_image(img_bytes.getvalue())
        
        assert result.is_valid == True
        assert len(result.quality.issues) > 0
        assert any('bright' in issue.lower() for issue in result.quality.issues)
    
    def test_low_contrast_only(self):
        """Very low contrast image should be detected"""
        # Create image with minimal variation (almost flat)
        # Use very tight color range to guarantee low std dev
        base_color = 128
        variation = 3  # Only ±3 levels
        
        img = Image.new('RGB', (600, 600), color=(base_color, base_color, base_color))
        
        # Add minimal pattern (tiny contrast)
        draw = ImageDraw.Draw(img)
        for i in range(0, 600, 100):
            for j in range(0, 600, 100):
                # Alternate between 125 and 131 (6 levels difference)
                color = base_color - variation if (i + j) % 200 == 0 else base_color + variation
                draw.rectangle([i, j, i+50, j+50], fill=(color, color, color))
        
        img_bytes = io.BytesIO()
        img.save(img_bytes, format='JPEG', quality=95)  # High quality to preserve values
        
        result = validate_image(img_bytes.getvalue())
        
        assert result.is_valid == True
        
        # With only 6 gray levels variance, OpenCV std dev should be very low
        # Threshold 0.4 is generous (std of 6 levels over 255 range ≈ 0.02)
        assert result.quality.contrast < 0.4, (
            f"Expected low contrast for 6-level grayscale image, "
            f"but got contrast={result.quality.contrast:.2f}. "
            f"This might indicate JPEG compression artifacts or test image generation issue. "
            f"Full quality met"
            )

# ============================================================================
# HELPER FUNCTIONS TESTS
# ============================================================================

class TestHelperFunctions:
    """Test helper functions"""
    
    def test_is_quality_acceptable_above_threshold(self):
        """Quality above QUALITY_THRESHOLD should be acceptable"""
        # Create result with high quality
        result = ValidationResult(
            is_valid=True,
            quality=QualityMetrics(overall=0.8)
        )
        
        assert is_quality_acceptable(result) == True
    
    def test_is_quality_acceptable_below_threshold(self):
        """Quality below QUALITY_THRESHOLD should not be acceptable"""
        # Create result with low quality
        result = ValidationResult(
            is_valid=True,
            quality=QualityMetrics(overall=0.2)
        )
        
        assert is_quality_acceptable(result) == False
    
    def test_is_quality_acceptable_at_threshold(self):
        """Quality exactly at QUALITY_THRESHOLD should be acceptable"""
        from core.validator import QUALITY_THRESHOLD
        
        result = ValidationResult(
            is_valid=True,
            quality=QualityMetrics(overall=QUALITY_THRESHOLD)
        )
        
        assert is_quality_acceptable(result) == True
    
    def test_get_quality_feedback_no_issues(self):
        """Feedback for good quality should be positive"""
        result = ValidationResult(
            is_valid=True,
            quality=QualityMetrics(overall=0.9, issues=[])
        )
        
        feedback = get_quality_feedback(result)
        
        assert isinstance(feedback, str)
        assert "good" in feedback.lower()
    
    def test_get_quality_feedback_with_issues(self):
        """Feedback should list quality issues"""
        result = ValidationResult(
            is_valid=True,
            quality=QualityMetrics(
                overall=0.3,
                issues=["Image too blurry", "Low contrast"]
            )
        )
        
        feedback = get_quality_feedback(result)
        
        assert isinstance(feedback, str)
        assert "blurry" in feedback.lower()
        assert "contrast" in feedback.lower()


# ============================================================================
# EDGE CASES TESTS
# ============================================================================

class TestEdgeCases:
    """Test edge cases and boundary conditions"""
    
    def test_minimum_valid_resolution(self):
        """Exactly MIN_RESOLUTION should pass"""
        img = Image.new('RGB', (MIN_RESOLUTION, MIN_RESOLUTION), color='red')
        img_bytes = io.BytesIO()
        img.save(img_bytes, format='JPEG')
        
        result = validate_image(img_bytes.getvalue())
        
        assert result.is_valid == True
        assert result.resolution == (MIN_RESOLUTION, MIN_RESOLUTION)
    
    def test_one_pixel_below_resolution(self):
        """One pixel below MIN_RESOLUTION should fail"""
        size = MIN_RESOLUTION - 1
        img = Image.new('RGB', (size, MIN_RESOLUTION), color='red')
        img_bytes = io.BytesIO()
        img.save(img_bytes, format='JPEG')
        
        result = validate_image(img_bytes.getvalue())
        
        assert result.is_valid == False
        assert "Resolution too low" in result.error_message
    
    def test_empty_bytes(self):
        """Empty bytes should fail gracefully"""
        result = validate_image(b'')
        
        assert result.is_valid == False
        assert result.error_message is not None


# ============================================================================
# PYDANTIC FEATURES TESTS
# ============================================================================

class TestPydanticFeatures:
    """Test Pydantic-specific features"""
    
    def test_pydantic_rejects_out_of_bounds_overall(self):
        """Pydantic should reject quality scores outside [0, 1] range"""
        # Overall score > 1.0
        with pytest.raises(PydanticValidationError):
            QualityMetrics(overall=1.5)
        
        # Overall score < 0.0
        with pytest.raises(PydanticValidationError):
            QualityMetrics(overall=-0.1)
    
    def test_pydantic_rejects_out_of_bounds_sharpness(self):
        """Pydantic should reject sharpness outside [0, 1] range"""
        with pytest.raises(PydanticValidationError):
            QualityMetrics(sharpness=2.0)
        
        with pytest.raises(PydanticValidationError):
            QualityMetrics(sharpness=-0.5)
    
    def test_pydantic_rejects_out_of_bounds_brightness(self):
        """Pydantic should reject brightness outside [0, 1] range"""
        with pytest.raises(PydanticValidationError):
            QualityMetrics(brightness=1.1)
        
        with pytest.raises(PydanticValidationError):
            QualityMetrics(brightness=-0.01)
    
    def test_pydantic_rejects_out_of_bounds_contrast(self):
        """Pydantic should reject contrast outside [0, 1] range"""
        with pytest.raises(PydanticValidationError):
            QualityMetrics(contrast=3.0)
        
        with pytest.raises(PydanticValidationError):
            QualityMetrics(contrast=-1.0)
    
    def test_pydantic_accepts_boundary_values(self):
        """Pydantic should accept exact 0.0 and 1.0 values"""
        # Minimum boundary
        quality_min = QualityMetrics(
            overall=0.0,
            sharpness=0.0,
            brightness=0.0,
            contrast=0.0
        )
        assert quality_min.overall == 0.0
        
        # Maximum boundary
        quality_max = QualityMetrics(
            overall=1.0,
            sharpness=1.0,
            brightness=1.0,
            contrast=1.0
        )
        assert quality_max.overall == 1.0
    
    def test_pydantic_rejects_negative_size_bytes(self):
        """Pydantic should reject negative size_bytes"""
        with pytest.raises(PydanticValidationError):
            ValidationResult(
                is_valid=True,
                size_bytes=-1000
            )
    
    def test_json_serialization(self, valid_jpeg_bytes):
        """ValidationResult should be JSON-serializable"""
        result = validate_image(valid_jpeg_bytes)
        
        # Pydantic v2: .model_dump()
        json_data = result.model_dump()
        
        assert isinstance(json_data, dict)
        assert 'is_valid' in json_data
        assert 'quality' in json_data
        assert isinstance(json_data['quality'], dict)
    
    def test_json_serialization_preserves_structure(self, valid_jpeg_bytes):
        """JSON structure should match model structure"""
        result = validate_image(valid_jpeg_bytes)
        json_data = result.model_dump()
        
        # Check nested structure
        assert 'overall' in json_data['quality']
        assert 'sharpness' in json_data['quality']
        assert 'issues' in json_data['quality']


# Run with:
# pytest tests/test_validator.py -v
# pytest tests/test_validator.py --cov=core.validator --cov-report=term-missing
# pytest tests/test_validator.py --cov=core.validator --cov-report=html