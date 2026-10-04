"""합성 fixture 생성기(9절). 시드로 결정되는 번들을 메모리에서 만든다. 실데이터를 쓰지 않는다.

- taxonomy: 저장소 tests/fixtures/default_taxonomy_rows.jsonl에서 스냅샷을 만든다(xlsx를 읽지 않는다).
- 문장 틀마다 지지하는 라벨이 정해져 있다. 정답 레코드는 문장 틀에서 나온다(사외 골든셋).
- 원본 bytes는 pptx_writer가 io.BytesIO 안에서 만든다. 파일 ID는 그 bytes의 sha256이다.
- 파서 출력(ParsedUnit)은 생성기가 직접 조립한다. 반복 바닥글은 파서처럼 본문에서 뺀다.
"""
import copy
import hashlib
import json
import os
import random

from qabot import model
from qabot.tests import pptx_writer

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TAXONOMY_ROWS = os.path.join(REPO_ROOT, "tests", "fixtures", "default_taxonomy_rows.jsonl")
LABELER_RUN_ID = "20261004T000000-fx01"
FOOTER = "사내 테스트용 더미 자료"

# 축별 문장 틀. {v}에 값(또는 동의어)이 들어간다. 다른 축의 값이나 동의어가 섞이지 않게 쓴다.
AXIS_TEMPLATES = {
    "구조/레이어": ["{v} 배선층에서 저항 측정 진행", "{v} 구간 단면 분석 결과 공유"],
    "공정 모듈": ["{v} 공정 조건 재점검 진행", "{v} 단계 레시피 비교 결과 정리"],
    "제품·세대": ["{v} 제품 기준으로 평가 진행", "{v} 세대 적용 일정 검토"],
    "REMSPC": ["{v} 항목 변경 영향 확인", "{v} 요인으로 분류해 원인 분석"],
    "Patterning": ["{v} 방식으로 패턴 형성", "{v} 조건에서 패턴 균일도 비교"],
    "Material": ["{v} 막 적용 조건 비교", "{v} 막 두께 영향 검토"],
    "불량 모드": ["{v} 불량이 Center 영역에서 확인됨", "{v} 불량 발생 위치 분석"],
    "물리 현상": ["{v} 현상이 단면 분석에서 관찰됨", "{v} 현상 발생 조건 정리"],
    "결과": ["평가 결과 {v} 판정으로 정리됨", "비교 결과는 {v} 수준으로 판단"],
    "의사결정 상태": ["최종 결론은 {v} 상태로 기록", "검토 결과 {v} 상태로 정리"],
}
MULTI_TEMPLATE = "{v1} 및 {v2} 관련 조건 동시 점검"
ANSWER_TEMPLATES = {
    "O": ["HTOL 500h 이후 재발 여부는 미확인", "고온 조건 영향은 후속 평가 필요", "장기 신뢰성은 아직 미검증 상태"],
    "X": ["이전 이슈는 모두 해소됨", "장기 신뢰성까지 검증 완료", "잔여 위험 없어 추가 확인 불필요"],
}
FILLERS = ["회의 참석자 일정 공유", "다음 주 일정 재확인", "자료 배포 범위 안내", "샘플 반입 일정 조율",
           "측정 장비 예약 현황 공유", "보고서 양식 변경 안내", "담당 부서 연락처 정리", "실험 노트 작성 규칙 안내"]
PEOPLE = ["김민수", "이서연", "박지훈", "최유나", "정다은"]


# ---- taxonomy 스냅샷 --------------------------------------------------------

