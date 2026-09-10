"""Semua logic kecil untuk Phase 1 berada di satu file ini.

Bayangkan file ini seperti satu kotak alat. Di dalamnya ada alat untuk:

- mengenali data produk dari HTML;
- mengambil halaman website;
- mengumpulkan hasil dan error;
- memeriksa data dengan Pydantic;
- menyimpan sample ke JSON;
- menjalankan percobaan dari terminal.

Kita sengaja membuatnya satu file karena Phase 1 masih berupa POC kecil.
Jika project nanti menjadi lebih besar, file ini bisa dipecah lagi.
"""

import argparse
import csv
import json
import re
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from xml.etree import ElementTree
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import urlencode, urljoin, urlparse

import requests
import truststore
from bs4 import BeautifulSoup
from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, field_validator, model_validator


# Python bawaan Windows kadang tidak memakai certificate store Windows. Ini
# membuat requests mengikuti certificate store sistem, sama seperti browser.
truststore.inject_into_ssl()


# Tiga kategori yang sengaja kita samakan di semua retailer.
#
# Satu registry ini adalah tempat utama untuk mengubah URL dan strategi.
# Smoke test memakai ``smoke_url``. Pengambilan berulang nanti memakai
# ``discovery`` dan ``discovery_url`` jika source memilikinya.
CATEGORY_IDS = ("smartphone", "tablet", "laptop")

SOURCE_CONFIG = {
    "eraspace": {
        "smartphone": {
            "smoke_url": "https://eraspace.com/eraspace/katalog/mobile-phones/smartphones-24",
            "discovery": "sitemap",
            "discovery_url": "https://eraspace.com/sitemap/eraspace/mobile-phones-23.xml",
        },
        "tablet": {
            "smoke_url": "https://eraspace.com/eraspace/katalog/tablet-403",
            "discovery": "sitemap",
            "discovery_url": "https://eraspace.com/sitemap/eraspace/tablet-403.xml",
        },
        "laptop": {
            "smoke_url": "https://eraspace.com/eraspace/katalog/computer/laptop-141",
            "discovery": "sitemap",
            "discovery_url": "https://eraspace.com/sitemap/eraspace/computer-140.xml",
        },
    },
    "electronic_city": {
        "smartphone": {
            "smoke_url": "https://eci.id/category/handphone-dan-tablet?sort=best-selling",
            "discovery": "product_suggestions_api",
            "discovery_url": "https://eci.id/api/product-suggestions",
            "search_query": "smartphone",
        },
        "tablet": {
            "smoke_url": "https://eci.id/category/handphone-dan-tablet?sort=best-selling",
            "discovery": "product_suggestions_api",
            "discovery_url": "https://eci.id/api/product-suggestions",
            "search_query": "tablet",
        },
        "laptop": {
            "smoke_url": "https://eci.id/category/laptop-dan-gaming?sort=best-selling",
            "discovery": "product_suggestions_api",
            "discovery_url": "https://eci.id/api/product-suggestions",
            "search_query": "laptop",
        },
    },
    "digimap": {
        "smartphone": {
            "smoke_url": "https://www.digimap.co.id/pages/view-all-iphone",
            "discovery": "shopify_sitemap",
            "discovery_url": "https://www.digimap.co.id/sitemap.xml",
        },
        "tablet": {
            "smoke_url": "https://www.digimap.co.id/pages/view-all-ipad",
            "discovery": "shopify_sitemap",
            "discovery_url": "https://www.digimap.co.id/sitemap.xml",
        },
        "laptop": {
            "smoke_url": "https://www.digimap.co.id/pages/view-all-mac",
            "discovery": "shopify_sitemap",
            "discovery_url": "https://www.digimap.co.id/sitemap.xml",
        },
    },
    "erablue": {
        "smartphone": {
            "smoke_url": "https://www.erablue.id/handphone",
            "discovery": "category_listing",
        },
        "tablet": {
            "smoke_url": "https://www.erablue.id/tablet",
            "discovery": "category_listing",
        },
        "laptop": {
            "smoke_url": "https://www.erablue.id/laptop",
            "discovery": "category_listing",
        },
    },
}


# Kompatibilitas sementara untuk CLI lama yang belum menerima --category.
# Nilainya dibuat dari registry, jadi URL tidak ditulis ulang di dua tempat.
SOURCE_CATEGORIES = {
    source_id: categories["smartphone"]["smoke_url"]
    for source_id, categories in SOURCE_CONFIG.items()
}


def dispatch_source_category(source_id: str, category_id: str) -> dict[str, Any]:
    """Memilih aturan pengambilan untuk satu kombinasi retailer-kategori.

    WHY:
        Empat retailer tidak memakai cara discovery yang sama. Dispatcher ini
        menjadi pintu masuk tunggal agar caller tidak menebak-nebak aturan.

    INPUT:
        ``source_id`` seperti ``eraspace`` dan ``category_id`` seperti
        ``tablet``.

    PROCESS:
        Cari dua nama tersebut di ``SOURCE_CONFIG`` dan salin aturan penting
        ke sebuah rencana kecil.

    OUTPUT:
        Dictionary berisi source, kategori, strategi, URL smoke test, dan URL
        discovery jika source memilikinya. Belum ada request jaringan.

    FAILURE CASE:
        Source atau kategori yang tidak dikenal menghasilkan ``ValueError``.
    """
    categories = SOURCE_CONFIG.get(source_id)
    if categories is None:
        raise ValueError(f"unsupported source_id: {source_id}")
    category = categories.get(category_id)
    if category is None:
        raise ValueError(f"unsupported category_id: {category_id}")
    return {
        "source_id": source_id,
        "category_id": category_id,
        "strategy": category["discovery"],
        "smoke_url": category["smoke_url"],
        "discovery_url": category.get("discovery_url"),
        "category_hint": category.get("category_hint"),
        "search_query": category.get("search_query"),
    }


# Setiap toko bisa memiliki bentuk link produk yang berbeda.
SOURCE_PATH_PATTERNS = {
    "erablue": re.compile(r"^/[^?#]+/[^?#]+", re.I),
    "eraspace": re.compile(r"^/eraspace/produk/[^?#]+", re.I),
    "digimap": re.compile(r"^/products/[^?#]+", re.I),
    "electronic_city": re.compile(r"^/product/\d+/detail/?$", re.I),
}


# Nama ini memberi tahu website bahwa request berasal dari POC read-only.
USER_AGENT = "PortfolioSmokeTest/1.0 (+read-only public catalogue POC)"


