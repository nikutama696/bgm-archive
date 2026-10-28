#!/usr/bin/env python3
"""data/ を走査して dist/ を生成する (Cloudflare Pages 用・静的出力のみ)。

ファイル名の規則:  ジャンル_タイトル.mp3   例) edm_neon-city.mp3 → ジャンル "edm"
"_" が無いファイルはジャンル "other" になります。

使い方:
  python3 build.py                    # dist/ を生成
  SITE_URL=https://example.pages.dev python3 build.py   # llms.txt を絶対URLにする
"""
import html
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
DIST = ROOT / "dist"
EXTS = {".mp3", ".wav", ".ogg", ".m4a", ".flac", ".aac"}
PAGES_LIMIT = 25 * 1024 * 1024  # Cloudflare Pages: 1ファイル25MBまで
SITE_URL = os.environ.get("SITE_URL", "").rstrip("/")
SITE_TITLE = "Nikutama BGM Stock"

def _load_mutagen():
    """再生時間の取得に使う。無ければ自動でインストールする (Cloudflareのビルド環境用)。"""
    try:
        from mutagen import File
        return File
    except ImportError:
        pass
    try:  # システムのPythonを汚さないよう、一時フォルダに入れる
        target = tempfile.mkdtemp()
        subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "--target", target, "mutagen"], check=True)
        sys.path.insert(0, target)
        from mutagen import File
        return File
    except Exception:
        print("[警告] mutagen を用意できなかったため、再生時間は表示されません")
        return None


MutagenFile = _load_mutagen()


def get_duration(path):
    if MutagenFile is None:
        return None
    try:
        f = MutagenFile(path)
        return round(f.info.length) if f is not None and f.info else None
    except Exception:
        return None


def scan():
    tracks = []
    if not DATA.is_dir():
        return tracks
    for p in sorted(DATA.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in EXTS:
            continue
        rel = p.relative_to(DATA).as_posix()
        genre, sep, rest = p.stem.partition("_")
        if not sep or not genre or not rest:
            genre, rest = "other", p.stem
        size = p.stat().st_size
        if size > PAGES_LIMIT:
            print(f"[警告] 25MB超: {rel} ({size / 1048576:.1f}MB) → Cloudflare Pagesにはアップできません")
        tracks.append({
            "file": rel,
            "title": rest.replace("_", " "),
            "genre": genre.lower(),
            "size": size,
            "duration": get_duration(p),
            "url": "data/" + urllib.parse.quote(rel),
        })
    return tracks


def main():
    tracks = scan()
    genres = {}
    for t in tracks:
        genres[t["genre"]] = genres.get(t["genre"], 0) + 1
    genres = dict(sorted(genres.items()))

    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir()
    if DATA.is_dir():
        shutil.copytree(DATA, DIST / "data")

    # index.json (人間用UI・AIエージェント共通の目録)
    index = {
        "title": SITE_TITLE,
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "count": len(tracks),
        "genres": genres,
        "terms": {
            "url": "terms.html",
            "license": "Stability AI Community License",
            "commercial_use": True,
            "modification": True,
            "credit": "optional",
            "redistribution_or_resale": False,
            "content_id_registration": False,
            "ai_training": False,
        },
        "tracks": tracks,
    }
    (DIST / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")

    # index.html (JS非対応クローラー向けに静的リンク一覧を埋め込む)
    items = "\n".join(
        f'<li><a href="{html.escape(t["url"])}">{html.escape(t["title"])}</a> [{html.escape(t["genre"])}]</li>'
        for t in tracks
    )
    page = (ROOT / "index.html").read_text(encoding="utf-8").replace("<!--STATIC_LIST-->", items)
    (DIST / "index.html").write_text(page, encoding="utf-8")

    # 利用規約・ファビコン
    for name in ("terms.html", "favicon.svg", "icon.png", "ogp.png"):
        src = ROOT / name
        if src.exists():
            shutil.copy(src, DIST / name)
        else:  # 1ファイルの置き忘れでデプロイ全体が失敗しないようにする
            print(f"[警告] {name} がリポジトリにありません (スキップ)")

    # llms.txt (AIエージェント向けの案内)
    base = SITE_URL + "/" if SITE_URL else ""
    lines = [
        f"# {SITE_TITLE}",
        "",
        "> BGM音源のアーカイブ。全曲の一覧は index.json (JSON) にまとまっています。",
        "",
        f"- 目録: {base}index.json",
        "- ファイル名の規則: ジャンル_タイトル.拡張子 (例: edm_neon-city.mp3 → ジャンル edm)",
        f"- 曲数: {len(tracks)} / ジャンル: {', '.join(f'{g}({n})' for g, n in genres.items()) or 'なし'}",
        "",
        "## 利用規約 (必ず確認してください)",
        f"- 規約全文: {base}terms.html",
        "- 音源はStability AI Community Licenseに基づき生成・編集されたAI音源",
        "- OK: 商用利用 / 加工・編集 / クレジット表記は任意",
        "- NG: 音源ファイル自体の再配布・転売 / YouTube Content ID等への登録 / 生成AI・機械学習モデルの学習への利用 / 違法・公序良俗に反する用途 / 他者の権利を侵害する表現",
        "- AIエージェントによる検索・試聴・ダウンロードは可。ただし学習データとしての利用は不可",
        "- Powered by Stability AI",
        "",
        "## Tracks",
    ]
    lines += [f"- [{t['genre']}] {t['title']}: {base}{t['url']}" for t in tracks]
    (DIST / "llms.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    # _headers (目録と音源を外部サイト・エージェントからも取得できるように)
    (DIST / "_headers").write_text(
        "/index.json\n  Access-Control-Allow-Origin: *\n  Cache-Control: no-cache\n"
        "/llms.txt\n  Access-Control-Allow-Origin: *\n"
        "/data/*\n  Access-Control-Allow-Origin: *\n",
        encoding="utf-8",
    )

    print(f"{len(tracks)} 曲 / ジャンル {len(genres)} 種 → {DIST}")


if __name__ == "__main__":
    main()
