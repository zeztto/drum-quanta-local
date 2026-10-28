# 외부 라이브러리 고지

자체 MIT License는 외부 package의 원 저작권·라이선스를 변경하지 않습니다. 검증 환경에 설치된 runtime·개발 도구 50개 package의 버전, 원문 위치와 hash는 [index.json](third-party-licenses/index.json)에 기록했습니다. wheel에 포함된 원문을 byte 그대로 복사했으며, packageurl-python은 동일 버전 공식 PyPI sdist의 SHA-256을 확인한 뒤 포함된 MIT 원문을 복사했습니다.

- NumPy·SciPy·librosa: 각 BSD 계열 원문 및 포함된 구성 요소 조건을 따릅니다. NumPy의 random·pocketfft·LAPACK 등 고지와 SciPy의 Qhull 등 고지도 함께 보존합니다.
- SoundFile은 BSD 계열이며 wheel에 동봉된 **libsndfile은 LGPL-2.1 계열**입니다. `_soundfile_data/COPYING`과 licensing notes를 보존했습니다. 설치 환경에서 native library를 교체·재배포하는 경우 해당 원문과 소스 제공·재링크 등의 조건을 별도로 따라야 합니다.
- llvmlite·Numba 및 그 외 runtime·개발 도구는 복사한 원문 조건을 따릅니다. 외부 native binary 자체는 이 source 저장소에 동봉하지 않습니다.
- 개인 녹음, 상용 음원, 외부 이미지·폰트는 동봉하지 않습니다. 테스트의 신호는 테스트 코드가 자체 생성하며 사용자 녹음이나 청감 승인 증거가 아닙니다.

다른 플랫폼의 wheel이나 새로운 버전을 배포할 때는 그 실제 배포물의 고지를 다시 수집해야 합니다. Gradio·Matplotlib·Pillow는 공개 CLI의 설치 lock에 포함하지 않습니다.
