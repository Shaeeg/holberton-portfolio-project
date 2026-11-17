"""Bounded Telegram JPEG access through the authenticated operator API."""

import json
import re
from urllib.request import HTTPRedirectHandler, Request, build_opener

from telegram_flow import PHOTO_LIMIT


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def fetch_photo(token, file_id):
    if not re.fullmatch(r"[0-9]+:[A-Za-z0-9_-]+", token):
        raise ValueError("Invalid Telegram token")
    opener = build_opener(NoRedirect())
    base = "https://api.telegram.org"
    call = Request(f"{base}/bot{token}/getFile", json.dumps({"file_id": file_id}).encode(),
                   {"Content-Type": "application/json"})
    with opener.open(call, timeout=5) as response:
        result = json.loads(response.read(8192))
    path = result.get("result", {}).get("file_path", "")
    if not isinstance(path, str) or not re.fullmatch(r"photos/[A-Za-z0-9_-]+[.]jpg", path):
        raise ValueError("Unexpected Telegram file path")
    with opener.open(f"{base}/file/bot{token}/{path}", timeout=5) as response:
        content = response.read(PHOTO_LIMIT + 1)
    if len(content) > PHOTO_LIMIT or not (content.startswith(b"\xff\xd8\xff") and content.endswith(b"\xff\xd9")):
        raise ValueError("Invalid or oversized JPEG")
    return content
