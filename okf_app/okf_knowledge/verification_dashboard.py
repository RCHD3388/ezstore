"""Separate read-only Stage 4 dashboard for an explicitly selected saved report."""

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

WEB = Path(__file__).resolve().parent / "verification_web"


def load_report(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    checks = data.get("checks")
    if not isinstance(checks, list) or not checks or any(
        not isinstance(item.get("passed"), bool) for item in checks
    ):
        raise ValueError("Verification report has no valid check results.")
    data["passed"] = all(check["passed"] for check in checks)
    return data


def create_server(report_path, host="127.0.0.1", port=8021):
    report_path = Path(report_path).resolve()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def send(self, status, content, kind="application/json"):
            body = content.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", kind + "; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; "
                             "style-src 'self'; connect-src 'self'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = urlsplit(self.path).path
            if path == "/favicon.ico":
                return self.send(204, "")
            assets = {"/": ("index.html", "text/html"), "/dashboard.js": ("dashboard.js", "text/javascript"),
                      "/dashboard.css": ("dashboard.css", "text/css")}
            if path in assets:
                name, kind = assets[path]
                return self.send(200, (WEB / name).read_text(encoding="utf-8"), kind)
            if path == "/api/report":
                try:
                    return self.send(200, json.dumps(load_report(report_path), ensure_ascii=False))
                except (OSError, ValueError, TypeError):
                    return self.send(503, json.dumps({"error": "A valid saved verification report is unavailable."}))
            return self.send(404, json.dumps({"error": "Not found"}))

        def reject_write(self):
            self.send_response(405)
            self.send_header("Allow", "GET")
            self.send_header("Content-Length", "0")
            self.end_headers()
            self.close_connection = True

        do_POST = do_PUT = do_PATCH = do_DELETE = reject_write

    return ThreadingHTTPServer((host, port), Handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8021)
    args = parser.parse_args()
    server = create_server(args.report, port=args.port)
    print(f"Stage 4 verification dashboard: http://127.0.0.1:{server.server_port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
