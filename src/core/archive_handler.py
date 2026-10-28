"""Bounded ZIP/TAR extraction into instance-owned temporary directories."""

import atexit
import gzip
import re
import shutil
import stat
import struct
import tarfile
import tempfile
import unicodedata
import zipfile
from pathlib import Path, PurePosixPath


class ArchiveError(Exception):
    pass


class ArchiveHandler:
    MAX_FILES = 16
    MAX_ENTRIES = 64
    MAX_ARCHIVE_BYTES = 128 * 1024 * 1024
    MAX_FILE_BYTES = 64 * 1024 * 1024
    MAX_EXPANDED_BYTES = 256 * 1024 * 1024
    AUDIO_EXTENSIONS = frozenset({".wav", ".aiff", ".aif", ".flac"})

    def __init__(self):
        self._temp_dirs = set()
        atexit.register(self.cleanup_all)

    def cleanup_all(self):
        for directory in tuple(self._temp_dirs):
            self.cleanup_temp_dir(directory)

    def cleanup_temp_dir(self, directory):
        path = str(Path(directory).absolute())
        if path not in self._temp_dirs:
            return
        self._temp_dirs.remove(path)
        shutil.rmtree(path, ignore_errors=True)

    @staticmethod
    def _safe_name(name):
        value = unicodedata.normalize("NFC", name)
        p = PurePosixPath(value)
        if (
            not value
            or ":" in value
            or any(ord(c) < 32 or ord(c) == 127 for c in value)
            or "\\" in value
            or "\x00" in value
            or p.is_absolute()
            or ".." in p.parts
            or re.match(r"^[A-Za-z]:", value)
        ):
            raise ArchiveError("압축 파일에 허용되지 않는 경로가 있습니다.")
        return p

    def extract_archive(self, archive_path):
        source = Path(archive_path)
        if not source.is_file() or source.stat().st_size > self.MAX_ARCHIVE_BYTES:
            raise ArchiveError("압축 파일 크기는 128 MiB 이하여야 합니다.")
        supported, _ = self.is_archive_format_supported(source.name)
        if not supported:
            raise ArchiveError("ZIP 또는 TAR/TAR.GZ만 지원합니다.")
        root = Path(tempfile.mkdtemp(prefix="drum-quanta-archive-"))
        self._temp_dirs.add(str(root))
        counters = {"entries": 0, "files": 0, "bytes": 0}
        names = set()
        paths = []

        def extract_entry(name, size, is_dir, is_regular, opener):
            counters["entries"] += 1
            if counters["entries"] > self.MAX_ENTRIES:
                raise ArchiveError("압축 항목 수 제한을 초과했습니다.")
            relative = self._safe_name(name)
            if not is_regular and not is_dir:
                raise ArchiveError(
                    "심볼릭 링크·하드 링크·특수 파일은 지원하지 않습니다."
                )
            if is_dir:
                return
            counters["bytes"] += size
            if (
                size < 0
                or size > self.MAX_FILE_BYTES
                or counters["bytes"] > self.MAX_EXPANDED_BYTES
            ):
                raise ArchiveError("압축 해제 크기 제한을 초과했습니다.")
            if (
                "__MACOSX" in relative.parts
                or relative.name == ".DS_Store"
                or relative.name.startswith("._")
            ):
                return
            if relative.suffix.lower() not in self.AUDIO_EXTENSIONS:
                raise ArchiveError("압축 파일에는 WAV·AIFF·FLAC 오디오만 넣어주세요.")
            counters["files"] += 1
            key = relative.name.casefold()
            if key in names:
                raise ArchiveError("중복 파일 이름은 지원하지 않습니다.")
            names.add(key)
            if counters["files"] > self.MAX_FILES:
                raise ArchiveError("오디오 트랙은 최대 16개입니다.")
            target = root.joinpath(*relative.parts)
            if not target.resolve().is_relative_to(root.resolve()):
                raise ArchiveError("압축 경로가 작업 폴더를 벗어납니다.")
            target.parent.mkdir(parents=True, exist_ok=True)
            copied = 0
            with opener() as stream, target.open("xb") as output:
                while chunk := stream.read(128 * 1024):
                    copied += len(chunk)
                    if copied > size or copied > self.MAX_FILE_BYTES:
                        raise ArchiveError(
                            "압축 항목의 실제 크기가 제한을 초과했습니다."
                        )
                    output.write(chunk)
            if copied != size:
                raise ArchiveError("압축 항목 크기가 일치하지 않습니다.")
            paths.append(str(target))

        try:
            if source.suffix.lower() == ".zip":
                with source.open("rb") as raw:
                    self._preflight_zip(raw)
                    raw.seek(0)
                    with zipfile.ZipFile(raw) as archive:
                        if len(archive.infolist()) > self.MAX_ENTRIES:
                            raise ArchiveError("압축 항목 수 제한을 초과했습니다.")
                        for item in archive.infolist():
                            mode = item.external_attr >> 16
                            regular = stat.S_IFMT(mode) in (0, stat.S_IFREG)
                            directory = item.is_dir() and stat.S_IFMT(mode) in (
                                0,
                                stat.S_IFDIR,
                            )
                            extract_entry(
                                item.filename,
                                item.file_size,
                                directory,
                                regular,
                                lambda item=item: archive.open(item),
                            )
            else:
                with (
                    source.open("rb") as raw,
                    (
                        gzip.GzipFile(fileobj=raw)
                        if source.name.lower().endswith((".gz", ".tgz"))
                        else raw
                    ) as decoded,
                    tarfile.open(
                        fileobj=_BoundedReader(
                            decoded, self.MAX_EXPANDED_BYTES + 65536
                        ),
                        mode="r|",
                    ) as archive,
                ):
                    for item in archive:
                        extract_entry(
                            item.name,
                            item.size,
                            item.isdir(),
                            item.isfile(),
                            lambda item=item: archive.extractfile(item),
                        )
            if not paths:
                raise ArchiveError("지원하는 오디오 트랙이 없습니다.")
            return str(root), sorted(paths)
        except Exception as error:
            self.cleanup_temp_dir(root)
            if isinstance(error, ArchiveError):
                raise
            raise ArchiveError("압축 파일을 안전하게 읽지 못했습니다.") from error

    def _preflight_zip(self, stream):
        """Bound central-directory parsing before ZipFile allocates its entry list.

        This bounded audio format uses single-disk ZIP32. ZIP64 end records and
        optional central-directory signatures are intentionally unsupported.
        """
        stream.seek(0, 2)
        size = stream.tell()
        if size > self.MAX_ARCHIVE_BYTES or size < 22:
            raise ArchiveError("ZIP 크기가 올바르지 않습니다.")
        tail_size = min(size, 22 + 65535)
        stream.seek(size - tail_size)
        tail = stream.read(tail_size)
        # Match the stdlib's last-signature interpretation and fail closed;
        # never accept an earlier record if the last signature is malformed.
        cursor = tail.rfind(b"PK\x05\x06")
        if cursor < 0 or cursor + 22 > len(tail):
            raise ArchiveError("ZIP 종료 정보가 올바르지 않습니다.")
        end_record = struct.unpack("<4s4H2IH", tail[cursor : cursor + 22])
        if cursor + 22 + end_record[7] != len(tail):
            raise ArchiveError("ZIP 종료 주석 경계가 올바르지 않습니다.")
        end_position = size - tail_size + cursor
        # CPython consults these ZIP64 records even without ZIP32 sentinels.
        # They can be hidden inside a central-entry comment; reject before
        # ZipFile can replace our checked ZIP32 bounds with ZIP64 values.
        for distance, signature in ((20, b"PK\x06\x07"), (76, b"PK\x06\x06")):
            if end_position >= distance:
                stream.seek(end_position - distance)
                if stream.read(4) == signature:
                    raise ArchiveError("ZIP64 종료 정보는 지원하지 않습니다.")
        _, disk, central_disk, disk_count, count, central_size, offset, _ = end_record
        if (
            disk
            or central_disk
            or disk_count != count
            or count == 65535
            or central_size == 0xFFFFFFFF
            or offset == 0xFFFFFFFF
        ):
            raise ArchiveError("분할 ZIP·ZIP64는 지원하지 않습니다.")
        if count > self.MAX_ENTRIES:
            raise ArchiveError("압축 항목 수 제한을 초과했습니다.")
        end = offset + central_size
        if end != size - tail_size + cursor:
            raise ArchiveError("ZIP 중앙 목록 경계가 올바르지 않습니다.")
        stream.seek(offset)
        seen = 0
        while stream.tell() < end:
            seen += 1
            if seen > self.MAX_ENTRIES:
                raise ArchiveError("압축 항목 수 제한을 초과했습니다.")
            header = stream.read(46)
            if len(header) != 46 or header[:4] != b"PK\x01\x02":
                raise ArchiveError("ZIP 중앙 목록이 올바르지 않습니다.")
            name_size, extra_size, comment_size = struct.unpack_from("<3H", header, 28)
            next_position = stream.tell() + name_size + extra_size + comment_size
            if next_position > end:
                raise ArchiveError("ZIP 중앙 항목 경계가 올바르지 않습니다.")
            stream.seek(next_position)
        if seen != count:
            raise ArchiveError("ZIP 항목 수가 일치하지 않습니다.")

    @staticmethod
    def is_archive_format_supported(filename):
        lower = str(filename).lower()
        return (
            any(lower.endswith(ext) for ext in (".zip", ".tar", ".tar.gz", ".tgz")),
            None,
        )

    @staticmethod
    def get_archive_info(archive_path):
        path = Path(archive_path)
        return {
            "filename": path.name,
            "size_mb": path.stat().st_size / 1024**2,
            "supported": ArchiveHandler.is_archive_format_supported(path.name)[0],
        }


class _BoundedReader:
    """Count decoded TAR bytes including parser metadata, before tarfile consumes them."""

    def __init__(self, source, limit):
        self.source, self.remaining = source, limit

    def read(self, size=-1):
        amount = self.remaining + 1 if size < 0 else min(size, self.remaining + 1)
        block = self.source.read(amount)
        self.remaining -= len(block)
        if self.remaining < 0:
            raise ArchiveError("TAR 스트림 크기 제한을 초과했습니다.")
        return block
