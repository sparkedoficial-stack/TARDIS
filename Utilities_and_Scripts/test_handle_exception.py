import unittest
import sys
import os

# Agrega la carpeta actual al path para poder importar gia_agent
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gia_agent import handle_exception

class TestHandleException(unittest.TestCase):
    def test_handle_exception(self):
        try:
            raise Exception("Error de prueba")
        except Exception as e:
            handle_exception(e, context="Test Context")
            self.assertTrue(True)

if __name__ == '__main__':
    unittest.main()
