"""Run tests with proper mocking."""

import sys
import os
from unittest.mock import MagicMock

# Add the parent directories to the Python path
# This is the key fix - add parent directories to sys.path
root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__))))))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

# IMPORTANT: Also create a custom_components reference at the root level
config_dir = os.path.join(root_dir, "config")
if not os.path.exists(os.path.join(root_dir, "custom_components")):
    # Create a symbolic link or reference
    sys.path.insert(0, config_dir)
    # Also create a virtual module mapping
    custom_components_dir = os.path.join(config_dir, "custom_components")
    sys.modules['custom_components'] = type('custom_components', (), {})()
    sys.modules['custom_components.uk_bin_collection'] = \
        __import__('config.custom_components.uk_bin_collection', fromlist=['uk_bin_collection'])

# Mocks must be defined before ANY imports happen
class MockUKBinCollectionApp:
    """Mock UKBinCollectionApp class."""
    def __init__(self, *args, **kwargs):
        pass
    def execute(self, *args, **kwargs):
        return {"bins": []}
    def set_args(self, args):
        pass
    def run(self):
        return '{"bins": []}'

# Apply mocks
sys.modules['uk_bin_collection'] = MagicMock()
sys.modules['uk_bin_collection.uk_bin_collection'] = MagicMock()
mock_data = MagicMock()
mock_data.UKBinCollectionApp = MockUKBinCollectionApp
sys.modules['uk_bin_collection.uk_bin_collection.collect_data'] = mock_data

# Get the current directory of this script
tests_dir = os.path.dirname(os.path.abspath(__file__))
if tests_dir not in sys.path:
    sys.path.insert(0, tests_dir)

# Now import pytest
import pytest

if __name__ == "__main__":
    # Get the test file from command line or use default
    test_file = sys.argv[1] if len(sys.argv) > 1 else "test_config_flow.py"
    
    # Configure pytest with coverage reporting
    pytest_args = [
        "-xvs",
        "--import-mode=importlib",
        "--cov=..",  # Coverage for parent directory
        "--cov-report=term",
        "--asyncio-mode=auto",  # Add this to handle asyncio warning
        test_file
    ]
    
    # Run pytest with the file
    sys.exit(pytest.main(pytest_args))