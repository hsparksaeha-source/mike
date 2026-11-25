"""캐릭터목록.txt 의 [인물 설명] (키 등) 을 이미지·영상 요청 글에 붙이기."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "cavn_music"))

import cast  # noqa: E402

LIST = """프로젝트: 캐릭터목록
[칸쏘네1]
여: 쥴리
남: 마태오

[인물 설명]
쥴리: 키 185센티미터의 큰 키
마태오: 키 195센티미터의 큰 키
# 서준: 주석은 안 읽음
"""


def test_traits_are_not_a_group_and_go_into_requests(tmp_path):
    f = tmp_path / "캐릭터목록.txt"
    f.write_text(LIST, encoding="utf-8")
    project, groups = cast.load_cast(f)
    assert list(groups) == ["칸쏘네1"]
    traits = cast.load_traits(f)
    assert traits == {"쥴리": "키 185센티미터의 큰 키", "마태오": "키 195센티미터의 큰 키"}
    assert cast.traits_text(["쥴리", "마태오"], traits, what="이미지 15장") == (
        "쥴리 키 185센티미터의 큰 키, 마태오 키 195센티미터의 큰 키, 이 키를 그대로 반영해서 가사에 맞게 이미지 15장 만들어 주세요.")
    assert cast.traits_text(["마태오"], traits, what="영상").endswith("영상을 만들어 주세요.")
    assert cast.traits_text(["서준"], traits) == ""


def test_real_list_has_heights_for_canzone():
    traits = cast.load_traits()
    assert "185" in traits["쥴리"] and "195" in traits["브루노"]
