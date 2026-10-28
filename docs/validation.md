# 검증

## 실제 엔진과 CLI

Python 3.12.13 / 3.13.7의 각각 별도 venv에서 hash가 고정된 audio·개발 dependency를 설치했습니다. CLI는 `Session.analyze → Session.quantize → Session.export`를 직접 호출합니다. 기존 독립 트랙 검출 pipeline은 이 증거에 사용하지 않았으며 공개 source에서 제외합니다.

짧은 8 kHz 3초 impulse/tone 트랙을 테스트 코드에서 생성합니다. 실제 reference 감지는 4개이고 kick·snare 두 트랙에 같은 onset·target plan을 적용합니다. snare=0.5×kick 관계와 미선택 room 원본 samples 보존을 실제 출력 WAV와 ZIP 내부 WAV를 각각 decode하여 확인합니다. 강도0·감지0·leading audio·readonly input0444 hash/mode·출력0600·기존 출력 거부·실패 시 자체 scratch 정리도 검증합니다. 개인 녹음은 사용하지 않았습니다.

ZIP은 중앙 목록을 최대64개 bounded seek로 먼저 검사한 뒤 ZipFile parser를 엽니다. 선언한 항목 수가 실제 중앙 목록과 다른 경우도 거부합니다. 안전 회귀는 ZIP traversal·symlink·개수·expanded bytes, TAR symlink·hardlink·FIFO·traversal·압축 parser metadata 상한, 실제 정상 TAR.GZ, 오디오 채널·샘플레이트·길이·총 samples 제한을 포함합니다. 잘못된 archive/reference/strength 및 부분 export 실패에서 원본·이웃 파일을 보존합니다.

## 의존성과 실행 경계

정상 resolver로 만든 새 환경에서 `pip check`가 통과했고 기본 `pip-audit`의 잔존 취약점은0건입니다. Gradio·Pillow·Matplotlib는 runtime lock과 새 환경의 metadata에 존재하지 않습니다. 예외 목록, 강제 dependency 상한 무시, `--no-deps`를 사용하지 않았습니다. 폐기한 웹 후보의 설치·취약점 실패·API 검증은 공개 source 밖의 감사 이력에 보존했으며 CLI의 성공 증거로 바꾸지 않았습니다.

CLI는 네트워크·브라우저·마이크를 열지 않습니다. POSIX directory descriptor와 exclusive create로 기존 출력을 보호하며 작업 중 이 실행이 만든 파일만 정리합니다. 같은 사용자 권한의 악성 프로세스, 디스크 손상·전원 장애, Windows, 실제 DAW 청감·상업 녹음 품질은 검증 범위가 아닙니다. 공통 계획 검증을 완벽한 위상·클릭 제거 주장으로 확대하지 않습니다.

CI는 Python 3.12/3.13에서 설치·Ruff·pytest·pip check·audit를 실행합니다. action은 commit SHA로 고정하고 `contents: read`만 부여하며 배포하지 않습니다. 원격 CI 결과는 source 설정과 별도입니다.

첫 공개 선별본에서 발견된 기존 GUI/Windows build·Release workflow 두 개를 제외하고 검증 전용 `ci.yml`만 유지했습니다. 이전 동결본과 실패 지적은 별도 감사 이력에 보존했습니다.

ZIP32 comment 안에 ZIP64 end/locator를 숨긴 5,870-byte 합성 입력이 기존 사전 검사 뒤 stdlib의65-entry 할당을 유발하는 해석 차이를 재현했습니다. stdlib가 조회하는 종료 위치의 ZIP64 기록을 먼저 거부하고, 마지막 EOCD signature가 잘못되면 이전 record로 되돌아가지 않도록 수정했습니다. 두 실제 회귀의 RED와 이전R2는 보존했습니다.
