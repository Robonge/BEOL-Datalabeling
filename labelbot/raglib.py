"""RAG 답변(labelbot.ragsrv)의 순수 함수와 상수. 네트워크·환경변수를 쓰지 않는다.

옛 Edge Function의 lib.ts를 1:1로 옮겼다. 상수·문구·시스템 프롬프트는 글자 그대로다.
JS와 다른 점: 정규식의 \\p{Extended_Pictographic}은 이모지 범위 문자 클래스로 근사하고, 글자 수 상한은
UTF-16 단위가 아니라 코드 포인트(len) 기준이다. \\d는 JS처럼 ASCII 숫자([0-9])만 본다.
입력 오류는 RagInputError(code)로 낸다.
"""
import math
import random
import re

MAX_K = 8
DEFAULT_K = 5
MAX_MESSAGES = 12
MAX_QUESTION_CHARS = 1000
MAX_MESSAGE_CHARS = 4000
MAX_BODY_BYTES = 204800
MAX_FILTER_AXES = 16
MAX_FILTER_VALUES = 30
MAX_FILTER_VALUE_CHARS = 100
MAX_REWRITE_CHARS = 400
MAX_CITE_RANGE = 8
NO_ANSWER_PREFIX = "자료에 없음"
# 근거가 질문에 답하지 못할 때 "자료에 없음 — …" 뒤에 붙이는 안내(검색된 슬라이드는 그대로 보여 준다).
NO_ANSWER_GUIDE = "대신 그나마 가장 비슷한 슬라이드를 아래에 보여 드리니, 찾으시는 내용이 있는지 참고해 보세요."

# 답 끝의 확인 질문("원하신 답이 맞나요?")은 요청의 이 비율에서만 하게 한다(서버가 매번 무작위로 정한다).
CONFIRM_QUESTION_RATE = 0.3

MAX_CONTEXT_ASSISTANT_CHARS = 2000
MAX_EVIDENCE_CONTENT_CHARS = 1500

# 검색된 슬라이드와 같은 파일의 다른 chunk도 근거로 함께 넘긴다(파일당·전체 상한, 본문은 더 짧게).
MAX_SIBLINGS_PER_FILE = 6
MAX_SIBLINGS_TOTAL = 15
MAX_SIBLING_CONTENT_CHARS = 1000

NO_EVIDENCE_ANSWER = "자료에 없음 — 질문과 맞는 슬라이드를 찾지 못했습니다."
NO_EVIDENCE_FILTERED_ANSWER = "자료에 없음 — 선택한 필터에 맞는 슬라이드가 없습니다. 필터를 줄여 보세요."

RESERVED_KEYS = frozenset(["__proto__", "constructor", "prototype"])

REWRITE_SYSTEM_PROMPT = (
    "앞 대화를 참고해 마지막 질문을 혼자서도 뜻이 통하는 한국어 검색 질문 한 문장으로 다시 써라. 설명·따옴표 없이 문장만."
)


class RagInputError(ValueError):
    """요청 본문 검사 실패. code는 응답의 error 값(BAD_INPUT)."""

    def __init__(self, code="BAD_INPUT"):
        super().__init__(code)
        self.code = code


def _num(v):
    """JS Number(v) || 0 근사(정렬용)."""
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (int, float)):
        return 0 if isinstance(v, float) and math.isnan(v) else v
    if isinstance(v, str):
        try:
            f = float(v.strip() or "0")
        except ValueError:
            return 0
        return 0 if math.isnan(f) else f
    return 0


def _js_str(v):
    return "" if v is None else str(v)


def ask_confirm(rand=random.random):
    """이번 답 끝에 확인 질문을 붙일지(Math.random() < CONFIRM_QUESTION_RATE). 테스트는 rand를 바꿔 끼운다."""
    return rand() < CONFIRM_QUESTION_RATE