class RawProductObservation(BaseModel):
    """Satu hasil pengamatan produk yang sudah diperiksa.

    WHY:
        Semua toko harus menghasilkan bentuk data yang sama agar mudah
        dibandingkan.

    INPUT:
        Data dari parser: nama, harga, link, stok, dan waktu pengambilan.

    OUTPUT:
        Object observation yang aman dipakai oleh collection dan storage.

    FAILURE CASE:
        URL salah, nama kosong, harga negatif, waktu tanpa timezone, atau
        harga normal lebih rendah daripada harga jual akan ditolak.
    """

    # Field tambahan yang tidak dikenal akan ditolak. Ini mencegah typo diam-diam.
    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(min_length=2)
    # Kategori berasal dari runner, bukan dari HTML produk. Default ini hanya
    # dipakai bila parser dipanggil sendirian di test atau eksperimen kecil.
    category_id: str = Field(default="UNSPECIFIED", min_length=2)
    source_product_id: str | None = None
    source_url: AnyHttpUrl
    product_name_raw: str = Field(min_length=2)
    current_price_idr: Decimal | None = None
    original_price_idr: Decimal | None = None
    availability_status_raw: str | None = None
    observed_at_utc: datetime
    location_context: str = "UNSPECIFIED"

    @field_validator("current_price_idr", "original_price_idr")
    @classmethod
    def prices_must_be_non_negative(cls, value: Decimal | None) -> Decimal | None:
        """Menolak harga negatif karena harga produk tidak boleh minus."""
        if value is not None and value < 0:
            raise ValueError("price cannot be negative")
        return value

    @field_validator("observed_at_utc")
    @classmethod
    def timestamp_must_be_timezone_aware(cls, value: datetime) -> datetime:
        """Menyamakan semua waktu menjadi UTC agar waktu antar-source konsisten."""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("observed_at_utc must include a timezone")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def original_price_cannot_be_below_current(self) -> "RawProductObservation":
        """Memastikan harga normal tidak lebih murah dari harga saat ini."""
        if (
            self.current_price_idr is not None
            and self.original_price_idr is not None
            and self.original_price_idr < self.current_price_idr
        ):
            raise ValueError("original_price_idr cannot be below current_price_idr")
        return self


@dataclass(frozen=True)
class CollectionResult:
    """Kotak hasil collection: data berhasil dan masalahnya disimpan bersama."""

    source_id: str
    category_url: str
    observed_at_utc: datetime
    discovered_product_urls: list[str]
    observations: list[RawProductObservation]
    errors: list[dict[str, str]]


@dataclass(frozen=True)
class SmokeRunResult:
    """Satu laporan kecil untuk satu retailer dan satu kategori.

    WHY:
        ``CollectionResult`` tahu cara mengambil produk, tetapi belum tahu
        kategori bisnis yang dipilih. Kotak ini menambahkan konteks tersebut
        agar 12 hasil tidak tertukar.

    INPUT:
        Rencana source, hasil collection, waktu, dan status hasil.

    OUTPUT:
        Satu object yang siap disimpan sebagai bukti smoke test.

    FAILURE CASE:
        Bila website gagal diambil, ``status`` menjadi ``FAILED`` dan alasan
        kegagalan tetap disimpan pada ``errors``.
    """

    source_id: str
    category_id: str
    strategy: str
    smoke_url: str
    observed_at_utc: datetime
    discovered_product_urls: list[str]
    observations: list[RawProductObservation]
    errors: list[dict[str, str]]
    status: str
    price_valid_count: int


def _jsonld_products(soup: BeautifulSoup) -> list[dict[str, Any]]:
    """Mengambil product object dari script JSON-LD jika ada.

    JSON-LD adalah data terstruktur yang biasanya lebih mudah dibaca daripada
    teks visual. Script yang rusak dilewati supaya produk lain tetap dicoba.
    """
    products: list[dict[str, Any]] = []
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            value = json.loads(script.string or script.get_text())
        except (TypeError, json.JSONDecodeError):
            continue
        candidates = value if isinstance(value, list) else [value]
        for candidate in candidates:
            if isinstance(candidate, dict) and (
                candidate.get("@type") == "Product" or "offers" in candidate
            ):
                products.append(candidate)
    return products


def _first_jsonld_product(soup: BeautifulSoup) -> dict[str, Any]:
    """Mengambil product JSON-LD pertama, atau kotak kosong jika tidak ada."""
    products = _jsonld_products(soup)
    return products[0] if products else {}


def _price(value: Any) -> Decimal | None:
    """Mengubah tulisan harga rupiah menjadi angka.

    Contoh: ``Rp 3.599.000`` menjadi ``3599000``. Jika tidak ada angka,
    hasilnya ``None`` agar parser dapat mencoba sumber harga lain.
    """
    if value is None:
        return None
    if isinstance(value, (int, float, Decimal)):
        return Decimal(str(value)).quantize(Decimal("1"))
    digits = re.sub(r"[^0-9]", "", str(value))
    return Decimal(digits) if digits else None


def _offer(product: dict[str, Any]) -> dict[str, Any]:
    """Menyederhanakan offer yang bisa berbentuk list atau dictionary."""
    offers = product.get("offers", {})
    if isinstance(offers, list):
        return offers[0] if offers else {}
    return offers if isinstance(offers, dict) else {}


def _next_data_product(soup: BeautifulSoup) -> dict[str, Any]:
    """Mengambil data produk Eraspace dari script ``__NEXT_DATA__``.

    Jika script tidak ada atau isinya rusak, kembalikan kotak kosong agar
    parser dapat mencoba JSON-LD atau teks halaman.
    """
    node = soup.find("script", id="__NEXT_DATA__")
    if node is None:
        return {}
    try:
        payload = json.loads(node.string or node.get_text())
    except (TypeError, json.JSONDecodeError):
        return {}
    data = payload.get("props", {}).get("pageProps", {}).get("data", {})
    return data if isinstance(data, dict) else {}


def _eraspace_availability(product: dict[str, Any]) -> str | None:
    """Mengubah beberapa tanda stok Eraspace menjadi satu status sederhana."""
    quantity = product.get("qty")
    stock_status = product.get("stock_status")
    store_stock_status = product.get("store_stock_status")
    if quantity is not None and quantity > 0:
        return "IN_STOCK"
    if stock_status == 1:
        return "IN_STOCK"
    if store_stock_status == 1:
        return "STORE_STOCK"
    if quantity is not None or stock_status is not None or store_stock_status is not None:
        return "OUT_OF_STOCK"
    return None


def _source_product_id(source_id: str, source_url: str, product: dict[str, Any]) -> str | None:
    """Mencari ID produk dengan aturan yang sesuai untuk setiap toko."""
    path = urlparse(source_url).path.rstrip("/")
    if source_id == "electronic_city":
        match = re.search(r"/product/(\d+)/detail", path, re.I)
        return match.group(1) if match else None
    if product.get("sku"):
        return str(product["sku"])
    return path.rsplit("/", 1)[-1] or None


def _visible_text(soup: BeautifulSoup, selector: str) -> str | None:
    """Mengambil tulisan dari bagian HTML tertentu, jika bagian itu ada."""
    node = soup.select_one(selector)
    return node.get_text(" ", strip=True) if node else None


