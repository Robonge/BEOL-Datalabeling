"""화면 템플릿 정적 검사 (표준 라이브러리만 사용)."""
import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCREENS = os.path.join(os.path.dirname(HERE), "labelbot", "screens")
PLACEHOLDER = "/*__DATA__*/null"
FILES = ("compare.html", "review.html", "slides.html")


def read(name):
    with open(os.path.join(SCREENS, name), "r", encoding="utf-8") as f:
        return f.read()


class ScreenTemplateTests(unittest.TestCase):
    def test_placeholder_exactly_once(self):
        for name in FILES:
            text = read(name)
            self.assertEqual(text.count(PLACEHOLDER), 1, name)
            self.assertEqual(text.count("__DATA__"), 1, name)
            self.assertIn("const DATA = " + PLACEHOLDER + ";", text, name)

    def test_no_http_anywhere(self):
        for name in FILES:
            self.assertNotIn("http", read(name).lower(), name)

    def test_no_external_resources(self):
        for name in FILES:
            text = read(name)
            self.assertIsNone(re.search(r"<link\b", text, re.I), name)
            self.assertIsNone(re.search(r"\bsrc\s*=\s*[\"']", text, re.I), name)
            self.assertIsNone(re.search(r"<script[^>]*\bsrc\b", text, re.I), name)
            self.assertIsNone(re.search(r"@import", text, re.I), name)
            self.assertIsNone(re.search(r"(?<![A-Za-z.])url\(\s*[\"']?(?!data:)", text, re.I), name)
            self.assertEqual(len(re.findall(r"<script\b", text, re.I)), 1, name)

    def test_localstorage_is_guarded(self):
        for name in FILES:
            text = read(name)
            for m in re.finditer(r"localStorage", text):
                before = text[max(0, m.start() - 200):m.start()]
                self.assertIn("try", before, name)

    def test_review_has_file_slides(self):
        text = read("review.html")
        # 같은 파일 슬라이드 썸네일은 DATA.file_slides를 쓰고, 확대 중에는 j/k 검수 이동을 막는다.
        self.assertIn("DATA.file_slides", text)
        self.assertIn("function openSibZoom(list, i)", text)
        self.assertRegex(text, r'if \(zoom\.classList\.contains\("on"\)\)\{')

    def test_review_has_same_file_apply(self):
        text = read("review.html")
        # 같은 파일(불량 목록 안) chunk에 분류 축·공통 질문 답만 복사하고, 확인 창을 거친 뒤 저장한다.
        m = re.search(r"function sameFileFlagged\(c\)\{(.*?)\n  \}", text, re.S)
        self.assertIsNotNone(m)
        self.assertIn("x.file_id === c.file_id", m.group(1))
        m = re.search(r"function applyToSameFile\(c\)\{(.*?)\n  \}", text, re.S)
        self.assertIsNotNone(m)
        body = m.group(1)
        for s in ("window.confirm", "srcQ.indexOf(qid) < 0", "save();", "curAxis(c, ax.name)", "curAnswer(c, qid)"):
            self.assertIn(s, body)
        for s in ("status[", "syns", "revisits"):
            self.assertNotIn(s, body)
        self.assertIn("onclick:function(){ applyToSameFile(c); }", text)

    def test_review_has_revisits(self):
        text = read("review.html")
        # buildOutput 반환 객체에 revisits가 실린다.
        m = re.search(r"function buildOutput\(\)\{(.*?)\n  \}", text, re.S)
        self.assertIsNotNone(m)
        self.assertRegex(m.group(1), r"out\.revisits\s*=\s*rvOutput\(\)")
        self.assertRegex(m.group(1), r"return out;")
        # 상태 저장·불러오기·자동 저장 조건에 revisits가 포함된다.
        self.assertRegex(text, r"setItem\(KEY, JSON\.stringify\(\{[^}]*revisits:revisits")
        self.assertRegex(text, r"Array\.isArray\(o\.revisits\)")
        m = re.search(r"function hasState\(\)\{(.*?)\n  \}", text, re.S)
        self.assertIsNotNone(m)
        self.assertIn("revisits.length", m.group(1))
        # 입력 상한은 DATA에서 받는다.
        self.assertIn("DATA.revisit_memo_max", text)
        self.assertIn("DATA.revisit_short_max", text)
        self.assertIn("maxlength:String(RV_MEMO_MAX)", text)
        self.assertIn("maxlength:String(RV_SHORT_MAX)", text)
        # 규칙이 없는 예전 DATA에서는 기능을 숨긴다.
        self.assertIn("DATA.revisit_rules", text)
        self.assertRegex(text, r"var rvOn = !!\(RV_REASONS && RV_RULES\);")
        # copyText 출력에는 메모가 실리지 않는다(건수만).
        m = re.search(r"function copyText\(\)\{(.*?)\n  \}", text, re.S)
        self.assertIsNotNone(m)
        self.assertIn("delete o.revisits", m.group(1))
        # 메모·제안 값을 콘솔에 남기지 않는다.
        self.assertNotIn("console.", text)

    def test_review_revisit_rules_match_backend(self):
        text = read("review.html")
        # 예약어는 taxonomy.norm_key와 같은 정규화(NFKC, 소문자, 공백 제거)로 비교한다.
        self.assertIn('normalize("NFKC").toLowerCase().replace(/\\s+/g, "")', text)
        self.assertIn("RV_RESERVED.indexOf(rvNormKey(v))", text)
        self.assertIn("var RV_KEY_MAX = 100;", text)
        # 백엔드가 버리는 key('|' 포함, 100자 초과)는 버튼·출력에서 뺀다.
        m = re.search(r"function rvAllowed\(c, r\)\{(.*?)\n  \}", text, re.S)
        self.assertIsNotNone(m)
        self.assertIn('r.key.indexOf("|") >= 0 || rvLen(r.key) > RV_KEY_MAX', m.group(1))
        # rvFor는 chunk마다 revisits 전체를 훑지 않는다(chunk_id별 캐시).
        m = re.search(r"function rvFor\(c\)\{(.*?)\n  \}", text, re.S)
        self.assertIsNotNone(m)
        self.assertNotIn("revisits.filter", m.group(1))
        self.assertIn("rvByChunk", m.group(1))

    def test_review_has_evidence(self):
        text = read("review.html")
        # 근거 기능은 DATA.file_ctx가 있을 때만 켜고, 상한은 DATA에서 받는다.
        self.assertIn("var FILE_CTX = DATA.file_ctx || null;", text)
        self.assertIn("var evOn = !!FILE_CTX;", text)
        for k in ("DATA.evidence_max", "DATA.evidence_quote_max", "DATA.evidence_reason_max"):
            self.assertIn(k, text)
        # 드래그 칸: 본문과 같은 파일 슬라이드 텍스트 패널(슬라이드 제목·본문, 파일명, 문서 제목).
        self.assertIn('"data-ev-source":"chunk", "data-ev-chunk":c.chunk_id', text)
        m = re.search(r"function ctxCard\(c\)\{(.*?)\n  \}", text, re.S)
        self.assertIsNotNone(m)
        for s in ('"file_name"', '"doc_title"', '"chunk", s.chunk_id', "onEvSelect"):
            self.assertIn(s, m.group(1))
        self.assertNotIn("innerHTML", text)
        # 근거 지정 중 드래그는 동의어 제안으로 가지 않는다.
        m = re.search(r"function onSelect\(\)\{(.*?)\n  \}", text, re.S)
        self.assertIsNotNone(m)
        self.assertTrue(m.group(1).strip().startswith("if (evMode){ evCapture(); return; }"))
        m = re.search(r"function evCapture\(\)\{(.*?)\n  \}", text, re.S)
        self.assertIsNotNone(m)
        self.assertNotIn("pendingAlias", m.group(1))
        self.assertIn("a !== b", m.group(1))
        # 교정 항목에는 근거·이유가 있을 때만 키를 넣는다.
        m = re.search(r"function evAttach\(cid, k, item\)\{(.*?)\n  \}", text, re.S)
        self.assertIsNotNone(m)
        self.assertIn("if (items.length) item.evidence = items;", m.group(1))
        self.assertIn("if (r) item.reason", m.group(1))
        self.assertEqual(text.count("evAttach(c.chunk_id, "), 2)
        # 같은 localStorage 상태에 저장하고, evid가 없는 예전 상태도 읽는다.
        self.assertEqual(len(re.findall(r"setItem\(KEY, JSON\.stringify\(\{[^}]*evid:evid", text)), 2)
        self.assertIn('if (o.evid && typeof o.evid === "object" && !Array.isArray(o.evid)) evid = o.evid;', text)
        # 이유 입력 상한과 다른 고친 축에 복사.
        self.assertIn("maxlength:String(EV_REASON_MAX)", text)
        self.assertIn("이 근거를 다른 고친 축에도", text)
        self.assertIn("function evCopyToOthers(c, k)", text)

    def test_review_run_axes(self):
        text = read("review.html")
        # 교정 수집·같은 파일 적용·동의어 표준어 목록은 이 실행이 라벨링한(editable) 축만 쓴다.
        for fn in ("function chunkCorrections(c)", "function applyToSameFile(c)", "function allValueNames()"):
            m = re.search(re.escape(fn) + r"\{(.*?)\n  \}", text, re.S)
            self.assertIsNotNone(m, fn)
            self.assertIn("editAxes.forEach", m.group(1), fn)
            self.assertNotIn("\n    axes.forEach", m.group(1), fn)
        self.assertIn("function canEdit(ax){ return ax.editable !== false; }", text)
        self.assertIn("다음 실행부터 라벨링되는 새 축", text)
        self.assertIn("taxonomy에서 빠진 축", text)
        self.assertIn('disabled:editable ? null : "disabled"', text)
        self.assertIn("nActive > 12", text)

    def test_no_fixed_question_id(self):
        # 첫 공통 질문 ID는 DATA.primary_qid로 받는다(questions 시트에서 도출).
        for name in ("review.html", "results.html"):
            text = read(name)
            self.assertNotIn("Q-COM-001", text, name)
            self.assertIn("DATA.primary_qid", text, name)

    def test_results_pending_axes(self):
        text = read("results.html")
        self.assertIn("hot = !a.pending &&", text)
        self.assertIn("다음 실행부터", text)
        self.assertIn('stroke-dasharray="3 3"', text)
        self.assertIn("DATA.new_axes", text)
        self.assertIn("다시 라벨링하면 반영됩니다", text)
        self.assertNotIn("http", text.lower())

    def test_declares_utf8_and_korean(self):
        for name in FILES:
            text = read(name)
            self.assertIn('charset="utf-8"', text, name)
            self.assertIn('lang="ko"', text, name)


if __name__ == "__main__":
    unittest.main()
