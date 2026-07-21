"""Photo handling — resize, validate, and upload to eBay Picture Service."""

import base64
import hashlib
from pathlib import Path
from typing import List, Optional

import requests
from PIL import Image
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

console = Console()

MAX_IMAGE_SIZE_MB = 7
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".bmp"}
MAX_DIMENSION = 8000


class Photo:
    """Wraps a single product photo."""

    def __init__(self, path: Path):
        self.path = path
        self._validate()

    def _validate(self):
        if not self.path.exists():
            raise FileNotFoundError(f"Photo not found: {self.path}")
        if self.path.suffix.lower() not in ALLOWED_EXTENSIONS:
            raise ValueError(f"Unsupported format: {self.path.suffix}")
        size_mb = self.path.stat().st_size / (1024 * 1024)
        if size_mb > MAX_IMAGE_SIZE_MB:
            raise ValueError(f"Photo too large ({size_mb:.1f} MB). Max {MAX_IMAGE_SIZE_MB} MB")
        with Image.open(self.path) as img:
            if max(img.size) > MAX_DIMENSION:
                raise ValueError(f"Image dimensions {img.size} exceed max {MAX_DIMENSION}px")

    @property
    def name(self) -> str:
        return self.path.name


def photo_size_ok(path: Path) -> bool:
    """Quick check without full PIL load."""
    return path.stat().st_size <= MAX_IMAGE_SIZE_MB * 1024 * 1024


def resize_photo(path: Path, output_dir: Optional[Path] = None, max_width: int = 1600) -> Path:
    """Resize photo to max_width while maintaining aspect ratio (eBay recommended)."""
    img = Image.open(path)
    if max(img.size) <= max_width:
        return path  # No resize needed

    ratio = max_width / max(img.size)
    new_size = (int(img.width * ratio), int(img.height * ratio))
    img = img.resize(new_size, Image.LANCZOS)

    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)
        out = output_dir / path.name
    else:
        out = path.parent / f"{path.stem}_resized{path.suffix}"

    img.save(out, optimize=True)
    return out


def batch_resize(photo_paths: List[Path], output_dir: Path, max_width: int = 1600) -> List[Path]:
    """Resize multiple photos in batch."""
    results = []
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("[cyan]Resizing photos...", total=len(photo_paths))
        for p in photo_paths:
            try:
                resized = resize_photo(p, output_dir, max_width)
                results.append(resized)
            except Exception as e:
                console.print(f"[red]✗ {p.name}: {e}[/red]")
            progress.advance(task)
    return results


# ── eBay Picture Service Upload ──────────────────────────────────

EBAY_EPS_UPLOAD_URL = "https://api.ebay.com/developer/upload/v1/media/file"
EBAY_EPS_SANDBOX_URL = "https://api.sandbox.ebay.com/developer/upload/v1/media/file"

EPS_SITE_MAP = {
    "AU": "0",
    "US": "0",
    "GB": "3",
    "DE": "77",
    "FR": "71",
}


class PictureService:
    """Upload photos to eBay Picture Service (EPS)."""

    def __init__(self, access_token: str, sandbox: bool = False):
        self.access_token = access_token
        self.base_url = EBAY_EPS_SANDBOX_URL if sandbox else EBAY_EPS_UPLOAD_URL

    def upload(self, photo_path: Path, site_id: str = "0") -> Optional[str]:
        """Upload a single photo, returns the full URL on success."""
        with open(photo_path, "rb") as f:
            files = {"file": (photo_path.name, f, "image/jpeg")}
            headers = {
                "Authorization": f"Bearer {self.access_token}",
                "X-EBAY-API-SITEID": site_id,
            }
            resp = requests.post(self.base_url, headers=headers, files=files)

        if resp.status_code in (200, 201):
            data = resp.json()
            return data.get("baselineImageUrl") or data.get("imageUrl")
        elif resp.status_code == 400:
            console.print(f"[yellow]EPS upload failed (400) for {photo_path.name}: {resp.text[:200]}[/yellow]")
            return None
        else:
            console.print(f"[red]EPS upload error {resp.status_code} for {photo_path.name}[/red]")
            return None

    def upload_many(self, photo_paths: List[Path], site_id: str = "0") -> List[str]:
        """Upload multiple photos, return list of URLs."""
        urls = []
        with Progress() as progress:
            task = progress.add_task("[cyan]Uploading photos to eBay...", total=len(photo_paths))
            for p in photo_paths:
                url = self.upload(p, site_id)
                if url:
                    urls.append(url)
                progress.advance(task)
        return urls


def encode_photo_base64(path: Path) -> str:
    """Encode photo as base64 (used in some eBay API endpoints)."""
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()


def photo_hash(path: Path) -> str:
    """MD5 hash for deduplication."""
    return hashlib.md5(path.read_bytes()).hexdigest()