def _visible_price(soup: BeautifulSoup) -> Decimal | None:
    """Mencari harga dari tulisan biasa sebagai jalan cadangan."""
    body_text = soup.get_text(" ", strip=True)
    match = re.search(r"Rp\.?\s*([0-9][0-9.]*)", body_text, re.I)
    return _price(match.group(1)) if match else None


def parse_product_html(
    source_id: str,
    source_url: str,
    html: str,
    observed_at_utc: datetime,
) -> RawProductObservation:
    """Mengubah satu halaman produk menjadi satu observation.

    WHY:
        Setiap toko menyusun halaman dengan cara berbeda. Fungsi ini membuat
        hasil akhirnya memiliki bentuk yang sama.

    INPUT:
        Nama toko, URL produk, HTML halaman, dan waktu pengambilan.

    PROCESS:
        Coba data Next.js, lalu JSON-LD, lalu tulisan HTML biasa. Setelah itu
        ambil nama, harga, stok, ID produk, dan minta Pydantic memeriksa hasil.

    OUTPUT:
        Satu ``RawProductObservation``.

    FAILURE CASE:
        Nama tidak ditemukan, tipe data rusak, atau hasil tidak lolos aturan
        Pydantic akan menghasilkan error untuk dicatat oleh collection.
    """
    soup = BeautifulSoup(html, "html.parser")
    next_product = _next_data_product(soup)
    product = next_product or _first_jsonld_product(soup)
    offer = _offer(product)
    name = product.get("name") or _visible_text(soup, "h1") or _visible_text(soup, "title")
    if not name:
        raise ValueError(f"{source_id}: product name was not found")

    current_price = _price(offer.get("price"))
    original_price = None
    if next_product:
        base_price = _price(next_product.get("price"))
        special_price = _price(next_product.get("special_price"))
        current_price = special_price or base_price
        if base_price is not None and current_price is not None and base_price > current_price:
            original_price = base_price
    if current_price is None:
        current_price = _price(_visible_text(soup, ".price, .sale-price, [data-price]"))
    if current_price is None:
        current_price = _visible_price(soup)
    if original_price is None:
        original_price = _price(_visible_text(soup, ".original-price, .compare-at-price"))

    availability = _eraspace_availability(next_product) if next_product else None
    if availability is None:
        availability = _visible_text(soup, ".availability, [data-availability]")
    if availability is None:
        stock_match = re.search(
            r"Stok\s+(?:habis|tersedia)!?", soup.get_text(" ", strip=True), re.I
        )
        availability = stock_match.group(0) if stock_match else None
    if availability is None and offer.get("availability"):
        availability = str(offer["availability"]).rsplit("/", 1)[-1]

    return RawProductObservation(
        source_id=source_id,
        source_product_id=_source_product_id(source_id, source_url, product),
        source_url=source_url,
        product_name_raw=str(name),
        current_price_idr=current_price,
        original_price_idr=original_price,
        availability_status_raw=availability,
        observed_at_utc=observed_at_utc,
    )


def _jsonld_products_from_collection(soup: BeautifulSoup) -> list[dict[str, Any]]:
    """Mencari Product yang tersembunyi di dalam CollectionPage atau ItemList."""
    found: list[dict[str, Any]] = []

    def visit(value: Any) -> None:
        """Berjalan ke bagian JSON yang lebih dalam sampai menemukan Product."""
        if isinstance(value, dict):
            if value.get("@type") == "Product" and value.get("url"):
                found.append(value)
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    for script in soup.select('script[type="application/ld+json"]'):
        try:
            visit(json.loads(script.string or script.get_text()))
        except (TypeError, json.JSONDecodeError):
            continue
    return found


def discover_product_urls(
    source_id: str, category_url: str, html: str, limit: int = 10
) -> list[str]:
    """Mencari link produk dari halaman daftar toko.

    WHY:
        Halaman daftar toko biasanya berisi banyak jenis link. Kita hanya ingin
        link yang benar-benar menuju produk dari toko yang sama.

    INPUT:
        Nama toko, alamat halaman daftar, isi HTML, dan jumlah maksimum link.

    PROCESS:
        Cari link di JSON-LD dulu, lalu cari link HTML biasa. Buang link dari
        domain lain, link yang bukan pola produk, dan link duplikat.

    OUTPUT:
        Daftar link produk, paling banyak sebanyak ``limit``.

    FAILURE CASE:
        Nama toko yang tidak dikenal menghasilkan error. Halaman tanpa link
        produk menghasilkan daftar kosong, bukan error program.
    """
    pattern = SOURCE_PATH_PATTERNS.get(source_id)
    if pattern is None:
        raise ValueError(f"unsupported source_id: {source_id}")
    category_host = urlparse(category_url).netloc.lower()
    result: list[str] = []
    soup = BeautifulSoup(html, "html.parser")

    for product in _jsonld_products_from_collection(soup):
        absolute = urljoin(category_url, str(product["url"]))
        parsed = urlparse(absolute)
        if parsed.netloc.lower() == category_host and pattern.match(parsed.path):
            normalized = absolute.split("#", 1)[0]
            if normalized not in result:
                result.append(normalized)
                if len(result) >= limit:
                    return result

    for anchor in soup.select("a[href]"):
        absolute = urljoin(category_url, anchor["href"])
        parsed = urlparse(absolute)
        if parsed.netloc.lower() != category_host or not pattern.match(parsed.path):
            continue
        normalized = absolute.split("#", 1)[0]
        if normalized not in result:
            result.append(normalized)
        if len(result) >= limit:
            break
    return result


def parse_sitemap_xml(xml: str) -> tuple[list[str], list[str]]:
    """Membaca satu file sitemap tanpa tergantung pada nama namespace XML.

    WHY:
        Sitemap Eraspace terdiri dari dua bentuk file: index yang menunjuk ke
        sitemap lain, dan urlset yang berisi link produk. Kita perlu tahu
        bedanya agar bisa mengikuti seluruh katalog.

    INPUT:
        Teks XML dari satu sitemap.

    PROCESS:
        Baca setiap elemen ``sitemap`` dan ``url``, lalu ambil isi ``loc``.

    OUTPUT:
        Dua daftar: ``(child_sitemap_urls, product_or_urlset_urls)``.

    FAILURE CASE:
        XML rusak menghasilkan ``ValueError`` yang mudah dibaca.
    """
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError as exc:
        raise ValueError("sitemap XML is not valid") from exc

    def local_name(tag: str) -> str:
        """Menghapus bagian namespace, misalnya ``{...}url`` menjadi ``url``."""
        return tag.rsplit("}", 1)[-1]

    child_sitemaps: list[str] = []
    product_urls: list[str] = []
    for item in root:
        item_type = local_name(item.tag)
        if item_type not in {"sitemap", "url"}:
            continue
        location = next(
            (child.text.strip() for child in item if local_name(child.tag) == "loc" and child.text),
            None,
        )
        if not location:
            continue
        if item_type == "sitemap":
            child_sitemaps.append(location)
        else:
            product_urls.append(location)
    return child_sitemaps, product_urls


