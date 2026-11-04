"""Bounded, transient voice transcription. No local media archive."""
from __future__ import annotations
import json
import re
import secrets
import urllib.request
from .core import APIError


class VoiceRecognizer:
    def __init__(self, config, telegram):
        self.config, self.telegram = config, telegram

    def transcribe(self, media):
        if media.get('duration', 0) > self.config.voice_max_seconds or media.get('file_size', 0) > self.config.voice_max_bytes:
            raise APIError(413)
        data = self.telegram.download(media['file_id'], self.config.voice_max_bytes)
        boundary = 'pakostnik-' + secrets.token_hex(12)
        model = self.config.transcription_model
        if not re.fullmatch(r'[a-zA-Z0-9_.-]{1,100}', model):
            raise APIError(500)
        video = media.get('kind') == 'video_note'
        ext, mime = ('mp4', 'video/mp4') if video else ('ogg', 'audio/ogg')
        head = (f'--{boundary}\r\nContent-Disposition: form-data; name="model"\r\n\r\n{model}\r\n'
                f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="voice.{ext}"\r\nContent-Type: {mime}\r\n\r\n').encode()
        request = urllib.request.Request('https://api.openai.com/v1/audio/transcriptions',
            data=head + data + f'\r\n--{boundary}--\r\n'.encode(), headers={
                'Authorization': 'Bearer ' + self.config.openai_key,
                'Content-Type': 'multipart/form-data; boundary=' + boundary})
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read(65537)
            if len(raw) > 65536:
                raise APIError(502)
            result = json.loads(raw)
            text = result.get('text') if isinstance(result, dict) else None
            if not isinstance(text, str) or not 0 < len(text.strip()) <= 4000:
                raise APIError(502)
            return text.strip()
        except (OSError, ValueError, TypeError):
            raise APIError(502) from None
