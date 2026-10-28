import stat
import zipfile

import numpy as np
import pytest

from src.core.archive_handler import ArchiveError, ArchiveHandler
from src.core.quantizer import Quantizer


def test_strength_zero_preserves_leading_audio_exactly():
    audio = np.linspace(-0.2, 0.2, 400)
    output = Quantizer.quantize(
        audio, np.array([100, 240]), 120, "1/16", 8000, strength=0
    )
    np.testing.assert_array_equal(output, audio)


def test_moved_plan_keeps_unmoved_leading_audio():
    audio = np.zeros(1000)
    audio[:80] = 0.1
    audio[200] = 0.5
    output = Quantizer._slice_and_reassemble(
        audio, np.array([200]), np.array([180]), 8000, 1
    )
    np.testing.assert_array_equal(output[:80], audio[:80])


def test_zero_hits_is_identity():
    audio = np.sin(np.arange(1000) / 10) * 0.1
    np.testing.assert_array_equal(
        Quantizer.quantize(audio, np.array([], dtype=int), 120, "1/16", 8000), audio
    )


@pytest.mark.parametrize(
    "name", ["../escape.wav", "/absolute.wav", "C:/escape.wav", "folder\\escape.wav"]
)
def test_archive_rejects_unsafe_names(tmp_path, name):
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr(name, b"not-audio")
    with pytest.raises(ArchiveError):
        ArchiveHandler().extract_archive(str(archive))


def test_archive_rejects_symlink(tmp_path):
    archive = tmp_path / "link.zip"
    info = zipfile.ZipInfo("link.wav")
    info.create_system = 3
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr(info, "outside.wav")
    with pytest.raises(ArchiveError):
        ArchiveHandler().extract_archive(str(archive))


def test_archive_count_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(ArchiveHandler, "MAX_FILES", 2, raising=False)
    archive = tmp_path / "many.zip"
    with zipfile.ZipFile(archive, "w") as output:
        for i in range(3):
            output.writestr(f"{i}.wav", b"not-audio")
    with pytest.raises(ArchiveError):
        ArchiveHandler().extract_archive(str(archive))


def test_cleanup_never_deletes_unowned_directory(tmp_path):
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    (unrelated / "sentinel").write_text("keep")
    ArchiveHandler().cleanup_temp_dir(str(unrelated))
    assert (unrelated / "sentinel").read_text() == "keep"


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "fifo", "traversal"])
def test_tar_rejects_links_special_files_and_traversal(tmp_path, kind):
    import io
    import tarfile

    archive = tmp_path / "bad.tar"
    info = tarfile.TarInfo("../outside.wav" if kind == "traversal" else "track.wav")
    info.type = {
        "symlink": tarfile.SYMTYPE,
        "hardlink": tarfile.LNKTYPE,
        "fifo": tarfile.FIFOTYPE,
        "traversal": tarfile.REGTYPE,
    }[kind]
    info.linkname = "/outside"
    info.size = 1 if kind == "traversal" else 0
    with tarfile.open(archive, "w") as tar:
        tar.addfile(info, io.BytesIO(b"x") if info.size else None)
    handler = ArchiveHandler()
    with pytest.raises(ArchiveError):
        handler.extract_archive(archive)
    assert handler._temp_dirs == set()
    assert not (tmp_path / "outside.wav").exists()


def test_expanded_size_limit_and_failure_cleanup(tmp_path, monkeypatch):
    monkeypatch.setattr(ArchiveHandler, "MAX_EXPANDED_BYTES", 7)
    archive = tmp_path / "size.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("a.wav", b"1234")
        z.writestr("b.wav", b"5678")
    handler = ArchiveHandler()
    with pytest.raises(ArchiveError):
        handler.extract_archive(archive)
    assert handler._temp_dirs == set()


def test_compressed_tar_parser_metadata_is_bounded_before_consumption(
    tmp_path, monkeypatch
):
    import gzip
    import tarfile

    monkeypatch.setattr(ArchiveHandler, "MAX_EXPANDED_BYTES", 64)
    info = tarfile.TarInfo("metadata")
    info.type = tarfile.XHDTYPE
    info.size = 100000
    archive = tmp_path / "metadata.tar.gz"
    archive.write_bytes(gzip.compress(info.tobuf() + b"x" * info.size + b"\0" * 1024))
    handler = ArchiveHandler()
    with pytest.raises(ArchiveError):
        handler.extract_archive(archive)
    assert not handler._temp_dirs


@pytest.mark.parametrize("forged_count", [False, True])
def test_zip_entry_limit_checked_before_zipfile_parser_allocation(
    tmp_path, monkeypatch, forged_count
):
    import struct

    archive = tmp_path / "central.zip"
    with zipfile.ZipFile(archive, "w") as z:
        for index in range(65):
            z.writestr(f"{index}.wav", b"")
    if forged_count:
        raw = bytearray(archive.read_bytes())
        offset = raw.rfind(b"PK\x05\x06")
        struct.pack_into("<2H", raw, offset + 8, 1, 1)
        archive.write_bytes(raw)

    def must_not_allocate(*args, **kwargs):
        raise AssertionError(
            "ZipFile parser must not run for an excessive central directory"
        )

    monkeypatch.setattr(zipfile, "ZipFile", must_not_allocate)
    with pytest.raises(ArchiveError, match="항목 수"):
        ArchiveHandler().extract_archive(archive)


def test_zip64_locator_hidden_in_zip32_comment_rejected_before_constructor(
    tmp_path, monkeypatch
):
    import io
    import struct

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
        for index in range(65):
            z.writestr(f"{index:02}.wav", b"")
    normal = buf.getvalue()
    fields = struct.unpack("<4s4H2IH", normal[-22:])
    cdsize, cdoff = fields[5], fields[6]
    fake = bytearray(normal[cdoff : cdoff + 52])
    struct.pack_into("<H", fake, 32, 76)
    fake[46:52] = b"ff.wav"
    end64 = struct.pack(
        "<4sQ2H2I4Q", b"PK\x06\x06", 44, 45, 45, 0, 0, 65, 65, cdsize, cdoff + 52
    )
    locator = struct.pack("<4sIQI", b"PK\x06\x07", 0, len(normal) - 22 + 52, 1)
    fake_cd = bytes(fake) + end64 + locator
    payload = (
        normal[:-22]
        + fake_cd
        + struct.pack(
            "<4s4H2IH", b"PK\x05\x06", 0, 0, 1, 1, len(fake_cd), len(normal) - 22, 0
        )
    )
    # Bounded synthetic control: the stdlib interprets ZIP64 despite the ZIP32 count.
    with zipfile.ZipFile(io.BytesIO(payload)) as z:
        assert len(z.infolist()) == 65
    archive = tmp_path / "hidden64.zip"
    archive.write_bytes(payload)
    constructor_calls = []
    original = zipfile.ZipFile

    def observe_constructor(*args, **kwargs):
        constructor_calls.append(True)
        return original(*args, **kwargs)

    monkeypatch.setattr(zipfile, "ZipFile", observe_constructor)
    with pytest.raises(ArchiveError):
        ArchiveHandler().extract_archive(archive)
    assert not constructor_calls, (
        "preflight must reject before the stdlib allocates its list"
    )


def test_zip_last_invalid_eocd_signature_does_not_fall_back():
    import io

    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as z:
        z.writestr("track.wav", b"")
        z.comment = b"prefix-PK\x05\x06-invalid"
    with pytest.raises(ArchiveError):
        ArchiveHandler()._preflight_zip(io.BytesIO(stream.getvalue()))
