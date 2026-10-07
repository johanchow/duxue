"""阿里云标准语音合成。只朗读调用方给出的已确认原文。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import time
import uuid
from urllib.parse import quote, urlencode

from app.bootstrap.settings import settings

VOICE_BY_LOCALE = {
    "en-US": "betty",
    "en-GB": "emily",
}
SPEECH_RATE_BY_PLAYBACK = {
    0.5: -500,
    0.75: -167,
    1.0: 0,
}
ENGINE_VERSION = "aliyun-isi-tts-v1"
MAX_TTS_CHARS = 300


class SpeechSynthesisError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def playback_speech_rate(rate: float) -> int:
    for playback, speech_rate in SPEECH_RATE_BY_PLAYBACK.items():
        if abs(playback - rate) < 1e-6:
            return speech_rate
    raise SpeechSynthesisError("unsupported_rate")


def _percent(value: str) -> str:
    return quote(str(value), safe="-_.~")


def create_token_query(*, access_key_id: str, access_key_secret: str, nonce: str, timestamp: str) -> str:
    params = {
        "AccessKeyId": access_key_id,
        "Action": "CreateToken",
        "Format": "JSON",
        "RegionId": "cn-shanghai",
        "SignatureMethod": "HMAC-SHA1",
        "SignatureNonce": nonce,
        "SignatureVersion": "1.0",
        "Timestamp": timestamp,
        "Version": "2019-02-28",
    }
    canonical = "&".join(f"{_percent(key)}={_percent(params[key])}" for key in sorted(params))
    string_to_sign = f"GET&{_percent('/')}&{_percent(canonical)}"
    digest = hmac.new(f"{access_key_secret}&".encode(), string_to_sign.encode(), hashlib.sha1).digest()
    params["Signature"] = base64.b64encode(digest).decode()
    return urlencode(params)


class AliyunSpeechSynthesizer:
    """按 locale 登记音色合成。缓存键不含 Ward，值只由原文、音色和倍速决定。"""

    def __init__(self, transport=None, clock=None, *, appkey: str | None = None, access_key_id: str | None = None, access_key_secret: str | None = None):
        self._transport = transport
        self._clock = clock or time.time
        self._appkey = settings.tts_appkey if appkey is None else appkey
        self._access_key_id = settings.oss_access_key_id if access_key_id is None else access_key_id
        self._access_key_secret = settings.oss_access_key_secret if access_key_secret is None else access_key_secret
        self._token = ""
        self._token_deadline = 0.0
        self._cache: dict[str, bytes] = {}

    def synthesize(self, *, text: str, locale: str, rate: float) -> bytes:
        voice = VOICE_BY_LOCALE.get(locale)
        if voice is None:
            raise SpeechSynthesisError("unsupported_locale")
        if len(text) > MAX_TTS_CHARS:
            raise SpeechSynthesisError("text_too_long")
        speech_rate = playback_speech_rate(rate)
        if not self._appkey or not self._access_key_id or not self._access_key_secret:
            raise SpeechSynthesisError("not_configured")
        key = hashlib.sha256(
            f"{text}|{locale}|{voice}|{speech_rate}|{ENGINE_VERSION}".encode()
        ).hexdigest()
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        try:
            audio = self._request(text=text, voice=voice, speech_rate=speech_rate)
        except SpeechSynthesisError:
            raise
        except Exception as error:
            raise SpeechSynthesisError("tts_error") from error
        self._cache[key] = audio
        return audio

    def _request(self, *, text: str, voice: str, speech_rate: int) -> bytes:
        token = self._access_token()
        payload = {
            "appkey": self._appkey,
            "text": text,
            "format": "mp3",
            "sample_rate": 16000,
            "voice": voice,
            "volume": 50,
            "speech_rate": speech_rate,
            "pitch_rate": 0,
        }
        status, content_type, body = self._post(settings.tts_gateway_url, token, payload)
        if status != 200 or "audio" not in content_type.lower() or not body:
            raise SpeechSynthesisError("tts_error")
        return body

    def _access_token(self) -> str:
        now = self._clock()
        if self._token and now < self._token_deadline:
            return self._token
        query = create_token_query(
            access_key_id=self._access_key_id,
            access_key_secret=self._access_key_secret,
            nonce=str(uuid.uuid4()),
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
        )
        status, content_type, body = self._get(f"{settings.tts_token_url}?{query}")
        if status != 200:
            raise SpeechSynthesisError("tts_error")
        import json
        try:
            payload = json.loads(body)
            token = payload["Token"]["Id"]
            expire = int(payload["Token"]["ExpireTime"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise SpeechSynthesisError("tts_error") from error
        self._token = token
        self._token_deadline = min(expire - 60, now + 12 * 3600)
        return token

    def _post(self, url: str, token: str, payload: dict) -> tuple[int, str, bytes]:
        if self._transport is not None:
            return self._transport("POST", url, token, payload)
        import httpx
        response = httpx.post(
            url, json=payload, headers={"X-NLS-Token": token}, timeout=8.0,
        )
        return response.status_code, response.headers.get("content-type", ""), response.content

    def _get(self, url: str) -> tuple[int, str, bytes]:
        if self._transport is not None:
            return self._transport("GET", url, "", None)
        import httpx
        response = httpx.get(url, timeout=8.0)
        return response.status_code, response.headers.get("content-type", ""), response.content
