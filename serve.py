#!/usr/bin/env python3
"""ローカル確認用サーバー (Range対応)。python3 build.py の後に python3 serve.py → http://localhost:8000

python3 -m http.server は Range リクエスト非対応で、音声のシークが効かず再生位置に戻ってしまう。
Cloudflare Pages は Range に対応しているため、本番ではこの問題は起きない。
"""
import os
import re
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

DIST = Path(__file__).resolve().parent / "dist"


class Handler(SimpleHTTPRequestHandler):
    _left = None

    def end_headers(self):
        self.send_header("Accept-Ranges", "bytes")
        super().end_headers()

    def send_head(self):
        rng = self.headers.get("Range")
        path = self.translate_path(self.path)
        m = re.match(r"bytes=(\d*)-(\d*)$", rng or "")
        if not m or not (m.group(1) or m.group(2)) or not os.path.isfile(path):
            return super().send_head()
        size = os.path.getsize(path)
        if m.group(1):
            start = int(m.group(1))
            end = int(m.group(2)) if m.group(2) else size - 1
        else:  # bytes=-N (末尾N バイト)
            start, end = max(size - int(m.group(2)), 0), size - 1
        end = min(end, size - 1)
        if start > end:
            self.send_error(416)
            return None
        f = open(path, "rb")
        f.seek(start)
        self._left = end - start + 1
        self.send_response(206)
        self.send_header("Content-Type", self.guess_type(path))
        self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Length", str(self._left))
        self.end_headers()
        return f

    def copyfile(self, src, dst):
        try:
            if self._left is None:
                return super().copyfile(src, dst)
            while self._left > 0:
                chunk = src.read(min(65536, self._left))
                if not chunk:
                    break
                dst.write(chunk)
                self._left -= len(chunk)
            self._left = None
        except (BrokenPipeError, ConnectionResetError):
            pass  # シーク時にブラウザが接続を切るのは正常


if __name__ == "__main__":
    print("http://localhost:8000  (Ctrl+C で終了)")
    ThreadingHTTPServer(("", 8000), partial(Handler, directory=str(DIST))).serve_forever()