def taxonomy_snapshot(path=TAXONOMY_ROWS):
    rows = {"taxonomy": [], "questions": [], "synonyms": []}
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                r = json.loads(line)
                if r["sheet"] in rows and r["row"] > 1:
                    rows[r["sheet"]].append(r["cells"])
    axes, order = {}, []
    for cells in rows["taxonomy"]:
        cells = list(cells) + [""] * (11 - len(cells))
        name, value = cells[0], cells[1]
        if not value:
            axes[name] = {"name": name, "kind": cells[6] or "분류", "multi": cells[3] == "Y",
                          "hierarchical": cells[4] == "Y", "definition": cells[7], "values": []}
            order.append(name)
        elif (cells[10] or "Y") != "N":
            axes[name]["values"].append({"name": value, "parent": cells[2] or None, "definition": cells[7]})
    ax_list = []
    for n in order:
        a = axes[n]
        a["active"] = bool(a["values"])
        ax_list.append(a)
    return {
        "version": model.hash_obj(rows["taxonomy"]),
        "questions_version": model.hash_obj(rows["questions"]),
        "synonyms_version": model.hash_obj(rows["synonyms"]),
        "reserved": {"na": model.NA, "unknown": model.UNKNOWN},
        "axes": ax_list,
        "questions": [{"qid": c[0], "text": c[1], "target": c[2] if len(c) > 2 else "공통"} for c in rows["questions"]],
        "synonyms": [{"alias": c[0], "canonical": c[1]} for c in rows["synonyms"]],
    }


def synonym_table(snapshot):
    from labelbot.synonyms import SynonymTable

    return SynonymTable([(s["alias"], s["canonical"]) for s in snapshot["synonyms"]])


# ---- 생성 -------------------------------------------------------------------

class FixtureLoader(object):
    def __init__(self, blobs, images):
        self.blobs = blobs
        self.images = images

    def source_bytes(self, source):
        try:
            return self.blobs[source["file_id"]]
        except KeyError:
            raise model.LoaderError("B64_MISSING")

    def image_bytes(self, image):
        try:
            return self.images[image["rel_file"]]
        except KeyError:
            raise model.LoaderError("B64_MISSING")


class Fixture(object):
    def __init__(self, bundle, blobs, images, specs, truth):
        self.bundle = bundle
        self.blobs = blobs
        self.images = images
        self.specs = specs
        self.truth = truth

    def bundle_hash(self):
        b = self.bundle
        return model.hash_obj({"sources": b.sources, "units": b.units, "records": b.records, "taxonomy": b.taxonomy,
                               "blobs": {k: hashlib.sha256(v).hexdigest() for k, v in self.blobs.items()}})


def _lot_id(rng):
    letters = "ABCDEFGHJKLMNPRSTUVWXYZ"
    if rng.random() < 0.6:
        n = rng.choice((3, 4))
        base = "R" + rng.choice("DQX") + "".join(rng.choice(letters) for _ in range(n))
    else:
        base = "Q" + "".join(rng.choice(letters) for _ in range(4)) + "0" + "%02d" % rng.randrange(100)
    return base + (".%02d" % rng.randrange(1, 20) if rng.random() < 0.5 else "")


def _ev(quote):
    return {"quote": quote, "unit_id": None, "start": None, "end": None}


def _pick_values(rng, ax, n):
    vals = ax["values"]
    if ax["hierarchical"]:
        # 하위만 저장하는 규칙: 상위값과 그 하위값을 함께 고르지 않는다
        out = []
        for v in rng.sample(vals, len(vals)):
            fam = {v["name"], v.get("parent")}
            if any(o["name"] in fam or o.get("parent") == v["name"] or v.get("parent") == o["name"] for o in out):
                continue
            out.append(v)
            if len(out) == n:
                break
        return [v["name"] for v in out]
    return [v["name"] for v in rng.sample(vals, n)]


def _surface(rng, value, syn_by_canon):
    aliases = syn_by_canon.get(value) or []
    if aliases and rng.random() < 0.5:
        return rng.choice(aliases), True
    return value, False