def discover_electronic_city_product_urls(
    api_url: str,
    *,
    query: str,
    limit: int,
    fetch_fn: Callable[[str], str],
) -> list[str]:
    """Mengubah hasil pencarian publik Electronic City menjadi URL produk.

    WHY:
        Halaman kategori ECI yang diambil oleh ``requests`` hanya berisi
        kerangka halaman. Sebaliknya, situs ECI sendiri memakai endpoint
        pencarian publik yang langsung mengirim ID produk. Kita memakai ID itu
        untuk membentuk URL halaman detail yang tetap menjadi sumber data utama.

    INPUT:
        URL endpoint, kata kategori seperti ``tablet``, batas produk, dan
        fungsi pengambil teks. ``fetch_fn`` dibuat terpisah agar aturan ini
        bisa dites tanpa internet.

    PROCESS:
        Minta kandidat sedikit lebih banyak daripada target karena endpoint
        kadang mengembalikan kurang dari angka ``limit``. Setelah itu periksa
        respons sukses, ambil ID yang benar, lalu ubah tiap ID menjadi
        ``/product/<id>/detail`` sampai target tercapai.

    OUTPUT:
        Daftar URL detail produk ECI yang unik, paling banyak sebanyak
        ``limit``. Detail dan harga tetap dibaca dari halaman produk sesudahnya.

    FAILURE CASE:
        Respons bukan JSON atau status API bukan ``success`` menghasilkan
        ``ValueError``. Item tanpa ID dilewati, karena tidak bisa dibuka.
    """
    if not query.strip():
        raise ValueError("Electronic City search query must not be empty")
    if limit < 1:
        raise ValueError("limit must be positive")

    # Over-fetch berdasarkan target, bukan ID hardcoded. Ini menangani kasus
    # endpoint mengembalikan 8 item saat diminta 10 karena sebagian kandidat
    # tidak lolos pencarian atau tidak memiliki ID lengkap.
    request_limit = limit * 3
    request_url = f"{api_url}?{urlencode({'q': query, 'limit': request_limit})}"
    try:
        payload = json.loads(fetch_fn(request_url))
    except json.JSONDecodeError as exc:
        raise ValueError("Electronic City search response is not valid JSON") from exc

    if payload.get("status") != "success" or not isinstance(payload.get("data"), list):
        raise ValueError("Electronic City search response is not successful")

    source_root = urljoin(api_url, "/")
    product_urls: list[str] = []
    seen: set[str] = set()
    for item in payload["data"]:
        product_id = item.get("id") if isinstance(item, dict) else None
        if isinstance(product_id, bool) or not str(product_id).isdigit():
            continue
        product_url = urljoin(source_root, f"product/{product_id}/detail")
        if product_url not in seen:
            seen.add(product_url)
            product_urls.append(product_url)
        if len(product_urls) >= limit:
            break
    return product_urls


def discover_sitemap_product_urls(
    root_sitemap_url: str,
    *,
    fetch_fn: Callable[[str], str],
    product_path_prefix: str = "/eraspace/produk/",
    max_sitemaps: int = 1000,
) -> list[str]:
    """Menemukan URL produk dari seluruh rantai sitemap satu host.

    WHY:
        URL kategori atau nomor halaman bisa berubah. Sitemap resmi adalah
        daftar katalog yang diterbitkan toko, sehingga lebih cocok untuk
        pengambilan ulang jangka panjang.

    INPUT:
        URL sitemap utama dan fungsi ``fetch_fn`` untuk mengambil XML. Prefix
        path menyaring hanya produk Eraspace, bukan Erafone atau kategori lain.

    PROCESS:
        Mulai dari sitemap utama, ikuti sitemap anak yang ditemukan di dalam
        XML, lalu kumpulkan URL produk. URL yang sama hanya disimpan sekali.

    OUTPUT:
        Daftar URL produk canonical dalam urutan pertama kali ditemukan.

    FAILURE CASE:
        Sitemap lintas-host ditolak, rantai terlalu panjang ditolak, dan
        error pengambilan/XML diteruskan ke pemanggil.
    """
    root_host = urlparse(root_sitemap_url).netloc.lower()
    if not root_host:
        raise ValueError("root sitemap URL must include a host")
    if max_sitemaps < 1:
        raise ValueError("max_sitemaps must be positive")

    pending = deque([root_sitemap_url])
    queued = {root_sitemap_url}
    visited: set[str] = set()
    product_urls: list[str] = []
    product_seen: set[str] = set()

    while pending:
        sitemap_url = pending.popleft()
        if sitemap_url in visited:
            continue
        if len(visited) >= max_sitemaps:
            raise ValueError(f"sitemap chain exceeded max_sitemaps={max_sitemaps}")
        if urlparse(sitemap_url).netloc.lower() != root_host:
            raise ValueError("all child sitemaps must stay on the same host")

        visited.add(sitemap_url)
        child_sitemaps, listed_urls = parse_sitemap_xml(fetch_fn(sitemap_url))

        for child_url in child_sitemaps:
            absolute_child = urljoin(sitemap_url, child_url).split("#", 1)[0]
            if urlparse(absolute_child).netloc.lower() != root_host:
                raise ValueError("all child sitemaps must stay on the same host")
            if absolute_child not in queued:
                queued.add(absolute_child)
                pending.append(absolute_child)

        for listed_url in listed_urls:
            absolute_product = urljoin(sitemap_url, listed_url).split("#", 1)[0]
            parsed_product = urlparse(absolute_product)
            if (
                parsed_product.netloc.lower() == root_host
                and parsed_product.path.startswith(product_path_prefix)
                and absolute_product not in product_seen
            ):
                product_seen.add(absolute_product)
                product_urls.append(absolute_product)

    return product_urls


def fetch_html(url: str, *, session: requests.Session, timeout_seconds: int) -> str:
    """Mengambil isi satu halaman website.

    WHY:
        Semua request memakai aturan yang sama: timeout, User-Agent, dan
        header penerima HTML.

    INPUT:
        URL, koneksi HTTP yang dipakai bersama, dan batas waktu tunggu.

    PROCESS:
        Kirim GET request, cek apakah website menjawab dengan status error,
        lalu ambil isi halaman.

    OUTPUT:
        Teks HTML halaman.

    FAILURE CASE:
        Timeout, masalah jaringan, atau status HTTP error akan dilempar ke
        fungsi pemanggil untuk dicatat sebagai error source.
    """
    response = session.get(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
        timeout=timeout_seconds,
    )
    response.raise_for_status()
    return response.text


