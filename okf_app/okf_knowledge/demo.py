"""Local GET-only interactive OKF demo; no external service or model calls."""

import argparse
import json
import re
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from markdown_it import MarkdownIt

from .consumer import DEFAULT_BUNDLE, InvalidBundle, KnowledgeConsumer

STATIC = Path(__file__).resolve().parent / "web"


def render_markdown(text):
    # Provenance is displayed separately; retain the original Markdown in JSON.
    display = re.sub(r"^\[\^[^\]]+\]:.*$", "", text, flags=re.MULTILINE)
    display = re.sub(r"\[\^[^\]]+\]", "", display)
    return MarkdownIt("commonmark", {"html": False}).enable("table").render(display)


def create_server(host="127.0.0.1", port=8020, bundle_root=DEFAULT_BUNDLE):
    consumer = KnowledgeConsumer(bundle_root)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass  # Do not log user questions, query strings, or credentials.

        def send(self, status, body, content_type="application/json; charset=utf-8"):
            data = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy",
                             "default-src 'self'; script-src 'self'; style-src 'self'; "
                             "connect-src 'self'; img-src 'self'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(data)

        def json(self, status, data):
            self.send(status, json.dumps(data, ensure_ascii=False))

        def do_GET(self):
            request = urlsplit(self.path)
            params = parse_qs(request.query)
            try:
                assets = {"/": ("index.html", "text/html"),
                          "/app.js": ("app.js", "text/javascript"),
                          "/style.css": ("style.css", "text/css")}
                if request.path in assets:
                    name, kind = assets[request.path]
                    return self.send(200, (STATIC / name).read_text(encoding="utf-8"), kind + "; charset=utf-8")
                if request.path == "/api/concepts":
                    return self.json(200, consumer.concepts())
                if request.path == "/api/ask":
                    question = params.get("question", [""])[0].strip()
                    if not question or len(question) > 1000:
                        return self.json(400, {"error": "Enter a question of 1-1000 characters."})
                    answer = asdict(consumer.answer(question))
                    answer["answer_html"] = render_markdown(answer["markdown"])
                    return self.json(200, answer)
                if request.path == "/api/document":
                    document = consumer.document(params.get("name", [""])[0])
                    return self.json(200, {"document": document.path, "body": document.body,
                                           "title": document.metadata.get("title", document.path),
                                           "body_html": render_markdown(document.body)})
                return self.json(404, {"error": "Not found"})
            except KeyError:
                self.json(404, {"error": "Unknown bundle concept"})
            except InvalidBundle as exc:
                self.json(503, {"error": str(exc)})

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
    parser.add_argument("--port", type=int, default=8020)
    parser.add_argument("--bundle", type=Path, default=DEFAULT_BUNDLE)
    args = parser.parse_args()
    server = create_server(port=args.port, bundle_root=args.bundle)
    print(f"EZStore OKF demo: http://127.0.0.1:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
