"""Initialize plotting before Qt; retain complete startup errors for diagnosis."""
import sys
import tempfile
import traceback
import faulthandler
from pathlib import Path

_runtime_log = open(Path(tempfile.gettempdir(), 'mir-cleanup-runtime.log'), 'a', buffering=1, encoding='utf-8')
sys.stdout = _runtime_log
sys.stderr = _runtime_log
faulthandler.enable(_runtime_log)

def startup_error(kind, value, tb):
    Path(tempfile.gettempdir(), 'mir-cleanup-startup-error.log').write_text(''.join(traceback.format_exception(kind,value,tb)), encoding='utf-8')
    sys.__excepthook__(kind,value,tb)

sys.excepthook = startup_error
import matplotlib.figure
import dateutil.rrule