def collect_from_html(
    source_id: str,
    category_url: str,
    category_html: str,
    product_pages: dict[str, str],
    observed_at_utc: datetime,
    limit: int = 10,
) -> CollectionResult:
    """Memproses halaman kategori dan halaman produk yang sudah diambil.

    WHY:
        Bagian ini memisahkan pekerjaan membaca HTML dari pekerjaan network,
        sehingga parser dapat dites tanpa membuka website.

    INPUT:
        HTML kategori, mapping URL ke HTML produk, nama source, dan waktu.

    PROCESS:
        Cari URL produk, cari HTML untuk setiap URL, lalu parse satu per satu.
        Produk yang gagal tidak menghapus produk yang berhasil.

    OUTPUT:
        ``CollectionResult`` berisi observation berhasil dan daftar error.

    FAILURE CASE:
        URL ditemukan tetapi HTML-nya hilang, atau parser menolak halaman.
        Masalah tersebut masuk ke ``errors``.
    """
    urls = discover_product_urls(source_id, category_url, category_html, limit=limit)
    observations: list[RawProductObservation] = []
    errors: list[dict[str, str]] = []
    for url in urls:
        html = product_pages.get(url)
        if html is None:
            errors.append({"url": url, "error": "product page was not fetched"})
            continue
        try:
            observations.append(parse_product_html(source_id, url, html, observed_at_utc))
        except (ValueError, TypeError) as exc:
            errors.append({"url": url, "error": str(exc)})
    return CollectionResult(source_id, category_url, observed_at_utc, urls, observations, errors)


def collect_explicit_pages(
    source_id: str,
    category_url: str,
    product_pages: dict[str, str],
    observed_at_utc: datetime,
) -> CollectionResult:
    """Memproses halaman dari daftar link yang sudah disetujui.

    WHY:
        Dipakai saat halaman kategori tidak dapat menemukan link produk dengan
        baik, misalnya pada Eraspace.

    INPUT:
        Nama source, URL kategori sebagai catatan, dan mapping URL ke HTML.

    PROCESS:
        Langsung parse setiap URL yang diberikan. Tidak melakukan discovery.

    OUTPUT:
        ``CollectionResult`` dengan link yang dicoba, data berhasil, dan error.

    FAILURE CASE:
        HTML produk tidak lengkap atau tidak lolos validasi akan masuk ke
        ``errors`` tanpa menghentikan URL lain.
    """
    observations: list[RawProductObservation] = []
    errors: list[dict[str, str]] = []
    for url, html in product_pages.items():
        try:
            observations.append(parse_product_html(source_id, url, html, observed_at_utc))
        except (ValueError, TypeError) as exc:
            errors.append({"url": url, "error": str(exc)})
    return CollectionResult(
        source_id,
        category_url,
        observed_at_utc,
        list(product_pages),
        observations,
        errors,
    )


