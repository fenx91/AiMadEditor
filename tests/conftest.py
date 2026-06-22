import sys
import pytest

@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_protocol(item, nextitem):
    # Let the test run
    yield
    # After each test, if the next test is in a different module, clean up sys.modules
    if nextitem is None or item.module != nextitem.module:
        for key in ["torch", "torch.nn", "torch.nn.functional", "transformers"]:
            if key in sys.modules:
                # If it's a MagicMock, remove it so it doesn't pollute subsequent imports
                val = sys.modules[key]
                if hasattr(val, "_mock_return_value") or "MagicMock" in str(type(val)):
                    del sys.modules[key]
