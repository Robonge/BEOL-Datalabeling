// beol-rag-ask 순수 함수와 상수. 네트워크·환경변수를 쓰지 않는다(index.ts가 쓴다).

export const MAX_K = 8;
export const DEFAULT_K = 5;
export const MAX_MESSAGES = 12;
export const MAX_QUESTION_CHARS = 1000;
export const MAX_MESSAGE_CHARS = 4000;
export const MAX_BODY_BYTES = 204800;
export const MAX_FILTER_AXES = 16;
export const MAX_FILTER_VALUES = 30;
export const MAX_FILTER_VALUE_CHARS = 100;
export const MAX_REWRITE_CHARS = 400;
export const MAX_CITE_RANGE = 8;
export const NO_ANSWER_PREFIX = "자료에 없음";
// 근거가 질문에 답하지 못할 때 "자료에 없음 — …" 뒤에 붙이는 안내(검색된 슬라이드는 그대로 보여 준다).
export const NO_ANSWER_GUIDE = "대신 그나마 가장 비슷한 슬라이드를 아래에 보여 드리니, 찾으시는 내용이 있는지 참고해 보세요.";
export const EMBED_MODEL = "text-embedding-3-small";
export const EMBED_DIM = 1536;

// 답 끝의 확인 질문("원하신 답이 맞나요?")은 요청의 이 비율에서만 하게 한다(서버가 매번 무작위로 정한다).
export const CONFIRM_QUESTION_RATE = 0.3;

export const MAX_CONTEXT_ASSISTANT_CHARS = 2000;
export const MAX_EVIDENCE_CONTENT_CHARS = 1500;

// 검색된 슬라이드와 같은 파일의 다른 chunk도 근거로 함께 넘긴다(파일당·전체 상한, 본문은 더 짧게).
export const MAX_SIBLINGS_PER_FILE = 6;
export const MAX_SIBLINGS_TOTAL = 15;
export const MAX_SIBLING_CONTENT_CHARS = 1000;

export const NO_EVIDENCE_ANSWER = "자료에 없음 — 질문과 맞는 슬라이드를 찾지 못했습니다.";
export const NO_EVIDENCE_FILTERED_ANSWER = "자료에 없음 — 선택한 필터에 맞는 슬라이드가 없습니다. 필터를 줄여 보세요.";

const RESERVED_KEYS = new Set(["__proto__", "constructor", "prototype"]);

export const REWRITE_SYSTEM_PROMPT =
  "앞 대화를 참고해 마지막 질문을 혼자서도 뜻이 통하는 한국어 검색 질문 한 문장으로 다시 써라. 설명·따옴표 없이 문장만.";

type Msg = { role: "user" | "assistant"; content: string };

function isPlainObject(v: unknown): v is Record<string, any> {
  return v !== null && typeof v === "object" && !Array.isArray(v);
}

export function corsHeaders(): Record<string, string> {
  return {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "authorization, apikey, content-type, x-client-info",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
  };
}

