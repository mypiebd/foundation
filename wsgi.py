"""WSGI entry point for PythonAnywhere."""

import os
import sys

PROJECT_HOME = os.path.dirname(os.path.abspath(__file__))
if PROJECT_HOME not in sys.path:
    sys.path.insert(0, PROJECT_HOME)

# Set a real secret before going live:
#   os.environ["LMS_SECRET_KEY"] = "some-long-random-string"

from app import app as application  # noqa: E402