def fetch_source(
    source_id: str,
    category_url: str,
    observed_at_utc: datetime,
    *,
    session: requests.Session | None = None,
    timeout_seconds: int = 20,
    limit: int = 10,
    delay_seconds: float = 0.5,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> CollectionResult:
    """Mengambil produk dengan cara mencari link dari halaman daftar toko.

    WHY:
        Ini jalur normal untuk source yang membuka product link dari katalog.

    INPUT:
        Nama source, URL kategori, waktu, batas jumlah, timeout, dan delay.

    PROCESS:
        Ambil kategori, cari link produk, ambil halaman produk, lalu proses
        semua HTML yang berhasil.

    OUTPUT:
        ``CollectionResult``.

    FAILURE CASE:
        Kategori atau produk bisa gagal diambil. Error network dan error parse
        digabung dalam hasil agar bisa dilihat setelah run selesai.
    """
    http = session or requests.Session()
    category_html = fetch_html(category_url, session=http, timeout_seconds=timeout_seconds)
    product_urls = discover_product_urls(source_id, category_url, category_html, limit=limit)
    product_pages: dict[str, str] = {}
    fetch_errors: list[dict[str, str]] = []
    for index, url in enumerate(product_urls):
        try:
            product_pages[url] = fetch_html(url, session=http, timeout_seconds=timeout_seconds)
        # Transport bisa diganti saat smoke test (misalnya curl di Windows).
        # Karena satu produk yang timeout tidak boleh menjatuhkan kategorinya,
        # catat semua error request biasa di batas per-produk ini.
        except Exception as exc:  # noqa: BLE001 - error dicatat per produk
            fetch_errors.append({"url": url, "error": f"request failed: {exc}"})
        if index < len(product_urls) - 1 and delay_seconds > 0:
            sleep_fn(delay_seconds)

    result = collect_from_html(
        source_id=source_id,
        category_url=category_url,
        category_html=category_html,
        product_pages=product_pages,
        observed_at_utc=observed_at_utc,
        limit=limit,
    )
    failed_urls = {error["url"] for error in fetch_errors}
    parse_errors = [
        error
        for error in result.errors
        if not (error["url"] in failed_urls and error["error"] == "product page was not fetched")
    ]
    return CollectionResult(
        result.source_id,
        result.category_url,
        result.observed_at_utc,
        result.discovered_product_urls,
        result.observations,
        fetch_errors + parse_errors,
    )


def fetch_explicit_source(
    source_id: str,
    category_url: str,
    product_urls: list[str],
    observed_at_utc: datetime,
    *,
    session: requests.Session | None = None,
    timeout_seconds: int = 20,
    limit: int = 10,
    delay_seconds: float = 0.5,
    sleep_fn: Callable[[float], None] = time.sleep,
    fetch_fn: Callable[[str], str] | None = None,
) -> CollectionResult:
    """Mengambil produk langsung dari daftar link yang sudah disetujui.

    WHY:
        Ini jalur untuk source yang tidak dapat diandalkan untuk discovery
        katalog. Jumlah produk tetap dibatasi oleh aturan Phase 1.

    INPUT:
        Nama source, URL kategori sebagai catatan, daftar URL produk, waktu,
        timeout, dan delay.

    PROCESS:
        Buang link duplikat, batasi jumlah, ambil setiap halaman, lalu parse
        halaman yang berhasil.

    OUTPUT:
        ``CollectionResult``.

    FAILURE CASE:
        URL gagal diambil atau isi halaman gagal dipahami. Error disimpan dan
        URL lain tetap dicoba.
    """
    http = session or requests.Session()

    # Biasanya kita memakai ``fetch_html``. Saat test, ``fetch_fn`` menyediakan
    # halaman palsu dari dictionary agar test tidak perlu membuka internet.
    def get_page(url: str) -> str:
        if fetch_fn is not None:
            return fetch_fn(url)
        return fetch_html(url, session=http, timeout_seconds=timeout_seconds)

    selected_urls = list(dict.fromkeys(product_urls))[:limit]
    product_pages: dict[str, str] = {}
    fetch_errors: list[dict[str, str]] = []
    for index, url in enumerate(selected_urls):
        try:
            product_pages[url] = get_page(url)
        except Exception as exc:  # noqa: BLE001 - satu URL gagal tidak menghentikan kategori
            fetch_errors.append({"url": url, "error": f"request failed: {exc}"})
        if index < len(selected_urls) - 1 and delay_seconds > 0:
            sleep_fn(delay_seconds)

    result = collect_explicit_pages(
        source_id=source_id,
        category_url=category_url,
        product_pages=product_pages,
        observed_at_utc=observed_at_utc,
    )
    return CollectionResult(
        result.source_id,
        result.category_url,
        result.observed_at_utc,
        selected_urls,
        result.observations,
        fetch_errors + result.errors,
    )


def fetch_sitemap_source(
    source_id: str,
    category_url: str,
    *,
    sitemap_url: str,
    observed_at_utc: datetime,
    session: requests.Session | None = None,
    timeout_seconds: int = 20,
    limit: int = 10,
    delay_seconds: float = 0.5,
    sleep_fn: Callable[[float], None] = time.sleep,
    fetch_fn: Callable[[str], str] | None = None,
) -> CollectionResult:
    """Mengambil produk dari sitemap kategori, lalu membaca halaman detailnya.

    WHY:
        Eraspace membuat kartu produknya di browser, sehingga HTML halaman
        kategori kosong bagi ``requests``. Sitemap kategori adalah daftar URL
        produk yang diterbitkan Eraspace sendiri dan tidak bergantung pada
        tampilan halaman katalog.

    INPUT:
        Nama toko, URL kategori sebagai catatan, URL sitemap kategori, waktu,
        serta batas kecil produk untuk smoke test.

    PROCESS:
        Baca sitemap, ambil URL yang bentuknya cocok dengan toko tersebut,
        lalu gunakan jalur pembaca halaman detail yang sudah ada.

    OUTPUT:
        ``CollectionResult`` berisi URL dari sitemap, produk yang terbaca, dan
        error per halaman jika ada.

    FAILURE CASE:
        Sitemap rusak/gagal diambil akan diteruskan ke smoke runner sebagai
        ``FAILED``. Jika satu produk gagal, produk lain tetap diproses.
    """
    http = session or requests.Session()

    def get_page(url: str) -> str:
        if fetch_fn is not None:
            return fetch_fn(url)
        return fetch_html(url, session=http, timeout_seconds=timeout_seconds)

    if source_id != "eraspace":
        raise ValueError(f"sitemap adapter is not configured for {source_id}")

    product_urls = discover_sitemap_product_urls(
        sitemap_url,
        fetch_fn=get_page,
        product_path_prefix="/eraspace/produk/",
    )
    return fetch_explicit_source(
        source_id,
        category_url,
        product_urls,
        observed_at_utc,
        session=http,
        timeout_seconds=timeout_seconds,
        limit=limit,
        delay_seconds=delay_seconds,
        sleep_fn=sleep_fn,
        fetch_fn=get_page,
    )


def fetch_electronic_city_source(
    category_url: str,
    *,
    api_url: str,
    query: str,
    observed_at_utc: datetime,
    session: requests.Session | None = None,
    timeout_seconds: int = 20,
    limit: int = 10,
    delay_seconds: float = 0.5,
    sleep_fn: Callable[[float], None] = time.sleep,
    fetch_fn: Callable[[str], str] | None = None,
) -> CollectionResult:
    """Mengambil produk ECI lewat pencarian publik, lalu halaman detailnya.

    WHY:
        ECI tidak menaruh kartu produk dalam HTML kategori awal. Endpoint
        pencarian yang dipakai halaman ECI memberi beberapa ID produk untuk
        satu kata kategori. ID itu cukup untuk membuka detail produk normal.

    INPUT:
        URL kategori untuk catatan run, endpoint pencarian, kata kategori
        seperti ``laptop``, waktu, dan batas jumlah produk.

    PROCESS:
        Cari beberapa ID produk melalui endpoint publik, bentuk URL detail,
        lalu baca setiap halaman detail menggunakan parser yang sama dengan
        retailer lain.

    OUTPUT:
        ``CollectionResult`` berisi produk ECI yang sudah diparse.

    FAILURE CASE:
        API pencarian bermasalah menghasilkan error pada smoke runner. Jika
        satu detail produk gagal, detail lain tetap diteruskan.
    """
    http = session or requests.Session()

    def get_page(url: str) -> str:
        if fetch_fn is not None:
            return fetch_fn(url)
        return fetch_html(url, session=http, timeout_seconds=timeout_seconds)

    product_urls = discover_electronic_city_product_urls(
        api_url,
        query=query,
        limit=limit,
        fetch_fn=get_page,
    )
    return fetch_explicit_source(
        "electronic_city",
        category_url,
        product_urls,
        observed_at_utc,
        session=http,
        timeout_seconds=timeout_seconds,
        limit=limit,
        delay_seconds=delay_seconds,
        sleep_fn=sleep_fn,
        fetch_fn=get_page,
    )


def run_smoke_test(
    source_id: str,
    category_id: str,
    *,
    observed_at_utc: datetime,
    collection_runner: Callable[..., CollectionResult] | None = None,
    session: requests.Session | None = None,
    timeout_seconds: int = 20,
    limit: int = 3,
    delay_seconds: float = 0.5,
) -> SmokeRunResult:
    """Menjalankan satu smoke test kecil untuk satu kombinasi source-kategori.

    WHY:
        Kita tidak ingin menjalankan 12 URL secara manual. Fungsi ini selalu
        memakai aturan dari ``SOURCE_CONFIG`` dan memberi label kategori pada
        setiap produk yang berhasil dibaca.

    INPUT:
        Nama retailer, kategori, waktu run, dan batas kecil jumlah produk.
        ``collection_runner`` dapat diganti oleh test agar test tidak membuka
        internet.

    PROCESS:
        Ambil rencana dari dispatcher, jalankan collector, tempelkan kategori
        ke hasil produk, lalu tentukan status sederhana.

    OUTPUT:
        ``SmokeRunResult`` dengan URL, records, error, dan status.

    FAILURE CASE:
        Jika collector melempar error, source tersebut menjadi ``FAILED``.
        Jika halaman berhasil dibaca tetapi tidak memberi harga valid, status
        menjadi ``DISCOVERY_WEAK``; run lain tetap bisa berjalan.
    """
    plan = dispatch_source_category(source_id, category_id)
    try:
        # Test boleh memberi collector kecilnya sendiri. Di luar test, strategi
        # di registry menentukan pintu masuk data yang benar untuk tiap toko.
        if collection_runner is not None:
            collected = collection_runner(
                source_id=source_id,
                category_url=plan["smoke_url"],
                observed_at_utc=observed_at_utc,
                session=session,
                timeout_seconds=timeout_seconds,
                limit=limit,
                delay_seconds=delay_seconds,
            )
        elif plan["strategy"] == "sitemap":
            if not plan["discovery_url"]:
                raise ValueError("sitemap strategy needs a discovery_url")
            collected = fetch_sitemap_source(
                source_id,
                plan["smoke_url"],
                sitemap_url=plan["discovery_url"],
                observed_at_utc=observed_at_utc,
                session=session,
                timeout_seconds=timeout_seconds,
                limit=limit,
                delay_seconds=delay_seconds,
            )
        elif plan["strategy"] == "product_suggestions_api":
            if not plan["discovery_url"] or not plan["search_query"]:
                raise ValueError("Electronic City strategy needs URL and search query")
            collected = fetch_electronic_city_source(
                plan["smoke_url"],
                api_url=plan["discovery_url"],
                query=plan["search_query"],
                observed_at_utc=observed_at_utc,
                session=session,
                timeout_seconds=timeout_seconds,
                limit=limit,
                delay_seconds=delay_seconds,
            )
        else:
            collected = fetch_source(
                source_id=source_id,
                category_url=plan["smoke_url"],
                observed_at_utc=observed_at_utc,
                session=session,
                timeout_seconds=timeout_seconds,
                limit=limit,
                delay_seconds=delay_seconds,
            )
    except Exception as exc:  # noqa: BLE001 - one source must not stop the matrix
        return SmokeRunResult(
            source_id=source_id,
            category_id=category_id,
            strategy=plan["strategy"],
            smoke_url=plan["smoke_url"],
            observed_at_utc=observed_at_utc,
            discovered_product_urls=[],
            observations=[],
            errors=[{"url": plan["smoke_url"], "error": str(exc)}],
            status="FAILED",
            price_valid_count=0,
        )

    observations = [
        record.model_copy(update={"category_id": category_id}) for record in collected.observations
    ]
    price_valid_count = sum(record.current_price_idr is not None for record in observations)
    status = "READY" if price_valid_count else "DISCOVERY_WEAK"
    return SmokeRunResult(
        source_id=source_id,
        category_id=category_id,
        strategy=plan["strategy"],
        smoke_url=plan["smoke_url"],
        observed_at_utc=observed_at_utc,
        discovered_product_urls=collected.discovered_product_urls,
        observations=observations,
        errors=collected.errors,
        status=status,
        price_valid_count=price_valid_count,
    )


def run_smoke_matrix(
    *,
    observed_at_utc: datetime,
    collection_runner: Callable[..., CollectionResult] | None = None,
    session: requests.Session | None = None,
    timeout_seconds: int = 20,
    limit: int = 3,
    delay_seconds: float = 0.5,
) -> list[SmokeRunResult]:
    """Menjalankan 12 smoke test dari registry secara berurutan.

    WHY:
        Matrix memberi bukti bahwa tiga kategori dicoba pada semua retailer,
        bukan hanya pada kategori yang kebetulan mudah diambil.

    INPUT:
        Waktu run dan aturan request yang sama untuk seluruh kombinasi.

    PROCESS:
        Loop setiap retailer lalu tiga kategori dari ``CATEGORY_IDS``.

    OUTPUT:
        Tepat 12 ``SmokeRunResult`` selama registry berisi 4 retailer.

    FAILURE CASE:
        Kegagalan satu website disimpan sebagai satu hasil ``FAILED`` dan
        tidak menghentikan 11 kombinasi lain.
    """
    results: list[SmokeRunResult] = []
    for source_id in SOURCE_CONFIG:
        for category_id in CATEGORY_IDS:
            results.append(
                run_smoke_test(
                    source_id,
                    category_id,
                    observed_at_utc=observed_at_utc,
                    collection_runner=collection_runner,
                    session=session,
                    timeout_seconds=timeout_seconds,
                    limit=limit,
                    delay_seconds=delay_seconds,
                )
            )
    return results


def write_smoke_run(output_root: Path, result: SmokeRunResult, *, run_id: str) -> Path:
    """Menyimpan satu hasil smoke test tanpa menimpa kategori lain.

    WHY:
        File lama hanya dipisahkan berdasarkan source dan tanggal. Tiga
        kategori dari source yang sama bisa saling menimpa. Path baru memisah
        run, source, dan kategori.

    INPUT:
        Folder output, hasil smoke, dan ID run yang sama untuk satu matrix.

    PROCESS:
        Tulis JSON di ``<output>/<run>/<source>/<category>.json``.

    OUTPUT:
        Path file bukti yang baru ditulis.

    FAILURE CASE:
        Jika folder atau file tidak bisa ditulis, error diteruskan agar caller
        tahu bukti run belum tersimpan.
    """
    output_path = output_root / run_id / result.source_id / f"{result.category_id}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "run_id": run_id,
        "source_id": result.source_id,
        "category_id": result.category_id,
        "strategy": result.strategy,
        "smoke_url": result.smoke_url,
        "observed_at_utc": result.observed_at_utc.isoformat(),
        "status": result.status,
        "discovered_product_urls": result.discovered_product_urls,
        "price_valid_count": result.price_valid_count,
        "record_count": len(result.observations),
        "records": [record.model_dump(mode="json") for record in result.observations],
        "errors": result.errors,
    }
    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return output_path


