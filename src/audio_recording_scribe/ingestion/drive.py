"""Google Drive public-link parsing and download helpers."""

from __future__ import annotations

from dataclasses import dataclass
from html import unescape
from http.cookiejar import CookieJar
from pathlib import Path
import re
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import HTTPCookieProcessor, OpenerDirector, Request, build_opener

_FILE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{10,}$")
_RESOURCE_KEY_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_CONFIRM_TOKEN_RE = re.compile(r"[?&]confirm=([A-Za-z0-9_-]+)")
_CONFIRM_INPUT_RE = re.compile(r'name=["\']confirm["\']\s+value=["\']([^"\']+)["\']')
_SUPPORTED_HOSTS = frozenset({"drive.google.com"})
_HTML_CONTENT_TYPES = frozenset({"text/html", "application/xhtml+xml"})
_CHUNK_SIZE = 64 * 1024
_HTML_PREVIEW_BYTES = 256 * 1024

DEFAULT_HEADERS: tuple[tuple[str, str], ...] = (
    ("User-Agent", "audio-recording-scribe/0.1"),
    ("Accept", "*/*"),
)
DRIVE_DOWNLOAD_ENDPOINT = "https://drive.google.com/uc"


class UnsupportedGoogleDriveLinkError(ValueError):
    """Raised when a Google Drive URL is not a supported public file link."""


class GoogleDriveDownloadError(RuntimeError):
    """Raised when a Google Drive file could not be downloaded."""


class GoogleDriveAccessError(GoogleDriveDownloadError):
    """Raised when a Google Drive link is not publicly downloadable."""


@dataclass(frozen=True, slots=True)
class GoogleDriveFileRef:
    file_id: str
    resource_key: str | None = None
    original_url: str | None = None


@dataclass(frozen=True, slots=True)
class GoogleDriveDownloadRequest:
    endpoint: str
    query_params: tuple[tuple[str, str], ...]
    headers: tuple[tuple[str, str], ...] = DEFAULT_HEADERS

    @property
    def url(self) -> str:
        encoded = urlencode(self.query_params)
        return f"{self.endpoint}?{encoded}" if encoded else self.endpoint

    def to_request(self) -> Request:
        return Request(self.url, headers=dict(self.headers), method="GET")


@dataclass(frozen=True, slots=True)
class GoogleDriveDownloadResult:
    destination: Path
    bytes_written: int
    content_type: str | None
    source_url: str


def parse_google_drive_url(url: str) -> GoogleDriveFileRef:
    parts = urlsplit(url)
    if parts.scheme not in {"https", "http"} or parts.netloc not in _SUPPORTED_HOSTS:
        raise UnsupportedGoogleDriveLinkError(f"Unsupported Google Drive host in URL: {url}")

    query = parse_qs(parts.query, keep_blank_values=False)
    resource_key = _optional_query_value(query, "resourcekey")
    segments = [segment for segment in parts.path.split("/") if segment]

    if len(segments) >= 3 and segments[0] == "file" and segments[1] == "d":
        file_id = segments[2]
    elif segments and segments[-1] in {"open", "uc"}:
        file_id = _required_query_value(query, "id", url)
    else:
        raise UnsupportedGoogleDriveLinkError(f"Unsupported Google Drive URL format: {url}")

    return GoogleDriveFileRef(
        file_id=_validate_file_id(file_id),
        resource_key=_validate_resource_key(resource_key),
        original_url=url,
    )


def build_google_drive_download_request(file_ref: GoogleDriveFileRef) -> GoogleDriveDownloadRequest:
    query_params: list[tuple[str, str]] = [
        ("export", "download"),
        ("id", file_ref.file_id),
    ]
    if file_ref.resource_key is not None:
        query_params.append(("resourcekey", file_ref.resource_key))
    return GoogleDriveDownloadRequest(endpoint=DRIVE_DOWNLOAD_ENDPOINT, query_params=tuple(query_params))


