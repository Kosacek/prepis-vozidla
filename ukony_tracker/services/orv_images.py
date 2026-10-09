"""Bounded, memory-only multipart uploads and image decoding."""
from io import BytesIO
import warnings

from flask import Request

MAX_IMAGE_BYTES = 8 * 1024 * 1024


class ScanRequest(Request):
    @property
    def max_content_length(self):
        if self.path == "/ukony/orv-sken":
            return MAX_IMAGE_BYTES + 64 * 1024  # multipart envelope
        return super().max_content_length

    def _get_file_stream(self, total_content_length, content_type, filename=None, content_length=None):
        if self.path == "/ukony/orv-sken":
            return BytesIO()  # Werkzeug's default spools large uploads to disk.
        return super()._get_file_stream(total_content_length, content_type, filename, content_length)


def sniff(data):
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[4:8] == b"ftyp":
        size = int.from_bytes(data[:4], "big")
        brands = [data[8:12]] + [data[i:i + 4] for i in range(16, min(size, len(data), 128), 4)]
        if any(b in (b"heic", b"heix", b"hevc", b"hevx") for b in brands):
            return "image/heic"
    raise ValueError("Vyberte fotku JPEG, PNG, WebP nebo HEIC.")


def prepare(data):
    """Verify actual pixels, orient, resize and strip metadata before vision."""
    media_type = sniff(data)
    from PIL import Image, ImageOps
    if media_type == "image/heic":
        from pillow_heif import register_heif_opener
        register_heif_opener()
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as source:
                if source.width * source.height > 50_000_000:
                    raise ValueError("Fotka má příliš velké rozlišení.")
                source.load()
                picture = ImageOps.exif_transpose(source)
                picture.thumbnail((1800, 1800))
                output = BytesIO()
                picture.convert("RGB").save(output, format="JPEG", quality=85)
                return output.getvalue(), "image/jpeg"
    except (OSError, SyntaxError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValueError("Fotku nelze otevřít. Vyfoťte ji znovu.") from exc
