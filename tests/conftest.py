"""시험용 가짜 Flow 는 이미지·영상을 1초도 안 걸려 만들기 때문에, '이렇게 빨리 생길 수 없다' 검사를 끈다."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "cavn_music"))

import flow_maker  # noqa: E402

flow_maker.NEW_GRACE_SEC = 0
