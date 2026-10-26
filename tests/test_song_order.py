"""노래 파일 날짜를 트랙 순서로 맞추기 (캡컷 조립 프로그램이 날짜순으로 줄 세움)."""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "cavn_music"))

from md_parser import Track  # noqa: E402
from song_order import fix_song_order  # noqa: E402


def test_files_follow_track_order(tmp_path):
    tracks = [Track(1, "Love"), Track(2, "Love Song"), Track(3, "Café: Night?"), Track(4, "Rain")]
    names = ["Love.wav", "Love (1).wav", "Love_mastered.wav", "Love Song.wav", "Love Song (1).wav",
             "Café_ Night_.wav", "Café_ Night_ (1).wav", "Café_ Night_.lrc", "Rain.wav", "Rain (1).wav",
             "Rain_구간라벨.txt", "다른곡.wav"]
    # 3·4번 곡을 나중에 받은 것처럼: 1, 2, 4번이 먼저, 3번이 제일 늦게
    late = {"Café_ Night_.wav": 900, "Café_ Night_ (1).wav": 901, "Café_ Night_.lrc": 902}
    for k, n in enumerate(names):
        (tmp_path / n).write_text(n)
        when = 1_000_000 + late.get(n, k)
        os.utime(tmp_path / n, (when, when))

    assert fix_song_order(tmp_path, tracks, base=2_000_000) == 11      # '다른곡' 은 건드리지 않음
    wavs = sorted((p for p in tmp_path.glob("*.wav") if p.name != "다른곡.wav"), key=lambda p: p.stat().st_mtime)
    assert [p.name for p in wavs] == ["Love.wav", "Love (1).wav", "Love_mastered.wav", "Love Song.wav",
                                      "Love Song (1).wav", "Café_ Night_.wav", "Café_ Night_ (1).wav",
                                      "Rain.wav", "Rain (1).wav"]
    assert (tmp_path / "다른곡.wav").stat().st_mtime == 1_000_011
