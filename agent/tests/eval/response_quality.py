"""Local Gemini judge for the 1–5 response-quality rubric in eval_config.yaml."""

import sys
from pathlib import Path

# agents-cli compiles custom_function_file into a namespace without __file__.
sys.path.insert(0, str(Path.cwd() / "tests" / "eval"))
from quotation_eval_judge import judge


def evaluate(instance):
    return judge(instance, "custom_response_quality", minimum=1, maximum=5)
