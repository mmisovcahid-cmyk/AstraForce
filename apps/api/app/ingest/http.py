import os
import time
from pathlib import Path

import httpx


def make_client() -> httpx.Client:
    return httpx.Client(
        timeout=httpx.Timeout(60.0, connect=15.0),
        follow_redirects=True,
        headers={"User-Agent": "AstraForce-ingest/0.1"},
    )


def get_with_retry(client: httpx.Client, url: str, attempts: int = 4) -> httpx.Response:
    """Ağ hatası ve 5xx/429 yanıtlarında artan beklemeyle yeniden dener."""
    for i in range(attempts):
        try:
            res = client.get(url)
            if res.status_code < 500 and res.status_code != 429:
                return res
        except httpx.TransportError:
            if i == attempts - 1:
                raise
        time.sleep(2 ** (i + 1))
    return res


def download(client: httpx.Client, url: str, dest: Path) -> bool:
    """Dosyayı indirir (varsa atlar). 404 ise False döner."""
    if dest.exists() and dest.stat().st_size > 0:
        return True
    dest.parent.mkdir(parents=True, exist_ok=True)
    # Süreç başına ayrı geçici dosya: iki süreç aynı .part dosyasına yazıp çakışmasın.
    part = dest.with_suffix(f"{dest.suffix}.{os.getpid()}.part")
    for i in range(4):
        try:
            with client.stream("GET", url) as res:
                if res.status_code == 404:
                    return False
                res.raise_for_status()
                with part.open("wb") as f:
                    for chunk in res.iter_bytes(1 << 20):
                        f.write(chunk)
            part.replace(dest)
            return True
        except (httpx.TransportError, httpx.HTTPStatusError):
            if i == 3:
                raise
            time.sleep(2 ** (i + 1))
    return False