def download_google_drive_file(
    download_request: GoogleDriveDownloadRequest,
    destination: Path,
    *,
    timeout: float = 30.0,
    opener: OpenerDirector | None = None,
) -> GoogleDriveDownloadResult:
    client = opener or build_opener(HTTPCookieProcessor(CookieJar()))
    resolved_destination = destination.expanduser().resolve()
    resolved_destination.parent.mkdir(parents=True, exist_ok=True)

    response = client.open(download_request.to_request(), timeout=timeout)
    try:
        if _is_html_response(response):
            response_body = response.read(_HTML_PREVIEW_BYTES)
            confirm_request = _build_confirm_request(download_request, response_body)
            if confirm_request is None:
                _raise_html_response_error(response.geturl(), response_body)
            response.close()
            response = client.open(confirm_request.to_request(), timeout=timeout)

        if _is_html_response(response):
            _raise_html_response_error(response.geturl(), response.read(_HTML_PREVIEW_BYTES))

        bytes_written = _write_response_body(response, resolved_destination)
        return GoogleDriveDownloadResult(
            destination=resolved_destination,
            bytes_written=bytes_written,
            content_type=response.headers.get_content_type(),
            source_url=response.geturl(),
        )
    finally:
        response.close()


def _required_query_value(query: dict[str, list[str]], key: str, url: str) -> str:
    value = _optional_query_value(query, key)
    if value is None:
        raise UnsupportedGoogleDriveLinkError(f"Missing '{key}' query parameter in URL: {url}")
    return value


def _optional_query_value(query: dict[str, list[str]], key: str) -> str | None:
    values = query.get(key)
    if not values:
        return None
    return values[0]


def _validate_file_id(file_id: str) -> str:
    if not _FILE_ID_RE.fullmatch(file_id):
        raise UnsupportedGoogleDriveLinkError(f"Unsupported Google Drive file id: {file_id!r}")
    return file_id


def _validate_resource_key(resource_key: str | None) -> str | None:
    if resource_key is None:
        return None
    if not _RESOURCE_KEY_RE.fullmatch(resource_key):
        raise UnsupportedGoogleDriveLinkError(f"Unsupported Google Drive resource key: {resource_key!r}")
    return resource_key


def _is_html_response(response: object) -> bool:
    content_type = response.headers.get_content_type()
    return content_type in _HTML_CONTENT_TYPES


def _build_confirm_request(
    download_request: GoogleDriveDownloadRequest,
    response_body: bytes,
) -> GoogleDriveDownloadRequest | None:
    document = unescape(response_body.decode("utf-8", errors="replace"))
    token_match = _CONFIRM_TOKEN_RE.search(document) or _CONFIRM_INPUT_RE.search(document)
    if token_match is None:
        return None

    confirm_token = token_match.group(1)
    query_params = [item for item in download_request.query_params if item[0] != "confirm"]
    query_params.append(("confirm", confirm_token))
    return GoogleDriveDownloadRequest(
        endpoint=download_request.endpoint,
        query_params=tuple(query_params),
        headers=download_request.headers,
    )


def _raise_html_response_error(source_url: str, response_body: bytes) -> None:
    document = unescape(response_body.decode("utf-8", errors="replace")).lower()
    if "sign in" in document or "request access" in document or "need access" in document:
        raise GoogleDriveAccessError(f"Google Drive link is not publicly downloadable: {source_url}")
    if "download_warning" in document or "too large for google to scan" in document:
        raise GoogleDriveDownloadError(
            f"Google Drive requested an unsupported confirmation flow for: {source_url}"
        )
    raise GoogleDriveDownloadError(f"Google Drive returned HTML instead of file content: {source_url}")


def _write_response_body(response: object, destination: Path) -> int:
    temp_path = destination.with_name(f"{destination.name}.part")
    bytes_written = 0
    try:
        with temp_path.open("wb") as handle:
            while True:
                chunk = response.read(_CHUNK_SIZE)
                if not chunk:
                    break
                handle.write(chunk)
                bytes_written += len(chunk)
        temp_path.replace(destination)
        return bytes_written
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise
