"""YouTube 스튜디오 '언어' 화면에 표시되는 언어 이름과 언어 코드 매핑.

각 항목: (언어코드, 한국어 이름들, 영어 이름들)
- 첫 번째 한국어 이름이 스튜디오(한국어 UI)에 보이는 대표 이름입니다.
- 나머지는 스튜디오 표기가 바뀌었거나 파일 이름에 다르게 적었을 때를 위한 별칭입니다.
스튜디오 표기가 다르면 config.json 의 "language_aliases" 에 추가하면 됩니다.
"""

import re
import unicodedata

LANGUAGES = [
    ("af", ["아프리칸스어"], ["Afrikaans"]),
    ("am", ["암하라어"], ["Amharic"]),
    ("ar", ["아랍어"], ["Arabic"]),
    ("as", ["아삼어"], ["Assamese"]),
    ("az", ["아제르바이잔어"], ["Azerbaijani"]),
    ("be", ["벨라루스어"], ["Belarusian"]),
    ("bg", ["불가리아어"], ["Bulgarian"]),
    ("bn", ["벵골어", "뱅골어"], ["Bengali", "Bangla"]),
    ("bs", ["보스니아어"], ["Bosnian"]),
    ("ca", ["카탈로니아어", "카탈루냐어"], ["Catalan"]),
    ("cs", ["체코어"], ["Czech"]),
    ("cy", ["웨일스어"], ["Welsh"]),
    ("da", ["덴마크어"], ["Danish"]),
    ("de", ["독일어"], ["German"]),
    ("el", ["그리스어"], ["Greek"]),
    ("en", ["영어"], ["English"]),
    ("en-GB", ["영어(영국)"], ["English (United Kingdom)", "English (UK)"]),
    ("es", ["스페인어"], ["Spanish"]),
    ("es-419", ["스페인어(라틴 아메리카)", "스페인어(중남미)"], ["Spanish (Latin America)"]),
    ("es-US", ["스페인어(미국)"], ["Spanish (United States)"]),
    ("et", ["에스토니아어"], ["Estonian"]),
    ("eu", ["바스크어"], ["Basque"]),
    ("fa", ["페르시아어"], ["Persian", "Farsi"]),
    ("fi", ["핀란드어"], ["Finnish"]),
    ("fil", ["필리핀어", "필리핀어(타갈로그어)", "타갈로그어"], ["Filipino", "Tagalog", "tl"]),
    ("fr", ["프랑스어"], ["French"]),
    ("fr-CA", ["프랑스어(캐나다)"], ["French (Canada)"]),
    ("gl", ["갈리시아어"], ["Galician"]),
    ("gu", ["구자라트어"], ["Gujarati"]),
    ("hi", ["힌디어"], ["Hindi"]),
    ("hr", ["크로아티아어"], ["Croatian"]),
    ("hu", ["헝가리어"], ["Hungarian"]),
    ("hy", ["아르메니아어"], ["Armenian"]),
    ("id", ["인도네시아어"], ["Indonesian"]),
    ("is", ["아이슬란드어"], ["Icelandic"]),
    ("it", ["이탈리아어"], ["Italian"]),
    ("iw", ["히브리어"], ["Hebrew", "he"]),
    ("ja", ["일본어"], ["Japanese"]),
    ("ka", ["조지아어", "그루지야어"], ["Georgian"]),
    ("kk", ["카자흐어", "카자흐스탄어"], ["Kazakh"]),
    ("km", ["크메르어", "캄보디아어"], ["Khmer"]),
    ("kn", ["칸나다어"], ["Kannada"]),
    ("ko", ["한국어"], ["Korean"]),
    ("ky", ["키르기스어", "키르기스스탄어"], ["Kyrgyz"]),
    ("lo", ["라오어", "라오스어"], ["Lao"]),
    ("lt", ["리투아니아어"], ["Lithuanian"]),
    ("lv", ["라트비아어"], ["Latvian"]),
    ("mk", ["마케도니아어"], ["Macedonian"]),
    ("ml", ["말라얄람어"], ["Malayalam"]),
    ("mn", ["몽골어"], ["Mongolian"]),
    ("mr", ["마라티어"], ["Marathi"]),
    ("ms", ["말레이어", "말레이시아어"], ["Malay"]),
    ("my", ["미얀마어", "버마어", "미얀마어(버마어)"], ["Burmese", "Myanmar"]),
    ("ne", ["네팔어"], ["Nepali"]),
    ("nl", ["네덜란드어"], ["Dutch"]),
    ("no", ["노르웨이어"], ["Norwegian"]),
    ("or", ["오리야어", "오디아어"], ["Odia", "Oriya"]),
    ("pa", ["펀자브어", "펀잡어"], ["Punjabi"]),
    ("pl", ["폴란드어"], ["Polish"]),
    ("pt", ["포르투갈어"], ["Portuguese"]),
    ("pt-BR", ["포르투갈어(브라질)"], ["Portuguese (Brazil)"]),
    ("pt-PT", ["포르투갈어(포르투갈)"], ["Portuguese (Portugal)"]),
    ("ro", ["루마니아어"], ["Romanian"]),
    ("ru", ["러시아어"], ["Russian"]),
    ("si", ["싱할라어", "스리랑카어"], ["Sinhala"]),
    ("sk", ["슬로바키아어"], ["Slovak"]),
    ("sl", ["슬로베니아어"], ["Slovenian"]),
    ("sq", ["알바니아어"], ["Albanian"]),
    ("sr", ["세르비아어"], ["Serbian"]),
    ("sv", ["스웨덴어"], ["Swedish"]),
    ("sw", ["스와힐리어"], ["Swahili"]),
    ("ta", ["타밀어"], ["Tamil"]),
    ("te", ["텔루구어"], ["Telugu"]),
    ("th", ["태국어"], ["Thai"]),
    ("tr", ["튀르키예어", "터키어"], ["Turkish"]),
    ("uk", ["우크라이나어"], ["Ukrainian"]),
    ("ur", ["우르두어"], ["Urdu"]),
    ("uz", ["우즈베크어", "우즈베키스탄어"], ["Uzbek"]),
    ("vi", ["베트남어"], ["Vietnamese"]),
    ("zh-Hans", ["중국어(간체)", "중국어 간체"], ["Chinese (Simplified)", "zh-CN", "zh"]),
    ("zh-Hant", ["중국어(번체)", "중국어 번체"], ["Chinese (Traditional)", "zh-TW"]),
    ("zh-HK", ["중국어(홍콩)"], ["Chinese (Hong Kong)"]),
    ("zu", ["줄루어"], ["Zulu"]),
    # 구글 번역기에서 지원하는 추가 언어 (번역 프로그램의 '새로운 언어 추가' 목록과 맞춤)
    ("ceb", ["세부아노어"], ["Cebuano"]),
    ("ny", ["치체와어", "치츄아어", "니안자어"], ["Chichewa", "Nyanja"]),
    ("co", ["코르시카어"], ["Corsican"]),
    ("eo", ["에스페란토어", "에스페란토"], ["Esperanto"]),
    ("fy", ["프리지아어", "서부 프리지아어"], ["Frisian", "Western Frisian"]),
    ("ht", ["아이티 크리올어", "아이티어"], ["Haitian Creole", "Haitian"]),
    ("ha", ["하우사어"], ["Hausa"]),
    ("haw", ["하와이어"], ["Hawaiian"]),
    ("hmn", ["몽어", "흐몽어"], ["Hmong"]),
    ("ig", ["이보어"], ["Igbo"]),
    ("ga", ["아일랜드어"], ["Irish"]),
    ("jv", ["자바어"], ["Javanese", "jw"]),
    ("ku", ["쿠르드어"], ["Kurdish"]),
    ("la", ["라틴어"], ["Latin"]),
    ("lb", ["룩셈부르크어"], ["Luxembourgish"]),
    ("mg", ["말라가시어"], ["Malagasy"]),
    ("mt", ["몰타어"], ["Maltese"]),
    ("mi", ["마오리어"], ["Maori"]),
    ("ps", ["파슈토어"], ["Pashto"]),
    ("sm", ["사모아어"], ["Samoan"]),
    ("gd", ["스코틀랜드 게일어"], ["Scottish Gaelic"]),
    ("st", ["세소토어", "남부 소토어"], ["Sesotho", "Southern Sotho"]),
    ("sn", ["쇼나어"], ["Shona"]),
    ("sd", ["신디어"], ["Sindhi"]),
    ("so", ["소말리어", "소말리아어"], ["Somali"]),
    ("su", ["순다어"], ["Sundanese"]),
    ("tg", ["타지크어"], ["Tajik"]),
    ("ug", ["위구르어"], ["Uyghur"]),
    ("xh", ["코사어"], ["Xhosa"]),
    ("yi", ["이디시어"], ["Yiddish"]),
    ("yo", ["요루바어"], ["Yoruba"]),
]


def normalize(text: str) -> str:
    """비교용 정규화: 대소문자, 공백, 괄호, 밑줄/하이픈 차이를 무시."""
    text = unicodedata.normalize("NFC", text).lower()
    return re.sub(r"[\s()\[\]_\-.]+", "", text)


class LanguageTable:
    def __init__(self, extra_aliases=None):
        self.extra_aliases = dict(extra_aliases or {})
        # 정규화된 이름 -> 언어코드
        self._by_name = {}
        self._names = {}
        for code, ko_names, en_names in LANGUAGES:
            self._names[code] = ko_names[0]
            for name in [code, *ko_names, *en_names]:
                self._by_name.setdefault(normalize(name), code)
        for alias, code in (extra_aliases or {}).items():
            self._by_name[normalize(alias)] = code
            self._names.setdefault(code, alias)

    def code_for(self, name: str):
        """언어 이름(스튜디오 표기, 파일 이름 등) -> 언어코드. 모르면 None."""
        return self._by_name.get(normalize(name))

    def display_name(self, code: str) -> str:
        return self._names.get(code, code)

    def match_filename(self, stem: str):
        """파일 이름(확장자 제외)에서 언어코드를 찾는다.

        'gu', '구자라트어', 'Gujarati', '03_gu', 'thumb_gu', '구자라트어_썸네일' 등을 허용.
        """
        code = self.code_for(stem)
        if code:
            return code
        # 구분자로 나눈 조각 중 언어 이름/코드와 일치하는 것을 찾는다 (긴 조각 우선).
        parts = [p for p in re.split(r"[\s_\-.]+", stem) if p]
        for part in sorted(parts, key=len, reverse=True):
            code = self.code_for(part)
            if code and not part.isdigit():
                return code
        # 'Chinese (Simplified)' 같은 여러 단어 이름이 포함된 경우
        norm_stem = normalize(stem)
        best = None
        for name, code in self._by_name.items():
            if len(name) >= 4 and name in norm_stem:
                if best is None or len(name) > len(best[0]):
                    best = (name, code)
        return best[1] if best else None