// 입력 검사. 성공이면 {ok:true, messages, filters, k, question}, 실패면 {ok:false, code:"BAD_INPUT"}.
export function validateInput(body: unknown) {
  const bad = { ok: false as const, code: "BAD_INPUT" };
  if (!isPlainObject(body)) return bad;

  const raw = body.messages;
  if (!Array.isArray(raw) || raw.length === 0) return bad;
  for (const m of raw) {
    if (!isPlainObject(m)) return bad;
    if (m.role !== "user" && m.role !== "assistant") return bad;
    if (typeof m.content !== "string") return bad;
  }
  const last = raw[raw.length - 1];
  if (last.role !== "user") return bad;
  const question = last.content.trim();
  if (!question || question.length > MAX_QUESTION_CHARS) return bad;

  const kept = raw.slice(-MAX_MESSAGES);
  const messages: Msg[] = kept.map((m: any, i: number) => ({
    role: m.role,
    content: i === kept.length - 1 ? question : m.content.slice(0, MAX_MESSAGE_CHARS),
  }));

  let k = DEFAULT_K;
  if (body.k !== undefined && body.k !== null) {
    if (typeof body.k !== "number" || !Number.isFinite(body.k)) return bad;
    k = Math.min(MAX_K, Math.max(1, Math.floor(body.k)));
  }

  const filters: Record<string, string[]> = {};
  const rawFilters = body.filters;
  if (rawFilters !== undefined && rawFilters !== null) {
    if (!isPlainObject(rawFilters)) return bad;
    const axes = Object.keys(rawFilters);
    if (axes.length > MAX_FILTER_AXES) return bad;
    for (const axis of axes) {
      if (RESERVED_KEYS.has(axis)) return bad;
      const values = rawFilters[axis];
      if (!Array.isArray(values) || values.length > MAX_FILTER_VALUES) return bad;
      if (!values.every((v: unknown) => typeof v === "string" && v.length <= MAX_FILTER_VALUE_CHARS)) return bad;
      filters[axis] = values.slice();
    }
  }

  return { ok: true as const, messages, filters, k, question };
}

// 앞 답(assistant)이 하나라도 있으면 후속 질문으로 보고 고쳐 쓴다.
export function needsRewrite(messages: Msg[]): boolean {
  return messages.some((m) => m.role === "assistant");
}

// 근거가 없을 때의 답. 값이 있는 필터 축이 하나라도 있으면 필터를 줄이라고 안내한다.
export function noEvidenceAnswer(filters: Record<string, string[]>): string {
  return Object.values(filters).some((v) => v.length > 0) ? NO_EVIDENCE_FILTERED_ANSWER : NO_EVIDENCE_ANSWER;
}

