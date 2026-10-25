"""Project-scoped agents-cli wrapper; never modifies the installed CLI or SDK."""

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv


def main():
    agent_dir = Path(__file__).resolve().parents[1]
    load_dotenv(agent_dir / ".env", override=False)
    load_dotenv(agent_dir.parent / ".env", override=False)
    command, *args = sys.argv[1:]
    env = os.environ.copy()
    env["AGENTS_CLI_DISABLE_OVERRIDES"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["PYTHONWARNINGS"] = "ignore::FutureWarning"
    studio = env.get("GOOGLE_GENAI_USE_VERTEXAI", "").lower() != "true" and bool(
        env.get("GEMINI_API_KEY") or env.get("GOOGLE_API_KEY")
    )
    if studio:
        compat_dir = str(agent_dir / "scripts" / "eval_compat")
        env["PYTHONPATH"] = os.pathsep.join(filter(None, [compat_dir, env.get("PYTHONPATH")]))
        env["EZSTORE_AI_STUDIO_EVAL"] = "1"
        print("AI Studio eval: original rubrics, real Gemini judges, native SDK reports; no ADC required.", flush=True)
        if command == "run" and env.get("EZSTORE_EVAL_RESUME"):
            from eval_resume import reuse_guardrails

            if reuse_guardrails(args, env["EZSTORE_EVAL_RESUME"]):
                return 0
    if command == "run" and not any(arg.startswith("--concurrency") for arg in args):
        args += ["--concurrency", "1"]
    if not any(arg.startswith("--qps") for arg in args):
        # Keep unfinished cases about 20 seconds apart for Gemini free-tier quota.
        args += ["--qps", "0.05"]
    logs = agent_dir / "artifacts" / "eval_runs"
    logs.mkdir(parents=True, exist_ok=True)
    path = logs / f"{datetime.now():%Y%m%d_%H%M%S}_{os.getpid()}.log"
    with path.open("w", encoding="utf-8") as log:
        with subprocess.Popen(
            ["agents-cli", "eval", command, *args], cwd=agent_dir, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
        ) as process:
            for line in process.stdout:
                for key in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
                    if env.get(key):
                        line = line.replace(env[key], "[redacted]")
                log.write(line)
                log.flush()
                print(line, end="", flush=True)
            return process.wait()


if __name__ == "__main__":
    raise SystemExit(main())
