import sys
import unittest.mock
if "tkinter" not in sys.modules:
    tk = unittest.mock.MagicMock()
    sys.modules["tkinter"] = tk
    sys.modules["tkinter.ttk"] = tk
    sys.modules["tkinter.Event"] = tk
if "mouseinfo" not in sys.modules:
    sys.modules["mouseinfo"] = unittest.mock.MagicMock()