// content의 첫 비어 있지 않은 줄에서 앞 "# "를 뗀 슬라이드 제목.
export function titleOf(content: unknown): string {
  if (typeof content !== "string") return "";
  const first = content.split(/\r?\n/).find((line) => line.trim() !== "") ?? "";
  return first.replace(/^\s*#+\s*/, "").trim();
}

// 이전 답의 근거 번호 [1]·[1, 3]을 지운다(새 근거 번호와 섞이지 않게).
export function stripCitations(text: string): string {
  return text.replace(/\[\d+(?:\s*,\s*\d+)*\]/g, "");
}

// pgvector 입력 문자열 "[0.1234567,-0.0000123,...]".
export function toVectorLiteral(vec: number[]): string {
  return "[" + vec.map((x) => Number(x).toFixed(7)).join(",") + "]";
}

function evidenceItem(r: any, n: number, imageUrls: Record<string, string | null>) {
  const labels = isPlainObject(r.labels) ? r.labels : {};
  const path = typeof r.slide_image_path === "string" ? r.slide_image_path : null;
  return {
    n,
    chunk_id: r.chunk_id,
    title: titleOf(r.content),
    content: typeof r.content === "string" ? r.content : "",
    labels,
    doc_meta: labels.doc_meta ?? null,
    file_id16: String(r.file_id ?? "").slice(0, 16),
    image_url: path && imageUrls[path] ? imageUrls[path] : null,
    image_path: path,
    kind: "hit" as "hit" | "sibling",
    sibling_of: null as number | null,
    scores: {
      rrf: r.rrf_score ?? null,
      vector_similarity: r.vector_similarity ?? null,
      text_score: r.text_score ?? null,
      vector_pos: r.vector_pos ?? null,
      text_pos: r.text_pos ?? null,
    },
  };
}

// RPC 행 → 응답 근거(kind "hit"). imageUrls: slide_image_path → 서명 URL(없으면 null).
export function buildEvidence(rows: any[], imageUrls: Record<string, string | null>) {
  return rows.map((r, i) => evidenceItem(r, i + 1, imageUrls));
}

// 같은 파일의 다른 chunk를 hit 뒤에 번호를 이어 붙인다(kind "sibling", sibling_of = 그 파일의 첫 hit 번호).
// 이미 hit인 chunk는 빼고, 파일 안에서는 seq 순, 파일 순서는 hit 순이다. 파일당·전체 상한을 넘으면 버린다.
export function attachSiblings(evidence: any[], siblingRows: any[], imageUrls: Record<string, string | null>) {
  const hitIds = new Set(evidence.map((e) => e.chunk_id));
  const firstHit = new Map<string, number>();
  const fileOrder: string[] = [];
  for (const e of evidence) {
    if (!firstHit.has(e.file_id16)) {
      firstHit.set(e.file_id16, e.n);
      fileOrder.push(e.file_id16);
    }
  }
  const byFile = new Map<string, any[]>();
  for (const r of Array.isArray(siblingRows) ? siblingRows : []) {
    if (!r || hitIds.has(r.chunk_id)) continue;
    const f = String(r.file_id ?? "").slice(0, 16);
    if (!firstHit.has(f)) continue;
    const list = byFile.get(f) ?? [];
    if (!list.some((x) => x.chunk_id === r.chunk_id)) list.push(r);
    byFile.set(f, list);
  }
  const out = evidence.slice();
  let added = 0;
  for (const f of fileOrder) {
    const list = (byFile.get(f) ?? []).sort((a, b) => (Number(a.seq) || 0) - (Number(b.seq) || 0));
    for (const r of list.slice(0, MAX_SIBLINGS_PER_FILE)) {
      if (added >= MAX_SIBLINGS_TOTAL) return out;
      const item = evidenceItem(r, out.length + 1, imageUrls);
      item.kind = "sibling";
      item.sibling_of = firstHit.get(f) ?? null;
      item.scores = { rrf: null, vector_similarity: null, text_score: null, vector_pos: null, text_pos: null };
      out.push(item);
      added++;
    }
  }
  return out;
}

function axesSummary(labels: any): string {
  const axes = isPlainObject(labels?.axes) ? labels.axes : {};
  const parts: string[] = [];
  for (const [axis, values] of Object.entries(axes)) {
    if (Array.isArray(values) && values.length > 0) parts.push(`${axis}=${values.join(", ")}`);
  }
  return parts.join(" / ") || "(없음)";
}

function docMetaSummary(meta: any): string {
  if (!isPlainObject(meta)) return "(없음)";
  const lots = Array.isArray(meta.lots) ? meta.lots : [];
  const lotText = lots
    .filter((l: any) => isPlainObject(l) && l.lot)
    .map((l: any) => (Array.isArray(l.wf) && l.wf.length > 0 ? `${l.lot}(WF ${l.wf.join(",")})` : String(l.lot)))
    .join("; ");
  return [
    `Lot/WF: ${lotText || "(없음)"}`,
    `작성자: ${meta.author || "(없음)"}`,
    `날짜: ${meta.date || "(없음)"}`,
  ].join(" | ");
}

// askConfirm: 이번 답 끝에 확인 질문을 붙일지(CONFIRM_QUESTION_RATE로 서버가 정한다).
function answerSystemPrompt(n: number, askConfirm: boolean): string {
  return [
    "너는 삼성전자 반도체연구소의 BEOL Integration 공정 평가 슬라이드를 찾아 분석해 주는 '전문적이고 친절한 AI 어시스턴트'다.",
    `사용자의 질문에 대해 아래 제공된 [근거] [1]…[${n}]을 바탕으로 한국어로 정중하게(~습니다/합니다) 답변하라.`,
    "",
    "[데이터 처리 및 추론 규칙]",
    "1. 검색된 슬라이드와 '같은 파일'로 표시된 슬라이드는 같은 평가의 앞뒤 내용이므로, 반드시 함께 읽고 문맥을 종합하여 추론하라.",
    "2. 근거에 없는 내용은 절대 지어내지 마며, 외부 지식이나 개인적 추측을 섞지 마라.",
    [
      "3. 데이터가 질문에 답하기에 부족하거나 없는 경우, 억지로 답변을 만들지 말고 아래 안내 문장을 포함하여 정중하게 안내하라. 근거에 질문과 관련된 내용이 전혀 없을 때만 이 문장을 쓰고, 일부라도 관련 있으면 있는 내용으로 답하라.",
      `   "찾으시는 내용과 완벽하게 일치하는 기존 평가결과를 확인하지 못했습니다. EDM 데이터 정제와 서비스 품질 향상을 지속적으로 진행 중입니다."`,
      `   (이후 이어지는 안내 문장: ${NO_ANSWER_GUIDE})`,
    ].join("\n"),
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
    `   <table class="border-collapse border"><thead><tr><th class="border px-3 py-2">...</th></tr></thead><tbody><tr><td class="border px-3 py-2">...</td></tr></tbody></table>`,
    "2. 표 안에는 style, onclick 등 지정되지 않은 다른 속성이나 태그를 임의로 추가하지 마라.",
    "3. 각 문장의 끝, 혹은 표의 각 행 마지막 <td> 내용 끝에 그 내용을 뒷받침하는 실제 근거 번호를 [1]이나 [1][3] 형태로 달아라.",
    "4. 같은 파일 슬라이드에서 온 내용은 해당 슬라이드의 번호를 붙여라.",
    "",
    "[확인 질문 규칙]",
    askConfirm
      ? "답변의 가장 마지막 줄에는 작성자가 원하는 답변이 맞는지 친절하게 묻는 짧은 확인 질문을 추가하라. (이 문장에는 근거 번호를 붙이지 마라.)"
      : "이번 답변에는 마지막 확인 질문을 추가하지 마라.",
  ].join("\n");
}

// 답 맨 끝 질문 문장("…맞나요? [2][4]")에 붙은 번호를 지운다. 확인 질문은 근거가 아니다.
const TRAILING_QUESTION_CITES = /(\?[ \t]*(?:\p{Extended_Pictographic}️?[ \t]*)*)(?:[ \t]*\[\d+\])+[ \t]*$/u;
export function stripTrailingQuestionCitations(text: string): string {
  return text.replace(TRAILING_QUESTION_CITES, "$1").trimEnd();
}

// 답변 생성용 chat messages. messages의 마지막은 지금 질문이다.
export function buildAnswerMessages(
  messages: Msg[],
  evidence: any[],
  question: string,
  searchQuery?: string,
  askConfirm = false,
) {
  const prior = messages.slice(0, -1).slice(-(MAX_MESSAGES - 1));
  const history = prior
    .map((m) =>
      m.role === "assistant"
        ? `도우미: ${stripCitations(m.content).slice(0, MAX_CONTEXT_ASSISTANT_CHARS)}`
        : `사용자: ${m.content}`
    )
    .join("\n\n");

  const blocks = evidence
    .map((e) => {
      const sibling = e.kind === "sibling";
      const tag = sibling ? ` (같은 파일 — [${e.sibling_of}]과 같은 파일의 다른 슬라이드)` : "";
      return [
        `[${e.n}]${tag} 제목: ${e.title || "(제목 없음)"}`,
        `축 라벨: ${axesSummary(e.labels)}`,
        docMetaSummary(e.doc_meta),
        "본문:",
        String(e.content ?? "").slice(0, sibling ? MAX_SIBLING_CONTENT_CHARS : MAX_EVIDENCE_CONTENT_CHARS),
      ].join("\n");
    })
    .join("\n\n");

  const parts: string[] = [];
  if (history) parts.push(`[이전 대화]\n${history}`);
  parts.push(`[근거]\n${blocks}`);
  let q = `[질문]\n${question}`;
  if (searchQuery && searchQuery !== question) q += `\n(검색에 쓴 질문: ${searchQuery})`;
  parts.push(q);

  return [
    { role: "system", content: answerSystemPrompt(evidence.length, askConfirm) },
    { role: "user", content: parts.join("\n\n") },
  ];
}

const CITE_ITEM = String.raw`\d+(?:\s*[-–]\s*\d+)?`;
const CITE_BRACKET = String.raw`\[\s*${CITE_ITEM}(?:\s*,\s*${CITE_ITEM})*\s*\]`;
// 이어 붙은 인용 묶음 "[1][2-3]". "TaN[1]"·"10nm[2]"처럼 영문·숫자 바로 뒤도 인용으로 본다.
// "]" 뒤에서는 새 묶음을 시작하지 않는다(묶음 중간에서 다시 잡지 않게).
const CITE_RUN = new RegExp(String.raw`([ \t]*)(?<!\])((?:${CITE_BRACKET})+)`, "g");

// "3" → [3], "1-3" → [1,2,3]. 거꾸로 된 범위나 MAX_CITE_RANGE보다 긴 범위는 버린다.
function citeNumbers(item: string): number[] {
  const range = item.match(/^(\d+)\s*[-–]\s*(\d+)$/);
  if (!range) return [Number(item)];
  const a = Number(range[1]);
  const b = Number(range[2]);
  if (b < a || b - a + 1 > MAX_CITE_RANGE) return [];
  return Array.from({ length: b - a + 1 }, (_, i) => a + i);
}

// 범위 밖 [m] 제거. "[1, 3]"·"[1-3]"·"[ 2 ]" 꼴은 "[1][3]"처럼 펼친다. cited는 남은 번호(오름차순, 중복 없음).
export function fixCitations(answer: string, n: number) {
  const cited = new Set<number>();
  const text = answer.replace(CITE_RUN, (_all: string, lead: string, run: string) => {
    const valid: number[] = [];
    for (const [, inner] of run.matchAll(/\[([^\]]*)\]/g)) {
      for (const item of inner.split(",")) {
        for (const m of citeNumbers(item.trim())) {
          if (Number.isInteger(m) && m >= 1 && m <= n && !valid.includes(m)) valid.push(m);
        }
      }
    }
    if (valid.length === 0) return "";
    for (const m of valid) cited.add(m);
    return lead + valid.map((m) => `[${m}]`).join("");
  });
  return { text, cited: [...cited].sort((a, b) => a - b) };
}

