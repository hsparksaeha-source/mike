"""일괄 작업 시험: md 여러 개 → 종류에 맞는 단계를 차례로 부르고, 실패해도 다음으로 넘어가는지.

실행: python -m pytest tests/test_batch_maker.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "cavn_music"))
sys.path.insert(0, str(ROOT / "tests"))

import batch_maker  # noqa: E402
from test_cavn_maker import EASY_MD, POP_MD, SACRED_MD  # noqa: E402
from test_thumb_maker import EASY  # noqa: E402


def test_batch_runs_steps_in_order(tmp_path, monkeypatch):
    easy = tmp_path / "경음악3집.md"
    easy.write_text(EASY_MD + EASY.split("# PART B.", 1)[1].join(["# PART B.", ""]), encoding="utf-8")
    pop = tmp_path / "카페소네트.md"
    pop.write_text(POP_MD, encoding="utf-8")
    sacred = tmp_path / "미사곡5집.md"
    sacred.write_text(SACRED_MD, encoding="utf-8")

    calls = []
    monkeypatch.setattr(batch_maker.cavn_maker, "run",
                        lambda md, out, **kw: calls.append(("노래", Path(md).stem, kw["master"], kw["confirm"])))

    def flow_run(md, out, **kw):
        calls.append(("이미지", Path(md).stem))
        assert kw.get("cast_group") == (None if "경음악" in str(md) else "칸쏘네")
        raise RuntimeError("Flow 가 멈춤")          # 실패해도 다음 단계로
    monkeypatch.setattr(batch_maker.flow_maker, "run", flow_run)
    monkeypatch.setattr(batch_maker.thumb_maker, "run", lambda md, out, **kw: calls.append(("썸네일", Path(md).stem)))
    monkeypatch.setattr(batch_maker, "prepare_flow", lambda: calls.append(("Flow 확인",)))
    answers = iter(["", "", "1", "n", "y"])   # 마스터링: 경음악 Enter(안 함), 가요 Enter(함) + 캐릭터 묶음 1, 미사곡 n, 시작 y
    monkeypatch.setattr("builtins.input", lambda *_: next(answers))
    monkeypatch.setattr(sys, "argv", ["batch_maker.py", str(easy), str(pop), str(sacred), "--out", str(tmp_path / "out")])

    batch_maker.main()

    assert calls == [
        ("Flow 확인",),
        ("노래", "경음악3집", 0, False), ("이미지", "경음악3집"), ("썸네일", "경음악3집"),
        ("노래", "카페소네트", 1, False), ("이미지", "카페소네트"),   # 가요: 캐릭터 + 가사로 이미지, 썸네일 문구 없음
        ("노래", "미사곡5집", 0, False),                        # 미사곡: 가사 있어서 이미지 안 함
    ]
    log = (tmp_path / "out" / "경음악3집" / "일괄작업기록.txt").read_text(encoding="utf-8")
    assert "이미지·영상 실패: Flow 가 멈춤" in log and "썸네일 끝" in log


def test_split_dropped_paths():
    line = '"C:\\음악 md\\앨범 1.md" C:\\md\\앨범2.md'
    assert batch_maker.split_paths(line) == ["C:\\음악 md\\앨범 1.md", "C:\\md\\앨범2.md"]
