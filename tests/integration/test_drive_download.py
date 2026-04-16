from __future__ import annotations

from email.message import Message
from pathlib import Path

import pytest

from audio_recording_scribe.ingestion import drive


class _FakeResponse:
    def __init__(self, url: str, content_type: str, payload: bytes) -> None:
        headers = Message()
        headers["Content-Type"] = content_type
        self.headers = headers
        self._url = url
        self._payload = payload
        self._offset = 0

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            size = len(self._payload) - self._offset
        chunk = self._payload[self._offset : self._offset + size]
        self._offset += len(chunk)
        return chunk

    def geturl(self) -> str:
        return self._url

    def close(self) -> None:
        return


class _FakeOpener:
    def __init__(self, responses: dict[str, _FakeResponse]) -> None:
        self._responses = responses
        self.requested_urls: list[str] = []

    def open(self, request: object, timeout: float = 30.0) -> _FakeResponse:
        del timeout
        self.requested_urls.append(request.full_url)
        try:
            return self._responses[request.full_url]
        except KeyError as exc:
            raise AssertionError(f"Unexpected URL requested: {request.full_url}") from exc


def test_download_google_drive_file_writes_binary_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(drive, "DRIVE_DOWNLOAD_ENDPOINT", "https://downloads.example.test/uc")
    request = drive.build_google_drive_download_request(
        drive.parse_google_drive_url(
            "https://drive.google.com/file/d/direct-file-id/view?usp=sharing"
        )
    )
    opener = _FakeOpener(
        {
            request.url: _FakeResponse(
                request.url,
                "audio/mpeg",
                b"audio-bytes",
            )
        }
    )

    result = drive.download_google_drive_file(
        request,
        tmp_path / "recording.m4a",
        opener=opener,
    )

    assert opener.requested_urls == [request.url]
    assert result.bytes_written == len(b"audio-bytes")
    assert result.content_type == "audio/mpeg"
    assert result.destination.read_bytes() == b"audio-bytes"


def test_download_google_drive_file_retries_confirmation_token_flow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(drive, "DRIVE_DOWNLOAD_ENDPOINT", "https://downloads.example.test/uc")
    request = drive.build_google_drive_download_request(
        drive.parse_google_drive_url(
            "https://drive.google.com/file/d/confirm-file-id/view?usp=sharing"
        )
    )
    confirm_url = (
        "https://downloads.example.test/uc?"
        "export=download&id=confirm-file-id&confirm=token123"
    )
    opener = _FakeOpener(
        {
            request.url: _FakeResponse(
                request.url,
                "text/html",
                (
                    b'<html><body><a href="/uc?export=download&id=confirm-file-id'
                    b'&confirm=token123">download</a></body></html>'
                ),
            ),
            confirm_url: _FakeResponse(confirm_url, "audio/mpeg", b"confirmed-audio"),
        }
    )

    result = drive.download_google_drive_file(
        request,
        tmp_path / "confirmed.m4a",
        opener=opener,
    )

    assert opener.requested_urls == [request.url, confirm_url]
    assert result.bytes_written == len(b"confirmed-audio")
    assert result.destination.read_bytes() == b"confirmed-audio"


def test_download_google_drive_file_rejects_non_public_html_response(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(drive, "DRIVE_DOWNLOAD_ENDPOINT", "https://downloads.example.test/uc")
    request = drive.build_google_drive_download_request(
        drive.parse_google_drive_url(
            "https://drive.google.com/file/d/private-file-id/view?usp=sharing"
        )
    )
    opener = _FakeOpener(
        {
            request.url: _FakeResponse(
                request.url,
                "text/html",
                b"<html><body>Sign in to continue</body></html>",
            )
        }
    )

    with pytest.raises(drive.GoogleDriveAccessError):
        drive.download_google_drive_file(
            request,
            tmp_path / "private.m4a",
            opener=opener,
        )


def test_list_google_drive_folder_files_extracts_public_file_links(monkeypatch: pytest.MonkeyPatch) -> None:
    folder_url = (
        "https://drive.google.com/drive/folders/1FolderAbCdEfGhIjKlMnOpQr?resourcekey=0-folder_key"
    )
    folder_ref = drive.parse_google_drive_url(folder_url)
    assert isinstance(folder_ref, drive.GoogleDriveFolderRef)

    request = drive.build_google_drive_folder_request(folder_ref)
    opener = _FakeOpener(
        {
            request.url: _FakeResponse(
                request.url,
                "text/html",
                b"""
                <html>
                  <body>
                    <a href="/file/d/1AudioFileAbCdEfGhIjKl/view?resourcekey=0-audio_key"
                       title="clip-one.m4a">clip-one.m4a</a>
                    <a href="https://drive.google.com/file/d/1SecondFileAbCdEfGhIj/view"
                       aria-label="clip-two.wav"></a>
                    <a href="/drive/folders/1NestedFolderAbCdEfGhIj/view">Nested folder</a>
                  </body>
                </html>
                """,
            )
        }
    )

    file_refs = drive.list_google_drive_folder_files(folder_ref, opener=opener)

    assert opener.requested_urls == [request.url]
    assert file_refs == (
        drive.GoogleDriveFileRef(
            file_id="1AudioFileAbCdEfGhIjKl",
            resource_key="0-audio_key",
            original_url="https://drive.google.com/file/d/1AudioFileAbCdEfGhIjKl/view?resourcekey=0-audio_key",
            file_name="clip-one.m4a",
        ),
        drive.GoogleDriveFileRef(
            file_id="1SecondFileAbCdEfGhIj",
            resource_key=None,
            original_url="https://drive.google.com/file/d/1SecondFileAbCdEfGhIj/view",
            file_name="clip-two.wav",
        ),
    )


def test_list_google_drive_folder_files_rejects_private_folder(monkeypatch: pytest.MonkeyPatch) -> None:
    folder_ref = drive.parse_google_drive_url(
        "https://drive.google.com/drive/folders/1FolderAbCdEfGhIjKlMnOpQr"
    )
    assert isinstance(folder_ref, drive.GoogleDriveFolderRef)

    request = drive.build_google_drive_folder_request(folder_ref)
    opener = _FakeOpener(
        {
            request.url: _FakeResponse(
                request.url,
                "text/html",
                b"<html><body>Sign in to continue</body></html>",
            )
        }
    )

    with pytest.raises(drive.GoogleDriveAccessError):
        drive.list_google_drive_folder_files(folder_ref, opener=opener)