# 입력 검사. 성공이면 {messages, filters, k, question}, 실패면 RagInputError("BAD_INPUT").
def validate_input(body):
    if not isinstance(body, dict):
        raise RagInputError()

    raw = body.get("messages")
    if not isinstance(raw, list) or len(raw) == 0:
        raise RagInputError()
    for m in raw:
        if not isinstance(m, dict):
            raise RagInputError()
        if m.get("role") not in ("user", "assistant"):
            raise RagInputError()
        if not isinstance(m.get("content"), str):
            raise RagInputError()
    last = raw[-1]
    if last["role"] != "user":
        raise RagInputError()
    question = last["content"].strip()
    if not question or len(question) > MAX_QUESTION_CHARS:
        raise RagInputError()

    kept = raw[-MAX_MESSAGES:]
    messages = [
        {"role": m["role"], "content": question if i == len(kept) - 1 else m["content"][:MAX_MESSAGE_CHARS]}
        for i, m in enumerate(kept)
    ]

    k = DEFAULT_K
    if body.get("k") is not None:
        bk = body["k"]
        if isinstance(bk, bool) or not isinstance(bk, (int, float)) or not math.isfinite(bk):
            raise RagInputError()
        k = min(MAX_K, max(1, math.floor(bk)))

    filters = {}
    raw_filters = body.get("filters")
    if raw_filters is not None:
        if not isinstance(raw_filters, dict):
            raise RagInputError()
        if len(raw_filters) > MAX_FILTER_AXES:
            raise RagInputError()
        for axis, values in raw_filters.items():
            if axis in RESERVED_KEYS:
                raise RagInputError()
            if not isinstance(values, list) or len(values) > MAX_FILTER_VALUES:
                raise RagInputError()
            if not all(isinstance(v, str) and len(v) <= MAX_FILTER_VALUE_CHARS for v in values):
                raise RagInputError()
            filters[axis] = list(values)

    return {"messages": messages, "filters": filters, "k": k, "question": question}


# 앞 답(assistant)이 하나라도 있으면 후속 질문으로 보고 고쳐 쓴다.
def needs_rewrite(messages):
    return any(m["role"] == "assistant" for m in messages)


# 근거가 없을 때의 답. 값이 있는 필터 축이 하나라도 있으면 필터를 줄이라고 안내한다.
def no_evidence_answer(filters):
    return NO_EVIDENCE_FILTERED_ANSWER if any(len(v) > 0 for v in filters.values()) else NO_EVIDENCE_ANSWER


# content의 첫 비어 있지 않은 줄에서 앞 "# "를 뗀 슬라이드 제목.
def title_of(content):
    if not isinstance(content, str):
        return ""
    first = next((line for line in re.split(r"\r?\n", content) if line.strip() != ""), "")
    return re.sub(r"^\s*#+\s*", "", first, count=1).strip()


_CITATIONS = re.compile(r"\[[0-9]+(?:\s*,\s*[0-9]+)*\]")


# 이전 답의 근거 번호 [1]·[1, 3]을 지운다(새 근거 번호와 섞이지 않게).
def strip_citations(text):
    return _CITATIONS.sub("", text)


def _evidence_item(r, n, image_urls):
    labels = r.get("labels") if isinstance(r.get("labels"), dict) else {}
    path = r.get("slide_image_path") if isinstance(r.get("slide_image_path"), str) else None
    return {
        "n": n,
        "chunk_id": r.get("chunk_id"),
        "title": title_of(r.get("content")),
        "content": r.get("content") if isinstance(r.get("content"), str) else "",
        "labels": labels,
        "doc_meta": labels.get("doc_meta"),
        "file_id16": _js_str(r.get("file_id"))[:16],
        "image_url": image_urls[path] if path and image_urls.get(path) else None,
        "image_path": path,
        "kind": "hit",
        "sibling_of": None,
        "scores": {
            "rrf": r.get("rrf_score"),
            "vector_similarity": r.get("vector_similarity"),
            "text_score": r.get("text_score"),
            "vector_pos": r.get("vector_pos"),
            "text_pos": r.get("text_pos"),
        },
    }


# 검색 행 → 응답 근거(kind "hit"). image_urls: slide_image_path → URL(없으면 None).
def build_evidence(rows, image_urls):
    return [_evidence_item(r, i + 1, image_urls) for i, r in enumerate(rows)]


# 같은 파일의 다른 chunk를 hit 뒤에 번호를 이어 붙인다(kind "sibling", sibling_of = 그 파일의 첫 hit 번호).
# 이미 hit인 chunk는 빼고, 파일 안에서는 seq 순, 파일 순서는 hit 순이다. 파일당·전체 상한을 넘으면 버린다.
def attach_siblings(evidence, sibling_rows, image_urls):
    hit_ids = {e["chunk_id"] for e in evidence}
    first_hit = {}
    file_order = []
    for e in evidence:
        if e["file_id16"] not in first_hit:
            first_hit[e["file_id16"]] = e["n"]
            file_order.append(e["file_id16"])
    by_file = {}
    for r in sibling_rows if isinstance(sibling_rows, list) else []:
        if not isinstance(r, dict) or r.get("chunk_id") in hit_ids:
            continue
        f = _js_str(r.get("file_id"))[:16]
        if f not in first_hit:
            continue
        lst = by_file.setdefault(f, [])
        if not any(x.get("chunk_id") == r.get("chunk_id") for x in lst):
            lst.append(r)
    out = list(evidence)
    added = 0
    for f in file_order:
        lst = sorted(by_file.get(f, []), key=lambda x: _num(x.get("seq")))
        for r in lst[:MAX_SIBLINGS_PER_FILE]:
            if added >= MAX_SIBLINGS_TOTAL:
                return out
            item = _evidence_item(r, len(out) + 1, image_urls)
            item["kind"] = "sibling"
            item["sibling_of"] = first_hit.get(f)
            item["scores"] = {"rrf": None, "vector_similarity": None, "text_score": None,
                              "vector_pos": None, "text_pos": None}
            out.append(item)
            added += 1
    return out


def _axes_summary(labels):
    axes = labels.get("axes") if isinstance(labels, dict) and isinstance(labels.get("axes"), dict) else {}
    parts = []
    for axis, values in axes.items():
        if isinstance(values, list) and len(values) > 0:
            parts.append("%s=%s" % (axis, ", ".join(_js_str(v) for v in values)))
    return " / ".join(parts) or "(없음)"


def _doc_meta_summary(meta):
    if not isinstance(meta, dict):
        return "(없음)"
    lots = meta.get("lots") if isinstance(meta.get("lots"), list) else []
    lot_text = "; ".join(
        ("%s(WF %s)" % (_js_str(l["lot"]), ",".join(_js_str(w) for w in l["wf"]))
         if isinstance(l.get("wf"), list) and len(l["wf"]) > 0 else _js_str(l["lot"]))
        for l in lots if isinstance(l, dict) and l.get("lot")
    )
    return " | ".join([
        "Lot/WF: %s" % (lot_text or "(없음)"),
        "작성자: %s" % (meta.get("author") or "(없음)"),
        "날짜: %s" % (meta.get("date") or "(없음)"),
    ])


# ask_confirm: 이번 답 끝에 확인 질문을 붙일지(CONFIRM_QUESTION_RATE로 서버가 정한다).
def answer_system_prompt(n, ask_confirm):
    return "\n".join([
        "너는 삼성전자 반도체연구소의 BEOL Integration 공정 평가 슬라이드를 찾아 분석해 주는 '전문적이고 친절한 AI 어시스턴트'다.",
        f"사용자의 질문에 대해 아래 제공된 [근거] [1]…[{n}]을 바탕으로 한국어로 정중하게(~습니다/합니다) 답변하라.",
        "",
        "[데이터 처리 및 추론 규칙]",
        "1. 검색된 슬라이드와 '같은 파일'로 표시된 슬라이드는 같은 평가의 앞뒤 내용이므로, 반드시 함께 읽고 문맥을 종합하여 추론하라.",
        "2. 근거에 없는 내용은 절대 지어내지 마며, 외부 지식이나 개인적 추측을 섞지 마라.",
        "\n".join([
            "3. 데이터가 질문에 답하기에 부족하거나 없는 경우, 억지로 답변을 만들지 말고 아래 안내 문장을 포함하여 정중하게 안내하라. 근거에 질문과 관련된 내용이 전혀 없을 때만 이 문장을 쓰고, 일부라도 관련 있으면 있는 내용으로 답하라.",
            '   "찾으시는 내용과 완벽하게 일치하는 기존 평가결과를 확인하지 못했습니다. EDM 데이터 정제와 서비스 품질 향상을 지속적으로 진행 중입니다."',
            f"   (이후 이어지는 안내 문장: {NO_ANSWER_GUIDE})",
        ]),
        "",
        "[답변 구조 및 포맷팅 규칙]",
        "답변 내용을 준비하는데 있어, 다음의 4단계 구조를 지켜서 조사하라. 단 답변을 작성할 때 개조식으로 1,2,3,4단계를 명시하지 않는다. 각 내용들을 순서대로 서술하면서 자연스러운 줄글 형태로 표현한다. 이모지는 절대 사용하지 마라.",
        "반도체 관련 terminology는 영어 표현을 적극 활용한다. 식각(etching), 증착(deposition), CMP, BEOL, FEOL, TSV, Cu, Al, W, SiO2, SiN 등은 그대로 쓴다.",
        "텍스트 설명 부분에는 가독성을 위해 마크다운(굵은 글씨, 글머리 기호)을 적절히 사용하라.",
        "답변에 이모지를 섞지 마라",
        "",
        "- 1단계 [핵심 분석]: 질문에 포함된 keyword에 대한 기술적 설명과 질문에 대한 직접적인 결론을 1~2문장으로 간결하게 작성하라.",
        "- 2단계 [근거 요약]: 결론을 뒷받침하는 주요 슬라이드 내용을 글머리 기호를 사용하여 핵심만 요약하라.",
        "- 3단계 [데이터 표]: 결과 데이터(조건, 웨이퍼, 수치, 판정, 날짜, 담당자 등)를 표로 정리하라. 평가 날짜와 담당자 정보가 있는 경우 표에 포함하라. Lot/WF 정보가 있는 경우에는 표에 포함하되, 별도의 열로 구분하여 작성하라. ",
        "- 4단계 [인과 관계 심층 분석]: 주요 슬라이드의 내용 및 같은 파일의 슬라이드 내용을 적극 참고하고, BEOL Integration 공정 전문가로서의 전문성을 발휘해 공정 조건(Condition)의 변화가 결과(Result/Issue)에 어떤 영향을 미쳤는지 인과관계를 구체적으로 설명하라.",
        "",
        "[표 출력 및 인용 번호 규칙]",
        "1. 표를 출력할 때는 일반 마크다운 대신 반드시 아래의 HTML 구조와 클래스를 정확히 사용하여 출력하라.",
        '   <table class="border-collapse border"><thead><tr><th class="border px-3 py-2">...</th></tr></thead><tbody><tr><td class="border px-3 py-2">...</td></tr></tbody></table>',
        "2. 표 안에는 style, onclick 등 지정되지 않은 다른 속성이나 태그를 임의로 추가하지 마라.",
        "3. 각 문장의 끝, 혹은 표의 각 행 마지막 <td> 내용 끝에 그 내용을 뒷받침하는 실제 근거 번호를 [1]이나 [1][3] 형태로 달아라.",
        "4. 같은 파일 슬라이드에서 온 내용은 해당 슬라이드의 번호를 붙여라.",
        "",
        "[확인 질문 규칙]",
        "답변의 가장 마지막 줄에는 작성자가 원하는 답변이 맞는지 친절하게 묻는 짧은 확인 질문을 추가하라. (이 문장에는 근거 번호를 붙이지 마라.)"
        if ask_confirm
        else "이번 답변에는 마지막 확인 질문을 추가하지 마라.",
    ])


