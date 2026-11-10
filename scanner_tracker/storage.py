"""Content-addressed, compressed input archives; credentials never enter reports."""
from __future__ import annotations

import gzip
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import quote

import requests

from .repository import clean
from .security import secret_value


class InputArchive:
    def __init__(self, local_directory=None, url=None, key=None, bucket="tracker-inputs"):
        self.directory = Path(local_directory) if local_directory else None
        self.url, self.key, self.bucket = url, key, bucket
        if self.directory:
            self.directory.mkdir(parents=True, exist_ok=True)
        elif not (url and key):
            raise ValueError("Private input storage is not configured. Set SUPABASE_URL and SUPABASE_SERVICE_KEY.")

    @classmethod
    def from_env(cls, *, local_directory=None):
        if local_directory is not None:
            return cls(local_directory=local_directory)
        return cls(url=secret_value("SUPABASE_URL"), key=secret_value("SUPABASE_SERVICE_KEY"),
                   bucket=secret_value("TRACKER_STORAGE_BUCKET", "tracker-inputs"))

    def _validate(self, key):
        if len(key) != 72 or not key.endswith(".json.gz") or any(c not in "0123456789abcdef" for c in key[:64]):
            raise ValueError("Invalid input archive key.")

    def _request(self, method, path, **kwargs):
        try:
            response = requests.request(method, self.url.rstrip("/") + path,
                headers={"Authorization": f"Bearer {self.key}", "apikey": self.key, **kwargs.pop("headers", {})},
                timeout=(10, 60), **kwargs)
        except requests.RequestException as exc:
            raise RuntimeError("Private input storage is unreachable.") from exc
        if response.status_code not in (200, 201):
            raise RuntimeError(f"Private input storage request failed (HTTP {response.status_code}).")
        return response

    def put(self, value):
        raw = json.dumps(clean(value), sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        key = hashlib.sha256(raw).hexdigest() + ".json.gz"
        encoded = gzip.compress(raw, mtime=0)
        self.last_put_bytes = len(encoded)
        self.put_bytes(key, encoded)
        return key

    def put_bytes(self, key, data):
        self._validate(key)
        raw = gzip.decompress(data)
        if hashlib.sha256(raw).hexdigest() != key[:64]:
            raise ValueError("Input archive checksum mismatch.")
        if self.directory:
            target = self.directory / key
            if not target.exists():
                temporary = self.directory / (key + ".tmp")
                temporary.write_bytes(data)
                os.replace(temporary, target)
        else:
            self._request("POST", f"/storage/v1/object/{quote(self.bucket, safe='')}/{key}", data=data,
                          headers={"Content-Type": "application/gzip", "x-upsert": "true"})

    def get_bytes(self, key):
        self._validate(key)
        if self.directory:
            data = (self.directory / key).read_bytes()
        else:
            data = self._request("GET", f"/storage/v1/object/{quote(self.bucket, safe='')}/{key}").content
        if hashlib.sha256(gzip.decompress(data)).hexdigest() != key[:64]:
            raise ValueError("Input archive checksum mismatch.")
        return data

    def get(self, key):
        return json.loads(gzip.decompress(self.get_bytes(key)))
