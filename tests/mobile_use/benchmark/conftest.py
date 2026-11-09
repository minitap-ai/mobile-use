"""Two pre-existing test modules (agents/outputter/test_outputter.py, tools/test_utils.py) put
Mock objects in sys.modules at import time for the whole session (graph.state, langchain_*).
These tests import the real graph, so drop any leftover Mock module before they are collected.
"""

import sys
from unittest.mock import Mock

for _name, _module in list(sys.modules.items()):
    if isinstance(_module, Mock):
        del sys.modules[_name]
