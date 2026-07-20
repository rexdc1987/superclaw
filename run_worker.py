"""Run the Windows Hongguo execution worker."""

import os
import sys


sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from rpa.hongguo.worker import HongguoWorker


if __name__ == "__main__":
    HongguoWorker().run()
