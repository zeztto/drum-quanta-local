"""Local CLI: analyze once, apply one reference plan, create a new output directory."""

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

from src.core.archive_handler import ArchiveError
from src.core.session import Session
from src.utils.config import Config


def parser():
    result = argparse.ArgumentParser(
        description="단일 기준 계획을 여러 mono 트랙에 적용합니다."
    )
    result.add_argument("--input", required=True, help="ZIP/TAR/TAR.GZ 압축 파일")
    result.add_argument(
        "--reference", required=True, help="압축 내부 기준 트랙 basename"
    )
    result.add_argument(
        "--apply", action="append", required=True, help="적용할 basename, 여러 번 지정"
    )
    result.add_argument("--bpm", type=float, required=True)
    result.add_argument("--grid", choices=list(Config.GRID_DIVISIONS), default="1/16")
    result.add_argument(
        "--strength", type=float, default=80, help="0–100, 0은 원본 samples"
    )
    result.add_argument("--output", required=True, help="아직 존재하지 않는 출력 폴더")
    return result


def run(args):
    # A new private directory is reserved exclusively. Writes use its open descriptor,
    # never a user-supplied child path. Existing outputs are never removed or replaced.
    requested = Path(args.output).absolute()
    parent = requested.parent.resolve(strict=True)
    output = parent / requested.name
    output.mkdir(mode=0o700)
    descriptor = None
    owned = []
    session = None
    identity = output.stat()
    try:
        descriptor = os.open(output, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        actual = os.fstat(descriptor)
        if (actual.st_dev, actual.st_ino) != (identity.st_dev, identity.st_ino):
            raise OSError("출력 폴더가 변경되었습니다.")
        session = Session()
        session.analyze(args.input)
        report = session.quantize(
            args.reference, args.apply, args.bpm, args.grid, args.strength
        )
        generated = session.export()
        records = []
        for source_name in generated:
            source = Path(source_name)
            handle = os.open(
                source.name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=descriptor,
            )
            owned.append(source.name)
            digest = hashlib.sha256()
            size = 0
            with os.fdopen(handle, "wb") as destination, source.open("rb") as origin:
                while block := origin.read(128 * 1024):
                    destination.write(block)
                    digest.update(block)
                    size += len(block)
                destination.flush()
                os.fsync(destination.fileno())
            records.append(
                {"path": source.name, "bytes": size, "sha256": digest.hexdigest()}
            )
        report.update(
            {
                "schema": 1,
                "bpm": args.bpm,
                "grid": args.grid,
                "strength": args.strength,
                "sample_rate": session.sample_rate,
                "original_onsets": session.onsets.tolist(),
                "target_onsets": session.targets.tolist(),
                "files": records,
            }
        )
        handle = os.open(
            "processing-report.json",
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=descriptor,
        )
        owned.append("processing-report.json")
        with os.fdopen(handle, "w") as destination:
            json.dump(report, destination, ensure_ascii=False, indent=2)
            destination.write("\n")
            destination.flush()
            os.fsync(destination.fileno())
        return report
    except Exception:
        if descriptor is not None:
            for name in owned:
                try:
                    os.unlink(name, dir_fd=descriptor)
                except OSError:
                    pass
        try:
            current = output.lstat()
            if (current.st_dev, current.st_ino) == (identity.st_dev, identity.st_ino):
                output.rmdir()  # Only succeeds for the same now-empty directory.
        except OSError:
            pass
        raise
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if session is not None:
            session.close()


def main(argv=None):
    args = parser().parse_args(argv)
    if os.name != "posix":
        print(
            "오류: 이 CLI는 POSIX 파일 권한·descriptor를 지원하는 macOS/Linux용입니다.",
            file=sys.stderr,
        )
        return 2
    try:
        report = run(args)
    except FileExistsError:
        print(
            "오류: 출력 폴더가 이미 존재합니다. 새 경로를 지정하세요.", file=sys.stderr
        )
        return 2
    except (ArchiveError, ValueError) as error:
        print("오류: " + str(error), file=sys.stderr)
        return 2
    except (OSError, RuntimeError, TypeError, KeyError, ImportError):
        print(
            "오류: 파일을 처리하지 못했습니다. 압축·오디오·출력 권한을 확인하세요.",
            file=sys.stderr,
        )
        return 2
    print(json.dumps({"status": "ok", **report}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
