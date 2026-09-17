import sys, os

# ── PythonAnywhere — account: house45 ──
PROJECT_HOME = '/home/house45/pie_scheduler'
if PROJECT_HOME not in sys.path:
    sys.path.insert(0, PROJECT_HOME)

os.chdir(PROJECT_HOME)

from app import app as application
