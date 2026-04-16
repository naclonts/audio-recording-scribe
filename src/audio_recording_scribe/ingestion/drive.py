"""Google Drive public-link parsing and download helpers."""

from __future__ import annotations

from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
from http.cookiejar import CookieJar
from pathlib import Path
import re
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit
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
    file_name: str | None = None


@dataclass(frozen=True, slots=True)
class GoogleDriveFolderRef:
    folder_id: str
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


def parse_google_drive_url(url: str) -> GoogleDriveFileRef | GoogleDriveFolderRef:
    parts = urlsplit(url)
    if parts.scheme not in {"https", "http"} or parts.netloc not in _SUPPORTED_HOSTS:
        raise UnsupportedGoogleDriveLinkError(f"Unsupported Google Drive host in URL: {url}")

    query = parse_qs(parts.query, keep_blank_values=False)
    resource_key = _optional_query_value(query, "resourcekey")
    segments = [segment for segment in parts.path.split("/") if segment]

    if len(segments) >= 3 and segments[0] == "file" and segments[1] == "d":
        file_id = segments[2]
        return GoogleDriveFileRef(
            file_id=_validate_file_id(file_id),
            resource_key=_validate_resource_key(resource_key),
            original_url=url,
        )
    if len(segments) >= 3 and segments[0] == "drive" and segments[1] == "folders":
        folder_id = segments[2]
        return GoogleDriveFolderRef(
            folder_id=_validate_file_id(folder_id),
            resource_key=_validate_resource_key(resource_key),
            original_url=url,
        )
    if len(segments) >= 5 and segments[0] == "drive" and segments[3] == "folders":
        folder_id = segments[4]
        return GoogleDriveFolderRef(
            folder_id=_validate_file_id(folder_id),
            resource_key=_validate_resource_key(resource_key),
            original_url=url,
        )
    elif segments and segments[-1] in {"open", "uc"}:
        file_id = _required_query_value(query, "id", url)
        return GoogleDriveFileRef(
            file_id=_validate_file_id(file_id),
            resource_key=_validate_resource_key(resource_key),
            original_url=url,
        )
    raise UnsupportedGoogleDriveLinkError(f"Unsupported Google Drive URL format: {url}")


def build_google_drive_download_request(file_ref: GoogleDriveFileRef) -> GoogleDriveDownloadRequest:
    query_params: list[tuple[str, str]] = [
        ("export", "download"),
        ("id", file_ref.file_id),
    ]
    if file_ref.resource_key is not None:
        query_params.append(("resourcekey", file_ref.resource_key))
    return GoogleDriveDownloadRequest(endpoint=DRIVE_DOWNLOAD_ENDPOINT, query_params=tuple(query_params))


def build_google_drive_folder_request(folder_ref: GoogleDriveFolderRef) -> GoogleDriveDownloadRequest:
    query_params: list[tuple[str, str]] = []
    if folder_ref.resource_key is not None:
        query_params.append(("resourcekey", folder_ref.resource_key))
    return GoogleDriveDownloadRequest(
        endpoint=f"https://drive.google.com/drive/folders/{folder_ref.folder_id}",
        query_params=tuple(query_params),
        headers=(
            ("User-Agent", "audio-recording-scribe/0.1"),
            ("Accept", "text/html,application/xhtml+xml"),
        ),
    )


def list_google_drive_folder_files(
    folder_ref: GoogleDriveFolderRef,
    *,
    timeout: float = 30.0,
    opener: OpenerDirector | None = None,
) -> tuple[GoogleDriveFileRef, ...]:
    client = opener or build_opener(HTTPCookieProcessor(CookieJar()))
    request = build_google_drive_folder_request(folder_ref)
    response = client.open(request.to_request(), timeout=timeout)
    try:
        if not _is_html_response(response):
            raise GoogleDriveDownloadError(
                f"Google Drive returned an unsupported folder response: {response.geturl()}"
            )
        document = response.read()
    finally:
        response.close()

    parser = _GoogleDriveFolderParser()
    parser.feed(document.decode("utf-8", errors="replace"))
    parser.close()
    file_refs = parser.file_refs()
    if file_refs:
        return file_refs

    document_lower = unescape(document.decode("utf-8", errors="replace")).lower()
    if "sign in" in document_lower or "request access" in document_lower or "need access" in document_lower:
        raise GoogleDriveAccessError(
            f"Google Drive folder is not publicly listable: {folder_ref.original_url or request.url}"
        )
    raise GoogleDriveDownloadError(
        f"Google Drive folder did not expose any downloadable files: "
        f"{folder_ref.original_url or request.url}"
    )


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


class _GoogleDriveFolderParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._current_anchor: dict[str, str] | None = None
        self._anchor_text: list[str] = []
        self._file_refs: dict[str, GoogleDriveFileRef] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        attributes = {key: value for key, value in attrs if value is not None}
        href = attributes.get("href")
        if href is None:
            return
        self._current_anchor = attributes
        self._anchor_text = []

    def handle_data(self, data: str) -> None:
        if self._current_anchor is not None:
            self._anchor_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != "a" or self._current_anchor is None:
            return
        href = self._current_anchor.get("href")
        if href is not None:
            absolute_href = urljoin("https://drive.google.com", href)
            try:
                parsed = parse_google_drive_url(absolute_href)
            except UnsupportedGoogleDriveLinkError:
                parsed = None
            if isinstance(parsed, GoogleDriveFileRef):
                name = self._extract_anchor_name(self._current_anchor)
                if name is None:
                    name = " ".join(chunk.strip() for chunk in self._anchor_text if chunk.strip()).strip() or None
                if parsed.file_id not in self._file_refs:
                    self._file_refs[parsed.file_id] = GoogleDriveFileRef(
                        file_id=parsed.file_id,
                        resource_key=parsed.resource_key,
                        original_url=parsed.original_url,
                        file_name=name,
                    )
        self._current_anchor = None
        self._anchor_text = []

    def file_refs(self) -> tuple[GoogleDriveFileRef, ...]:
        return tuple(self._file_refs.values())

    @staticmethod
    def _extract_anchor_name(anchor_attrs: dict[str, str]) -> str | None:
        for key in ("title", "aria-label", "data-tooltip"):
            value = anchor_attrs.get(key)
            if value:
                return value.strip() or None
        return None
