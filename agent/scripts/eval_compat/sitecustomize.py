"""Activate only inside the wrapped CLI process, never an Agent subprocess."""

import os
import sys
from pathlib import Path

if os.getenv("EZSTORE_AI_STUDIO_EVAL") == "1" and (
    "google-agents-cli" in sys.prefix.lower()
    or Path(sys.argv[0]).name.lower().startswith("agents-cli")
):
    try:
        from ai_studio_eval import install

        install()
    except Exception as error:
        sys.stderr.write(f"AI Studio evaluation adapter failed to initialize: {type(error).__name__}\n")
        os._exit(2)
