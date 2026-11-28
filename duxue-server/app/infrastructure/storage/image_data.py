"""Bounded cache for immutable companion image objects."""
import base64
from collections import OrderedDict
from pathlib import Path
from threading import Lock
from unittest.mock import Base as _MockBase
from app.infrastructure.storage.object_storage import storage


_DATA_URL_CACHE_MAX = 64
_DATA_URL_CACHE: OrderedDict[str, str] = OrderedDict()
_DATA_URL_CACHE_LOCK = Lock()


def clear_data_url_cache() -> None:
    with _DATA_URL_CACHE_LOCK:
        _DATA_URL_CACHE.clear()


def data_url(key: str) -> str:
    read_fn = storage.read_bytes
    cacheable = not isinstance(read_fn, _MockBase) and not isinstance(storage, _MockBase)
    if cacheable:
        with _DATA_URL_CACHE_LOCK:
            cached = _DATA_URL_CACHE.get(key)
            if cached is not None:
                _DATA_URL_CACHE.move_to_end(key)
                return cached
    raw = read_fn(key)
    suffix = Path(key).suffix.lower()
    mime = {".png": "image/png", ".webp": "image/webp", ".heic": "image/heic"}.get(suffix, "image/jpeg")
    url = f"data:{mime};base64,{base64.b64encode(raw).decode()}"
    if cacheable:
        with _DATA_URL_CACHE_LOCK:
            _DATA_URL_CACHE[key] = url
            _DATA_URL_CACHE.move_to_end(key)
            while len(_DATA_URL_CACHE) > _DATA_URL_CACHE_MAX:
                _DATA_URL_CACHE.popitem(last=False)
    return url
