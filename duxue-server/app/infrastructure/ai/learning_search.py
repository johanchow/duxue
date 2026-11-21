"""Bounded, turn-local retrieval. IQS returns source pages and third-party image URLs."""
from __future__ import annotations

import asyncio
import hashlib
import io
import ipaddress
import socket
import time

import httpx
from jsonschema import Draft202012Validator
from PIL import Image, ImageOps

from app.agent_specs.web_search import CONTRACT
from app.bootstrap.settings import settings


async def _fetch(mode, params, token):
    async with httpx.AsyncClient() as client:
        endpoint = "multimodal" if mode == "image" else "unified"
        response = await client.post(
            f"https://cloud-iqs.aliyuncs.com/search/{endpoint}", json=params,
            headers={"Authorization": f"Bearer {token}"},
        )
        response.raise_for_status()
        body = response.json()
        field = "imageItems" if mode == "image" else "pageItems"
        if not isinstance(body, dict) or not isinstance(body.get(field), list):
            raise httpx.DecodingError("missing IQS results", request=response.request)
        return body[field]


def _https_url(value):
    if not isinstance(value, str) or len(value) > 8192:
        return None
    try:
        url = httpx.URL(value)
        if url.scheme in {"http", "https"} and url.host and not url.userinfo and url.port is None:
            return url.copy_with(scheme="https")
    except httpx.InvalidURL:
        pass
    return None


async def _download_image(url):
    # Connect to the validated IP, keeping the original host for TLS and HTTP.
    # Each redirect gets its own client and DNS check.
    for _ in range(3):
        target = _https_url(url)
        if target is None:
            raise ValueError("invalid image URL")
        host = target.raw_host.decode("ascii")
        addresses = await asyncio.get_running_loop().getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        ips = [ipaddress.ip_address(row[4][0]) for row in addresses]
        if not ips or any(not ip.is_global or ip.is_multicast or ip.is_reserved for ip in ips):
            raise ValueError("non-public image destination")
        async with httpx.AsyncClient(trust_env=False) as client, client.stream(
            "GET", target.copy_with(host=str(ips[0])), headers={"Host": target.netloc.decode("ascii")},
            extensions={"sni_hostname": host},
        ) as response:
            if response.has_redirect_location:
                url = str(target.join(response.headers["location"]))
                continue
            response.raise_for_status()
            data = bytearray()
            async for chunk in response.aiter_bytes():
                data.extend(chunk)
                if len(data) > 8 * 1024 * 1024:
                    raise ValueError("oversized image file")
            return data
    raise ValueError("too many image redirects")


async def _thumbnail(url):
    data = await _download_image(url)
    with Image.open(io.BytesIO(data), formats=["JPEG", "PNG", "WEBP"]) as image:
        if image.width * image.height > 20_000_000:
            raise ValueError("oversized image")
        image.thumbnail((640, 640))
        output = io.BytesIO()
        ImageOps.exif_transpose(image).convert("RGB").save(output, format="JPEG", quality=82)
        return output.getvalue()


class LearningSearch:
    def __init__(self):
        self.deadline = None
        self.image_requested = False
        self.calls = 0
        self.photos = {}
        self.cached = {}
        self.failed_photos = set()

    def search(self, args):
        if not Draft202012Validator(CONTRACT["input_schema"]).is_valid(args):
            return {"status": "invalid_request"}
        if not args["query"].strip() or not args["learning_purpose"].strip():
            return {"status": "invalid_request"}
        self.image_requested |= args["mode"] == "image"
        if not settings.iqs_api_key:
            return {"status": "unavailable"}
        now = time.monotonic()
        if self.deadline is None:
            self.deadline = now + settings.search_budget_ms / 1000
        remaining = self.deadline - now
        if self.calls >= 2 or remaining <= 0 or (self.calls and remaining < 0.1):
            return {"status": "budget_exhausted"}
        self.calls += 1
        mode = args["mode"]
        count = args.get("count", 3)
        params = {"query": args["query"], "advancedParams": {"numResults": str(count)},
                  "engineType": "MultimodalSpeed" if mode == "image" else "LiteAdvanced"}
        try:
            rows = asyncio.run(asyncio.wait_for(_fetch(mode, params, settings.iqs_api_key), remaining))
        except (TimeoutError, httpx.TimeoutException):
            return {"status": "timeout"}
        except (httpx.HTTPError, ValueError):
            return {"status": "unavailable"}
        matches = []
        for row in rows[:count]:
            if not isinstance(row, dict):
                continue
            page = _https_url(row.get("hostPageUrl" if mode == "image" else "link"))
            title = str(row.get("title") or "")[:250]
            if not page or len(str(page)) > 2048 or not title:
                continue
            source = str(page)
            item = {"title": title, "source": source, "excerpt": str(row.get("snippet") or "")[:450]}
            if row.get("publishedTime"):
                item["published_time"] = str(row["publishedTime"])[:64]
            if mode == "image":
                image = _https_url(row.get("imageUrl"))
                if image is None:
                    continue
                url = str(image)
                ref = hashlib.sha256((source + url).encode()).hexdigest()[:24]
                self.photos[ref] = (url, source, title)
                item["photo_ref"] = ref
            matches.append(item)
        return {"status": "found" if matches else "no_match", "results": matches}

    def photo(self, ref):
        if not isinstance(ref, str) or ref not in self.photos:
            raise ValueError("unknown photo_ref")
        if ref in self.failed_photos:
            raise ValueError("thumbnail unavailable")
        if ref not in self.cached:
            url, source, title = self.photos[ref]
            try:
                data = asyncio.run(asyncio.wait_for(_thumbnail(url), timeout=2.5))
            except (TimeoutError, httpx.HTTPError, httpx.InvalidURL, Image.DecompressionBombError, OSError, ValueError) as error:
                self.failed_photos.add(ref)
                raise ValueError("thumbnail unavailable") from error
            self.cached[ref] = (source, title, data)
        return self.cached[ref]