def write_smoke_summary(
    output_root: Path, results: Iterable[SmokeRunResult], *, run_id: str
) -> Path:
    """Menyimpan ringkasan semua kombinasi agar closeout mudah dibaca.

    WHY:
        Dua belas file rinci bagus untuk audit, tetapi closeout membutuhkan
        satu file kecil yang langsung menunjukkan status setiap kombinasi.

    INPUT:
        Folder output, hasil matrix, dan ID run.

    PROCESS:
        Hitung jumlah setiap status lalu tulis ringkasan tanpa menyalin semua
        detail produk.

    OUTPUT:
        File ``summary.json`` untuk satu run.

    FAILURE CASE:
        Error tulis file diteruskan kepada caller.
    """
    result_list = list(results)
    status_counts: dict[str, int] = {}
    for result in result_list:
        status_counts[result.status] = status_counts.get(result.status, 0) + 1
    output_path = output_root / run_id / "summary.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "run_id": run_id,
        "status_counts": dict(sorted(status_counts.items())),
        "results": [
            {
                "source_id": result.source_id,
                "category_id": result.category_id,
                "strategy": result.strategy,
                "status": result.status,
                "discovered_count": len(result.discovered_product_urls),
                "price_valid_count": result.price_valid_count,
                "error_count": len(result.errors),
            }
            for result in result_list
        ],
    }
    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return output_path


