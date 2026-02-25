# In lambda/ folder

import sys
from pathlib import Path

# Add lambda/ directory to Python path
lambda_dir = Path(__file__).parent.parent
sys.path.insert(0, str(lambda_dir))

print(f"[conftest.py] Added to path: {lambda_dir}")