// 답 후처리. 번호를 고친 뒤, "자료에 없음 — …"으로 시작하는 답은
// [첫 문장(번호 없음)] + NO_ANSWER_GUIDE + [나머지 참고 설명(번호 유지)] 꼴로 맞춘다.
// 안내 문장은 모델이 빠뜨려도 붙고, 두 번 쓰면 하나만 남는다. cited는 나머지 설명의 번호만 센다.
export function finalizeAnswer(answer: string, n: number) {
  const fixed = fixCitations(stripTrailingQuestionCitations(answer.trim()), n);
  const text = fixed.text.trim();
  if (!text.startsWith(NO_ANSWER_PREFIX)) return { text, cited: fixed.cited };

  const body = text.split(NO_ANSWER_GUIDE).join(" ").replace(/[ \t]{2,}/g, " ").trim();
  // "SF1.0"처럼 숫자 속 마침표에서 끊기지 않게 "다."·"요."로 끝나는 첫 문장을 찾는다(번호가 붙어 있어도 된다).
  const m = body.match(/^.*?[다요](?:[ \t]*\[\d+\])*\.(?:[ \t]*\[\d+\])*(?=\s|$)/);
  const firstRaw = m ? m[0] : body;
  const rest = body.slice(firstRaw.length).trim();
  const first = firstRaw.replace(/[ \t]*\[\d+\]/g, "").trim();
  const restFixed = fixCitations(rest, n);
  const out = [first, NO_ANSWER_GUIDE, restFixed.text.trim()].filter((s) => s).join(" ");
  return { text: out, cited: restFixed.cited };
}
