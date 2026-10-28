# 변경 기록

## 1.0.0 — 2026-10-28

- 단일 기준 onset·target 계획을 선택한 mono 트랙 전체에 적용하는 CLI와 WAV·ZIP·JSON 출력을 공개 범위로 정리했습니다.
- 강도0·감지0·leading audio를 보존하고, 감지 envelope와 threshold의 normalization 단위 불일치를 수정했습니다.
- ZIP central-directory 사전 제한과 bounded ZIP/TAR extraction, 링크·특수 파일 거부, stream·항목·크기·오디오 제한과 실행별 작업 폴더를 적용했습니다.
- 새 출력 전용·POSIX directory descriptor·0600 파일·자체 파일만 실패 정리를 적용했습니다.
- Gradio·Matplotlib·Pillow와 웹 entry, 별도 트랙 검출 pipeline을 공개 범위에서 제외했습니다. 정상 resolver로 설치되는 audio 전용 hash lock과 Python 3.12/3.13 회귀·의존성 감사를 추가했습니다.
- 기존 GUI/Windows packaging·Release workflow를 공개 allowlist에서 제외하고 검증 CI만 유지합니다.
- ZIP64 locator의 숨김·마지막 EOCD 해석 차이를 constructor 이전에 거부합니다.
