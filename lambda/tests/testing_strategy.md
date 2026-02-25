# Testing Strategy

**Last Updated:** 2026-02-18
**Overall Coverage:** 94% (Unit Tests) | 82% (Integration Tests gegen gesamten Core)

---

## Coverage by Module

| Module | Tests | Coverage | Missing Lines | Status |
|--------|-------|----------|---------------|--------|
| `core/validator.py` | 28 | 98% | 2 | ✅ Excellent |
| `core/inference.py` | 27 | 91% | 5 | ✅ Good |
| `core/storage.py` | 18 | 100% | 0 | ✅ Perfect |
| `core/handler.py` | 47 | 94% | 7 | ✅ Excellent |
| **Integration** | **19** | **82% gesamt** | - | ✅ Good |
| **Gesamt** | **139** | | | |

---

## Test-Typen und Abgrenzung

### Unit Tests
Jeder Bounded Context wird isoliert getestet. Alle externen Abhängigkeiten
(DynamoDB, ONNX Model) werden gemockt.

```
test_validator.py   → validator.py isoliert (OpenCV Quality Check)
test_inference.py   → inference.py isoliert (ONNX Model)
test_storage.py     → storage.py isoliert (DynamoDB gemockt)
test_handler.py     → handler.py isoliert (alle Contexts gemockt)
```

### Integration Tests
Nur externe Services gemockt (DynamoDB, ONNX). Die Bounded Contexts
interagieren für real miteinander.

```
test_integration.py → validator + handler + storage laufen gemeinsam
                      Beweist: Contexts funktionieren korrekt zusammen
```

**Warum beide Typen?**
Unit Tests finden Bugs innerhalb eines Contexts.
Integration Tests finden Bugs an den Context-Grenzen —
z.B. falsches Datenformat zwischen Validator und Handler.

---

## Warum nicht 100% Coverage?

### core/validator.py (98% — 2 Lines fehlen)
**Fehlende Lines:** Seltene Quality-Kombination (hoher Sharpness + sehr niedriger Contrast)  
**Entscheidung:** Kombination tritt in der Praxis kaum auf. Komplexes Test-Setup ohne Mehrwert.

---

### core/inference.py (91% — 5 Lines fehlen)

**Lines 63-64: InferenceError re-raise**
```python
except InferenceError:
    raise  # Not covered
```
Pass-through Error Handling ohne eigene Logik — kein Test-Mehrwert.

**Line 102: Model file not found (second fallback)**
```python
if not model_path.exists():
    raise InferenceError("Model not found")
```
Catch-22: Test wird per `skipif` übersprungen wenn Model fehlt.

**Lines 112-113: ONNX loading exception**
```python
except Exception as e:
    raise InferenceError(f"Failed to load model: {e}")
```
Würde corrupt `.onnx` File erfordern — brittle, kein realer Mehrwert.

---

### core/handler.py (94% — 7 Lines fehlen)
**Fehlende Lines:** 175-176, 214-215, 257-258, 291  
**Ursache:** Seltene Exception-Kombinationen in den Route Handlers
(z.B. unexpected Exception nach bereits gecatchtem StorageError).  
**Entscheidung:** Alle realistischen Error-Paths sind getestet. Die fehlenden
7 Lines sind defensive `except Exception` Fallbacks.

---

## Testing Philosophy

**Ziel:** Hohes Vertrauen in Production-Verhalten, nicht 100% Line Coverage.

**Prioritäten:**
1. ✅ Alle user-facing Functions getestet
2. ✅ Alle Happy Paths getestet
3. ✅ Alle realistischen Error Cases getestet
4. ✅ Business Rules explizit getestet (Override-Logik, Quality Threshold)
5. ✅ patch() targets sind immer Import-Ort, nicht Definitions-Ort
6. ❌ Impossible/extrem seltene Error-Kombinationen NICHT getestet

**Industry Standard:**
- 70–80% = Acceptable
- 80–90% = Good
- 90%+ = Excellent
- 100% = Usually over-engineering

---

## Test Execution

### Alle Tests
```powershell
pytest tests/ -v
```

### Mit Coverage (Unit)
```powershell
pytest tests/test_validator.py --cov=core.validator --cov-report=term-missing
pytest tests/test_inference.py --cov=core.inference --cov-report=term-missing
pytest tests/test_storage.py --cov=core.storage --cov-report=term-missing
pytest tests/test_handler.py --cov=core.handler --cov-report=term-missing
```

### Mit Coverage (Integration)
```powershell
pytest tests/test_integration.py --cov=core --cov-report=term-missing
```

### Gesamt Coverage
```powershell
pytest tests/ --cov=core --cov-report=term-missing
pytest tests/ --cov=core --cov-report=html  # → htmlcov/index.html
```

### HTML Report
```powershell
pytest tests/ --html=test-report.html --self-contained-html
```

---

## Test Structure

```
tests/
├── conftest.py                 # sys.path config (Python path fix)
├── fixtures/
│   └── test_car_damage.jpg     # Echtes Schadenbild für Integration Tests
├── test_validator.py           # 28 tests, 98% coverage
├── test_inference.py           # 27 tests, 91% coverage
├── test_storage.py             # 18 tests, 100% coverage
├── test_handler.py             # 47 tests, 94% coverage
└── test_integration.py        # 19 tests, 82% gesamt coverage
```

---

## Key Design Decisions

### Echtes Testbild statt synthetischem
Einfarbige Bilder (z.B. `Image.new("RGB", ..., color="red")`) haben
Sharpness=0 und Contrast=0 und fallen durch den echten Quality Check.
`tests/fixtures/test_car_damage.jpg` wird automatisch auf ≥512x512
resized falls nötig.

### Dunkles Bild für Quality-Rejection-Tests
```python
def make_dark_image_base64() -> str:
    img = Image.new("RGB", (600, 600), color=(5, 5, 5))
```
Explizit dunkles Bild — garantiert `QUALITY_TOO_LOW`, kein Zufall.

### patch() Regel: Import-Ort, nicht Definitions-Ort
```python
# ❌ Greift nicht — handler hat eigene Referenz
patch("core.inference.predict_damage")

# ✅ Ersetzt die Referenz wo sie verwendet wird
patch("core.handler.predict_damage")
```

### TestWithRealModel als optionaler Smoke Test
```python
@pytest.mark.skipif(
    not Path("models/car_damage_v1.onnx").exists(),
    reason="ONNX model not available"
)
def test_real_inference_processing_time_under_2s(self, mock_dynamodb):
    assert duration_ms < 2000  # p95 Latenz-Anforderung
```
Läuft nur wenn ONNX Model vorhanden — wird in CI automatisch übersprungen
wenn kein Model verfügbar.

---

## CI/CD Integration

**GitHub Actions läuft bei jedem Push:**
- Alle Unit Tests müssen bestehen
- Coverage ≥ 90% (Unit Tests)
- Model-abhängige Tests werden übersprungen (kein ONNX in CI)

---

## Future Improvements

**Short-term:**
- Load Tests (locust) für p95/p99 Latenz unter Last
- Performance Benchmarks

**Long-term:**
- Contract Tests (API Schema Validation)
- Mutation Testing (prüft ob Tests wirklich Bugs finden)