def _content_slide(rng, tax, syn_by_canon, synt):
    lines, axes, used_syn = [], {}, []
    unknown_budget = 1
    for ax in tax["axes"]:
        roll = rng.random()
        if roll < 0.25 or (roll < 0.33 and unknown_budget == 0):
            axes[ax["name"]] = {"values": [model.NA], "status": "na", "evidence": _ev(""), "confidence": round(rng.uniform(0.7, 0.95), 2)}
            continue
        if roll < 0.33:
            unknown_budget -= 1
            axes[ax["name"]] = {"values": [model.UNKNOWN], "status": "unknown", "evidence": _ev(""),
                                "confidence": round(rng.uniform(0.5, 0.8), 2)}
            continue
        n = 2 if ax["multi"] and len(ax["values"]) > 2 and rng.random() < 0.2 else 1
        vals = _pick_values(rng, ax, n)
        if len(vals) == 2:
            s1, a1 = _surface(rng, vals[0], syn_by_canon)
            s2, a2 = _surface(rng, vals[1], syn_by_canon)
            sentence = MULTI_TEMPLATE.format(v1=s1, v2=s2)
            aliased = a1 or a2
        else:
            s1, aliased = _surface(rng, vals[0], syn_by_canon)
            sentence = rng.choice(AXIS_TEMPLATES[ax["name"]]).format(v=s1)
        lines.append(sentence)
        quote = sentence
        if aliased:
            used_syn.append(sentence)
            if rng.random() < 0.5:
                quote = synt.apply(sentence)[0]  # labelbot 1차 분류는 동의어 치환본에서 인용한다
        axes[ax["name"]] = {"values": vals, "status": "value", "evidence": _ev(quote),
                            "confidence": round(rng.uniform(0.7, 0.95), 2)}
    answers = {}
    for q in tax["questions"]:
        roll = rng.random()
        if roll < 0.4:
            s = rng.choice(ANSWER_TEMPLATES["O"])
            lines.append(s)
            answers[q["qid"]] = {"answer": "O", "evidence": _ev(s), "confidence": round(rng.uniform(0.7, 0.95), 2)}
        elif roll < 0.7:
            s = rng.choice(ANSWER_TEMPLATES["X"])
            lines.append(s)
            answers[q["qid"]] = {"answer": "X", "evidence": _ev(s), "confidence": round(rng.uniform(0.7, 0.95), 2)}
        else:
            answers[q["qid"]] = {"answer": "N/A", "evidence": _ev(""), "confidence": round(rng.uniform(0.6, 0.9), 2)}
    extracted = []
    if rng.random() < 0.35:
        y, m, d = 2026, rng.randrange(1, 10), rng.randrange(1, 28)
        s = "%d.%d.%d 회의에서 일정 확정" % (y, m, d)
        lines.append(s)
        extracted.append({"item": "date", "value": "%d-%02d-%02d" % (y, m, d), "evidence": {"quote": s}, "flag": ""})
    if rng.random() < 0.3:
        p = rng.choice(PEOPLE)
        s = "담당 %s 책임이 후속 일정 관리" % p
        lines.append(s)
        extracted.append({"item": "person", "value": p, "evidence": {"quote": s}, "flag": ""})
    if rng.random() < 0.25:
        lot = _lot_id(rng)
        s = "lot %s 샘플 분석 진행" % lot
        lines.append(s)
        extracted.append({"item": "lot_id", "value": lot, "evidence": {"quote": s}, "flag": ""})
    lines += rng.sample(FILLERS, rng.randrange(1, 3))
    # 같은 슬라이드에 같은 문장이 두 번 나오지 않게 한다
    seen, uniq = set(), []
    for l in lines:
        if l not in seen:
            seen.add(l)
            uniq.append(l)
    rng.shuffle(uniq)
    return uniq, axes, answers, extracted


def generate(seed=7, n_files=12, slides_range=(6, 11), labeler_run_id=LABELER_RUN_ID):
    rng = random.Random(seed)
    tax = taxonomy_snapshot()
    synt = synonym_table(tax)
    syn_by_canon = {}
    for s in tax["synonyms"]:
        syn_by_canon.setdefault(s["canonical"], []).append(s["alias"])
    sources, units, records, blobs, images, specs = {}, {}, [], {}, {}, {}
    sheet_hashes = {"taxonomy": tax["version"], "questions": tax["questions_version"],
                    "synonyms": tax["synonyms_version"]}
    for fno in range(n_files):
        n_slides = rng.randrange(slides_range[0], slides_range[1] + 1)
        slide_specs, slide_meta = [], []
        hidden_at = rng.randrange(2, n_slides) if rng.random() < 0.3 else None
        for sno in range(1, n_slides + 1):
            title = "주간 보고 %d-%d" % (fno + 1, sno)
            if sno == 1:
                spec = {"title": "과제 보고 %d" % (fno + 1), "lines": ["작성 부서 공정기술팀"], "footer": FOOTER}
                slide_specs.append(spec)
                slide_meta.append(("표지", None))
                continue
            lines, axes, answers, extracted = _content_slide(rng, tax, syn_by_canon, synt)
            spec = {"title": title, "lines": lines, "footer": FOOTER, "hidden": sno == hidden_at}
            if rng.random() < 0.25:
                spec["table"] = [["항목", "측정값"], ["Rs", "%.1f" % rng.uniform(10, 20)], ["Rc", "%.1f" % rng.uniform(1, 5)]]
            if rng.random() < 0.25:
                spec["images"] = [pptx_writer.fake_png("%d-%d-%d" % (seed, fno, sno))]
            if rng.random() < 0.2:
                spec["notes"] = "발표자 메모 %d" % sno
            slide_specs.append(spec)
            slide_meta.append(("내용", (axes, answers, extracted)))
        data = pptx_writer.build_pptx(slide_specs)
        fid = hashlib.sha256(data).hexdigest()
        blobs[fid] = data
        specs[fid] = slide_specs
        sources[fid] = {"file_id": fid, "ext": ".pptx", "status": "ok", "reason_code": None,
                        "b64_ref": "b64/%s.b64" % fid}
        for sno, (spec, (ctype, lab)) in enumerate(zip(slide_specs, slide_meta), 1):
            part = "ppt/slides/slide%d.xml" % sno
            uid = "%s:%s" % (fid[:16], part)
            text_lines = [spec["title"]] + list(spec.get("lines") or [])
            if spec.get("table"):
                text_lines += [" | ".join(r) for r in spec["table"]]
            if spec.get("notes"):
                text_lines += ["[노트]", spec["notes"]]
            text = model.nfc("\n".join(text_lines))
            canon = synt.apply(text)[0]
            imgs = []
            for img in spec.get("images") or []:
                iid = hashlib.sha256(img).hexdigest()
                rel = "images/%s.b64" % iid
                images[rel] = img
                imgs.append({"image_id": iid, "ext": "png", "size": len(img), "rel_file": rel})
            units[uid] = {
                "unit_id": uid, "file_id": fid, "seq": sno, "part_name": part, "title": spec["title"],
                "text": text, "text_canonical": canon if canon != model.nfkc(text) else None,
                "text_hash": model.sha256_text(text), "tables": [spec["table"]] if spec.get("table") else [],
                "notes": spec.get("notes") or "", "charts": [], "images": imgs, "warnings": [], "dup_group": None,
            }
            if ctype == "표지":
                axes = {ax["name"]: {"values": [model.NA], "status": "na", "evidence": _ev(""), "confidence": 0.9}
                        for ax in tax["axes"]}
                answers, extracted = {}, []
            else:
                axes, answers, extracted = lab
            records.append({
                "record_id": uid, "file_id": fid, "labeler_run_id": labeler_run_id, "chunk_type": ctype,
                "axes": axes, "answers": answers, "extracted": extracted, "failures": [],
                "labeler": {"agent": "labelbot", "prompt_versions": {"classify": "fx-classify", "label": "fx-label"},
                            "model": "mock", "sheet_hashes": dict(sheet_hashes), "created_at": "2026-10-04T00:00:00Z"},
                "human_reviewed": False, "duplicate_fields": [],
            })
    bundle = model.Bundle(labeler_run_id, sources, units, records, tax, FixtureLoader(blobs, images),
                          meta={"adapter": "fixture", "file_names": {fid: "합성 파일 %d" % (i + 1)
                                                                     for i, fid in enumerate(sorted(sources))}})
    return Fixture(bundle, blobs, images, specs, copy.deepcopy(records))