# \p{Extended_Pictographic} 근사: 이모지가 놓이는 주요 범위.
_EMOJI = ("[©®‼⁉™ℹ↔-↙↩↪⌚⌛⌨⏏"
          "⏩-⏳⏸-⏺Ⓜ▪▫▶◀◻-◾☀-➿"
          "⤴⤵⬅-⬇⬛⬜⭐⭕〰〽㊗㊙\U0001f000-\U0001faff]")
# 답 맨 끝 질문 문장("…맞나요? [2][4]")에 붙은 번호를 지운다. 확인 질문은 근거가 아니다.
_TRAILING_QUESTION_CITES = re.compile(
    r"(\?[ \t]*(?:" + _EMOJI + "️?" + r"[ \t]*)*)(?:[ \t]*\[[0-9]+\])+[ \t]*\Z")


def strip_trailing_question_citations(text):
    return _TRAILING_QUESTION_CITES.sub(r"\1", text, count=1).rstrip()


# 답변 생성용 chat messages. messages의 마지막은 지금 질문이다.
def build_answer_messages(messages, evidence, question, search_query=None, ask_confirm=False):
    prior = messages[:-1][-(MAX_MESSAGES - 1):]
    history = "\n\n".join(
        "도우미: " + strip_citations(m["content"])[:MAX_CONTEXT_ASSISTANT_CHARS]
        if m["role"] == "assistant" else "사용자: " + m["content"]
        for m in prior
    )

    blocks = []
    for e in evidence:
        sibling = e.get("kind") == "sibling"
        tag = " (같은 파일 — [%s]과 같은 파일의 다른 슬라이드)" % _js_str(e.get("sibling_of")) if sibling else ""
        blocks.append("\n".join([
            "[%s]%s 제목: %s" % (e.get("n"), tag, e.get("title") or "(제목 없음)"),
            "축 라벨: " + _axes_summary(e.get("labels")),
            _doc_meta_summary(e.get("doc_meta")),
            "본문:",
            _js_str(e.get("content"))[:MAX_SIBLING_CONTENT_CHARS if sibling else MAX_EVIDENCE_CONTENT_CHARS],
        ]))

    parts = []
    if history:
        parts.append("[이전 대화]\n" + history)
    parts.append("[근거]\n" + "\n\n".join(blocks))
    q = "[질문]\n" + question
    if search_query and search_query != question:
        q += "\n(검색에 쓴 질문: %s)" % search_query
    parts.append(q)

    return [
        {"role": "system", "content": answer_system_prompt(len(evidence), ask_confirm)},
        {"role": "user", "content": "\n\n".join(parts)},
    ]


