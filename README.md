# Drum Quanta Local

하나의 기준 트랙에서 감지한 onset·cut plan을 선택한 mono 트랙에 공통 적용하는 로컬 **CLI 음악 편집 도구**입니다. 원본 압축 파일을 읽고 새 폴더에 float32 WAV와 ZIP, 처리 보고서를 만듭니다.

## 설치·실행

macOS 또는 Linux의 Python 3.12/3.13이 대상입니다. POSIX directory descriptor와 파일 권한을 사용하므로 Windows는 지원하지 않습니다.

```sh
python3.13 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements.lock
.venv/bin/python -m drum_quanta --help
```

동일 샘플레이트·길이·시작 위치를 가진 트랙을 ZIP 또는 TAR/TAR.GZ/TGZ로 묶은 다음 실행합니다. `--reference`와 `--apply`는 압축 내부의 파일 basename입니다. 출력 폴더는 아직 존재하지 않아야 합니다.

```sh
.venv/bin/python -m drum_quanta \
  --input tracks.zip \
  --reference kick.wav \
  --apply kick.wav --apply snare.wav \
  --bpm 120 --grid 1/16 --strength 80 \
  --output edited-tracks
```

`kick.wav`, `snare.wav`는 사용자가 준비한 파일명으로 바꿉니다. 개인 녹음이나 음원은 저장소에 들어 있지 않습니다. 기준 onset은 한 번만 감지하고, 같은 onset·target 배열과 5 ms 편집 경계를 모든 적용 트랙에 사용합니다. 미선택 트랙도 원본 samples 그대로 함께 내보냅니다. 강도 0 또는 감지 0개이면 samples를 이동하지 않습니다. leading audio도 유지합니다.

## 출력과 안전 경계

- 파일명 앞에 순번을 붙인 WAV와 `drum-quanta-tracks.zip`, `processing-report.json`을 새 출력 폴더에 만듭니다. 보고서에는 기준·적용 목록·원본/목표 onset samples·이동 통계·출력 SHA-256이 들어 있습니다.
- 출력은 WAV float32이며 자동 gain normalization이나 resampling을 하지 않습니다. 입력 hash·mode를 변경하지 않습니다. 이미 존재하는 출력 폴더·파일은 덮어쓰지 않습니다.
- 출력 폴더는 0700, 파일은 0600으로 생성합니다. 실패 시 이 실행이 만든 파일과 비어 있는 자체 출력 폴더만 정리합니다. 성공 보고서가 쓰이기 전의 폴더를 완성된 결과로 취급하지 마세요. 저장 장치 장애에 대한 전체 폴더 원자성을 보장하지 않습니다.
- 단일 디스크 ZIP32와 TAR 계열을 지원합니다. 분할 ZIP·ZIP64 종료 record는 지원하지 않습니다. 압축 입력 최대128 MiB, 오디오 최대16개, 압축 항목 최대64개, 파일별64 MiB, 총 해제256 MiB입니다. TAR parser metadata도 별도 stream 상한을 적용합니다. 절대경로·상위경로·링크·장치·중복 basename·비오디오 항목은 거부합니다. macOS 메타데이터는 제한 검사 후 건너뜁니다.
- WAV·AIFF·FLAC의 mono만 지원합니다. 각 트랙0초 초과~120초, 8–192 kHz, 전체1,600만 samples 이하입니다. 모든 트랙의 길이와 샘플레이트가 같아야 합니다. RAR·7z는 지원하지 않습니다.

공통 편집 계획은 선택한 트랙의 상대적인 편집 위치를 일치시킵니다. 완벽한 위상·클릭 제거·청감 품질을 보장하지 않습니다. 편집 경계에서 겹침·무음이 생기거나 마지막 이동 slice 때문에 적용 트랙 길이가 늘 수 있습니다. 미선택 트랙은 원래 길이를 유지합니다. 편집 뒤 DAW에서 길이·경계·청감을 확인하세요. 자동 BPM, 자동 마이크 지연 정렬, RMS 목표 레벨, AI 검출, GUI·웹 서버는 제공하지 않습니다.

## 개발·검증

```sh
.venv/bin/python -m pip install --require-hashes -r requirements-dev.lock
.venv/bin/python -m pytest -q
.venv/bin/ruff check drum_quanta.py src tests
.venv/bin/python -m pip check
.venv/bin/python -m pip_audit -r requirements.lock
```

테스트는 짧은 impulse/tone 합성 WAV를 임시 폴더에서만 생성합니다. 실제 CLI subprocess로 공통 계획·WAV/ZIP 독립 decode·강도0·감지0·입력0444 hash/mode 보존·출력 덮어쓰기 거부·실패 cleanup·archive 경계를 확인합니다. [검증 문서](docs/validation.md)는 범위와 미검증 항목을 구별합니다. CI는 검증만 수행하고 배포하지 않습니다.

자체 코드는 [MIT License](LICENSE), 외부 package와 포함된 native audio library의 원문 조건은 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)를 따릅니다.
