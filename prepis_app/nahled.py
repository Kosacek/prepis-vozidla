"""Náhledy stránek PDF jako PNG — pro sdílenou stránku /<kód>.

Proč obrázky a ne vložené PDF: v iframu Chrome ukazuje PDF stísněně a
rozbitě (viz CLAUDE.md, zkoušeno dvakrát) a Android Chrome vložené PDF
neukáže vůbec — stáhne ho. Obrázek stránky se ukáže všude stejně, takže
protějšek nejdřív VIDÍ, co tiskne, a teprve pak otevře samotné PDF.

PDFium vykreslí i vyplněná pole formuláře (init_forms), takže náhled
odpovídá tomu, co vyjede z tiskárny. Na NASu (ARM) trvá stránka zlomek
sekundy; posledních pár náhledů drží cache v paměti, ať se rozcestník při
návratu nevykresluje znovu.
"""
from __future__ import annotations

import io
import logging
import os
import threading
from functools import lru_cache

_log = logging.getLogger(__name__)

# 144 DPI: A4 vyjde ~1190 × 1680 px. Na počítači se stránka ukazuje na celou
# výšku okna (s Windows škálováním 125–150 % to je ~1300 px), při 100 DPI
# byl text rozmazaný.
MERITKO = 144 / 72
MAX_STRAN = 12  # víc stránek žádný z našich dokumentů nemá; brzda proti nesmyslům

# PDFium není vláknově bezpečné (gunicorn běží s vlákny i workery).
_zamek = threading.Lock()


def _klic(cesta: str) -> tuple[str, float]:
    return cesta, os.path.getmtime(cesta)


@lru_cache(maxsize=64)
def _pocet(cesta: str, _mtime: float) -> int:
    import pypdfium2 as pdfium
    with _zamek:
        pdf = pdfium.PdfDocument(cesta)
        try:
            return min(len(pdf), MAX_STRAN)
        finally:
            pdf.close()


@lru_cache(maxsize=32)
def _png(cesta: str, _mtime: float, strana: int) -> bytes:
    import pypdfium2 as pdfium
    with _zamek:
        pdf = pdfium.PdfDocument(cesta)
        try:
            pdf.init_forms()
            stranka = pdf[strana - 1]
            obrazek = stranka.render(scale=MERITKO, may_draw_forms=True).to_pil()
        finally:
            pdf.close()
    buf = io.BytesIO()
    obrazek.convert("L").save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def pocet_stran(cesta: str) -> int:
    """Kolik stran má smysl ukázat; 0 = náhled nejde (rozbité PDF, chyba)."""
    try:
        return _pocet(*_klic(cesta))
    except Exception as e:
        _log.warning("náhled: nejde otevřít %s: %s", os.path.basename(cesta), e)
        return 0


def stranka_png(cesta: str, strana: int) -> bytes | None:
    """PNG jedné stránky (číslováno od 1), nebo None když taková není."""
    if not 1 <= strana <= pocet_stran(cesta):
        return None
    try:
        return _png(*_klic(cesta), strana)
    except Exception as e:
        _log.warning("náhled: nejde vykreslit %s/%d: %s", os.path.basename(cesta), strana, e)
        return None