_CITE_ITEM = r"[0-9]+(?:\s*[-–]\s*[0-9]+)?"
_CITE_BRACKET = r"\[\s*" + _CITE_ITEM + r"(?:\s*,\s*" + _CITE_ITEM + r")*\s*\]"
# 이어 붙은 인용 묶음 "[1][2-3]". "TaN[1]"·"10nm[2]"처럼 영문·숫자 바로 뒤도 인용으로 본다.
# "]" 뒤에서는 새 묶음을 시작하지 않는다(묶음 중간에서 다시 잡지 않게).
_CITE_RUN = re.compile(r"([ \t]*)(?<!\])((?:" + _CITE_BRACKET + r")+)")
_CITE_INNER = re.compile(r"\[([^\]]*)\]")
_CITE_RANGE = re.compile(r"([0-9]+)\s*[-–]\s*([0-9]+)")


# "3" → [3], "1-3" → [1,2,3]. 거꾸로 된 범위나 MAX_CITE_RANGE보다 긴 범위는 버린다.
def _cite_numbers(item):
    rng = _CITE_RANGE.fullmatch(item)
    if not rng:
        try:
            return [int(item)]
        except ValueError:
            return []
    a = int(rng.group(1))
    b = int(rng.group(2))
    if b < a or b - a + 1 > MAX_CITE_RANGE:
        return []
    return list(range(a, b + 1))


# 범위 밖 [m] 제거. "[1, 3]"·"[1-3]"·"[ 2 ]" 꼴은 "[1][3]"처럼 펼친다. cited는 남은 번호(오름차순, 중복 없음).
def fix_citations(answer, n):
    cited = set()

    def repl(mo):
        lead, run = mo.group(1), mo.group(2)
        valid = []
        for inner in _CITE_INNER.findall(run):
            for item in inner.split(","):
                for m in _cite_numbers(item.strip()):
                    if 1 <= m <= n and m not in valid:
                        valid.append(m)
        if not valid:
            return ""
        cited.update(valid)
        return lead + "".join("[%d]" % m for m in valid)

    text = _CITE_RUN.sub(repl, answer)
    return {"text": text, "cited": sorted(cited)}


_FIRST_SENTENCE = re.compile(
    r"[^\n\r  ]*?[다요](?:[ \t]*\[[0-9]+\])*\.(?:[ \t]*\[[0-9]+\])*(?=\s|\Z)")
_FIRST_CITES = re.compile(r"[ \t]*\[[0-9]+\]")
_MULTI_BLANK = re.compile(r"[ \t]{2,}")


# 답 후처리. 번호를 고친 뒤, "자료에 없음 — …"으로 시작하는 답은
# [첫 문장(번호 없음)] + NO_ANSWER_GUIDE + [나머지 참고 설명(번호 유지)] 꼴로 맞춘다.
# 안내 문장은 모델이 빠뜨려도 붙고, 두 번 쓰면 하나만 남는다. cited는 나머지 설명의 번호만 센다.
def finalize_answer(answer, n):
    fixed = fix_citations(strip_trailing_question_citations(answer.strip()), n)
    text = fixed["text"].strip()
    if not text.startswith(NO_ANSWER_PREFIX):
        return {"text": text, "cited": fixed["cited"]}

    body = _MULTI_BLANK.sub(" ", " ".join(text.split(NO_ANSWER_GUIDE))).strip()
    # "SF1.0"처럼 숫자 속 마침표에서 끊기지 않게 "다."·"요."로 끝나는 첫 문장을 찾는다(번호가 붙어 있어도 된다).
    m = _FIRST_SENTENCE.match(body)
    first_raw = m.group(0) if m else body
    rest = body[len(first_raw):].strip()
    first = _FIRST_CITES.sub("", first_raw).strip()
    rest_fixed = fix_citations(rest, n)
    out = " ".join(s for s in [first, NO_ANSWER_GUIDE, rest_fixed["text"].strip()] if s)
    return {"text": out, "cited": rest_fixed["cited"]}
