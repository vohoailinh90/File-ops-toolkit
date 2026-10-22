# layout: entry-point
"""Start File Ops Toolkit: `python app.py` opens the web UI; `python app.py run LIST.xlsx DEST` runs without it."""

import sys

from file_ops_toolkit.cli import main

if __name__ == "__main__":
    sys.exit(main())