def compare_smoke_discoveries(first: SmokeRunResult, second: SmokeRunResult) -> dict[str, Any]:
    """Membandingkan URL discovery dari dua run kombinasi yang sama.

    WHY:
        Reproducible tidak berarti katalog harus beku. Kita perlu membedakan
        perubahan katalog nyata dari pipeline yang tidak bisa dijalankan lagi.

    INPUT:
        Dua hasil untuk retailer dan kategori yang sama.

    PROCESS:
        Ubah dua daftar URL menjadi set lalu cari URL yang baru, hilang, dan
        tetap ada.

    OUTPUT:
        Dictionary kecil yang siap masuk ke closeout.

    FAILURE CASE:
        Dua hasil dari source atau kategori berbeda ditolak karena tidak adil
        untuk dibandingkan.
    """
    if (first.source_id, first.category_id) != (second.source_id, second.category_id):
        raise ValueError("smoke results must use the same source and category")
    first_urls = set(first.discovered_product_urls)
    second_urls = set(second.discovered_product_urls)
    return {
        "source_id": first.source_id,
        "category_id": first.category_id,
        "first_count": len(first_urls),
        "second_count": len(second_urls),
        "added_urls": sorted(second_urls - first_urls),
        "removed_urls": sorted(first_urls - second_urls),
        "unchanged_count": len(first_urls & second_urls),
    }


def write_raw_sample(
    output_root: Path,
    source_id: str,
    observed_at_utc: datetime,
    observations: Iterable[RawProductObservation],
    errors: Iterable[dict[str, str]],
) -> Path:
    """Menyimpan hasil percobaan ke satu file JSON.

    WHY:
        Di Phase 1 kita perlu melihat hasil dengan mudah. JSON cukup untuk
        sample kecil dan belum memerlukan database.

    INPUT:
        Folder output, nama source, waktu, observation berhasil, dan error.

    PROCESS:
        Buat folder source, ubah observation menjadi bentuk JSON, lalu tulis
        records dan errors dalam satu file tanggal.

    OUTPUT:
        Alamat file JSON yang baru ditulis.

    FAILURE CASE:
        Folder tidak bisa dibuat, file tidak bisa ditulis, atau data gagal
        diubah menjadi JSON. Error dikembalikan ke ``main``.
    """
    output_path = output_root / source_id / f"{observed_at_utc.date().isoformat()}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    observation_list = list(observations)
    payload = {
        "source_id": source_id,
        "observed_at_utc": observed_at_utc.isoformat(),
        "record_count": len(observation_list),
        "records": [record.model_dump(mode="json") for record in observation_list],
        "errors": list(errors),
    }
    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return output_path


def load_url_basket(path: Path, source_id: str) -> list[str]:
    """Membaca link produk ACTIVE untuk satu toko dari file CSV.

    WHY:
        Daftar link membuat percobaan bisa diulang dengan produk yang sama.

    INPUT:
        File CSV dan nama toko.

    PROCESS:
        Pilih baris untuk toko tersebut dan status ``ACTIVE``.

    OUTPUT:
        Daftar link produk.

    FAILURE CASE:
        File atau kolom link tidak ada. Jika tidak ada baris ACTIVE, hasilnya
        kosong.
    """
    with path.open(encoding="utf-8", newline="") as handle:
        rows = csv.DictReader(handle)
        return [
            row["product_url"]
            for row in rows
            if row.get("source_id") == source_id and row.get("status", "ACTIVE") == "ACTIVE"
        ]


def main() -> int:
    """Menyuruh semua bagian mencoba source dan menyimpan hasilnya.

    WHY:
        User hanya perlu menjalankan satu command. Fungsi ini menjadi pengatur
        urutan tanpa membuat pembaca memahami semua detail parser lebih dulu.

    INPUT:
        Pilihan source, kategori matrix, jumlah produk, timeout, delay, URL
        basket, dan folder output dari command line.

    PROCESS:
        Jika ``--smoke-matrix`` dipilih, jalankan 12 kombinasi dari registry.
        Jika tidak, pilih jalur category atau URL basket seperti POC lama.

    OUTPUT:
        Ringkasan di terminal dan exit code 0 atau 1.

    FAILURE CASE:
        Parameter salah ditolak. Error source, network, parse, dan storage
        dilaporkan per source agar hasil source lain tetap tersimpan.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=[*SOURCE_CATEGORIES, "all"], default="all")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--delay", type=float, default=0.5)
    parser.add_argument(
        "--url-basket", type=Path, help="File CSV berisi link produk yang boleh dicoba"
    )
    parser.add_argument(
        "--smoke-matrix",
        action="store_true",
        help="Coba seluruh 4 retailer x 3 kategori dan simpan bukti setiap kombinasi",
    )
    parser.add_argument("--output", type=Path, default=Path("data/phase-1/raw"))
    args = parser.parse_args()

    if args.limit < 1 or args.limit > 20:
        parser.error("--limit must be between 1 and 20 for the Phase 1 POC")
    if args.smoke_matrix and args.url_basket:
        parser.error("--smoke-matrix cannot use --url-basket")

    if args.smoke_matrix:
        observed_at = datetime.now(timezone.utc)
        run_id = observed_at.strftime("smoke-%Y%m%dT%H%M%SZ")
        results = run_smoke_matrix(
            observed_at_utc=observed_at,
            timeout_seconds=args.timeout,
            limit=args.limit,
            delay_seconds=args.delay,
        )
        for result in results:
            output_path = write_smoke_run(args.output, result, run_id=run_id)
            print(
                f"{result.source_id}/{result.category_id}: {result.status} "
                f"discovered={len(result.discovered_product_urls)} "
                f"price_valid={result.price_valid_count} errors={len(result.errors)} raw={output_path}"
            )
        summary_path = write_smoke_summary(args.output, results, run_id=run_id)
        print(f"smoke summary={summary_path}")
        return 0 if any(result.status == "READY" for result in results) else 1

    source_ids = list(SOURCE_CATEGORIES) if args.source == "all" else [args.source]
    observed_at = datetime.now(timezone.utc)
    exit_code = 0

    for source_id in source_ids:
        category_url = SOURCE_CATEGORIES[source_id]
        try:
            if args.url_basket:
                result = fetch_explicit_source(
                    source_id=source_id,
                    category_url=category_url,
                    product_urls=load_url_basket(args.url_basket, source_id),
                    observed_at_utc=observed_at,
                    limit=args.limit,
                    timeout_seconds=args.timeout,
                    delay_seconds=args.delay,
                )
            else:
                result = fetch_source(
                    source_id=source_id,
                    category_url=category_url,
                    observed_at_utc=observed_at,
                    limit=args.limit,
                    timeout_seconds=args.timeout,
                    delay_seconds=args.delay,
                )

            output_path = write_raw_sample(
                output_root=args.output,
                source_id=source_id,
                observed_at_utc=observed_at,
                observations=result.observations,
                errors=result.errors,
            )
            print(
                f"{source_id}: discovered={len(result.discovered_product_urls)} "
                f"valid={len(result.observations)} errors={len(result.errors)} raw={output_path}"
            )
            if not result.observations:
                exit_code = 1
        except Exception as exc:  # noqa: BLE001 - CLI reports source-local failure
            print(f"{source_id}: failed={exc}")
            exit_code = 1
    return exit_code


if __name__ == "__main__":
    main()
