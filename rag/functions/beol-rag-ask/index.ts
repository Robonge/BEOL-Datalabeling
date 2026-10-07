// Supabase Edge Function beol-rag-ask: 질문 → (후속이면 고쳐 쓰기) → 임베딩 → hybrid 검색 → 근거 그림 서명 → 한국어 답.
// 외부 패키지 없이 Deno.serve·fetch만 쓴다. 로그는 요청마다 사유 코드 한 줄뿐이다.
import {
  attachSiblings,
  buildAnswerMessages,
  buildEvidence,
  CONFIRM_QUESTION_RATE,
  corsHeaders,
  EMBED_DIM,
  EMBED_MODEL,
  finalizeAnswer,
  MAX_BODY_BYTES,
  MAX_CONTEXT_ASSISTANT_CHARS,
  MAX_REWRITE_CHARS,
  needsRewrite,
  noEvidenceAnswer,
  REWRITE_SYSTEM_PROMPT,
  stripCitations,
  toVectorLiteral,
  validateInput,
} from "./lib.ts";

const OPENAI_BASE = "https://api.openai.com/v1";
const DEFAULT_CHAT_MODEL = "gpt-6-sol";
const DEFAULT_MAX_COMPLETION_TOKENS = 1500;
const DEFAULT_SIGN_TTL = 3600;
const REWRITE_MAX_COMPLETION_TOKENS = 400;

// 요청 전체 예산(화면은 90초에 끊는다). 각 단계 timeout은 min(단계 상한, 남은 시간)이다.
const TOTAL_BUDGET_MS = 80000;
const MIN_STEP_MS = 3000;
const REWRITE_MIN_LEFT_MS = 60000;

const TIMEOUT_EMBED_MS = 20000;
const TIMEOUT_REWRITE_MS = 20000;
const TIMEOUT_SEARCH_MS = 20000;
const TIMEOUT_SIGN_MS = 15000;
const TIMEOUT_SIBLINGS_MS = 10000;
const TIMEOUT_ANSWER_MS = 45000;

type Ctx = { code: string; k: number; n_evidence: number };

class StepError extends Error {
  code: string;
  status: number;
  constructor(code: string, status: number) {
    super(code);
    this.code = code;
    this.status = status;
  }
}

function json(ctx: Ctx, status: number, code: string, body: unknown): Response {
  ctx.code = code;
  return new Response(JSON.stringify(body), {
    status,
    headers: { ...corsHeaders(), "Content-Type": "application/json; charset=utf-8" },
  });
}

function fail(ctx: Ctx, status: number, code: string): Response {
  return json(ctx, status, code, { error: code });
}

function positiveInt(raw: string | undefined, fallback: number): number {
  const n = Number.parseInt(raw ?? "", 10);
  return Number.isFinite(n) && n > 0 ? n : fallback;
}

// 남은 예산 안의 단계 timeout. 남은 시간이 MIN_STEP_MS 미만이면 그 단계 실패 코드로 끝낸다.
function stepTimeout(deadline: number, capMs: number, code: string): number {
  const left = deadline - Date.now();
  if (left < MIN_STEP_MS) throw new StepError(code, 502);
  return Math.min(capMs, left);
}

async function discard(r: Response) {
  try {
    await r.body?.cancel();
  } catch {
    // 본문 버리기 실패는 무시한다.
  }
}

// 요청 본문을 읽으며 바이트를 센다. MAX_BODY_BYTES를 넘으면 스트림을 끊고 null.
async function readBody(req: Request): Promise<Uint8Array | null> {
  if (!req.body) return new Uint8Array(0);
  const reader = req.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    total += value.byteLength;
    if (total > MAX_BODY_BYTES) {
      try {
        await reader.cancel();
      } catch {
        // 끊기 실패는 무시한다.
      }
      return null;
    }
    chunks.push(value);
  }
  const buf = new Uint8Array(total);
  let off = 0;
  for (const c of chunks) {
    buf.set(c, off);
    off += c.byteLength;
  }
  return buf;
}

// POST JSON → 응답 JSON. 호출 실패·비정상 상태·JSON 아님은 모두 StepError(code).
async function postJson(
  url: string,
  headers: Record<string, string>,
  body: unknown,
  timeoutMs: number,
  code: string,
): Promise<any> {
  let r: Response;
  try {
    r = await fetch(url, {
      method: "POST",
      headers: { ...headers, "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(timeoutMs),
    });
  } catch {
    throw new StepError(code, 502);
  }
  if (!r.ok) {
    await discard(r);
    throw new StepError(code, 502);
  }
  try {
    return await r.json();
  } catch {
    throw new StepError(code, 502);
  }
}

async function chatCompletion(
  apiKey: string,
  model: string,
  messages: unknown[],
  maxTokens: number,
  timeoutMs: number,
): Promise<{ text: string; finish_reason: string | null }> {
  const data = await postJson(
    `${OPENAI_BASE}/chat/completions`,
    { Authorization: `Bearer ${apiKey}` },
    { model, messages, max_completion_tokens: maxTokens },
    timeoutMs,
    "LLM_FAILED",
  );
  const choice = data?.choices?.[0];
  const text = choice?.message?.content;
  const reason = choice?.finish_reason;
  return { text: typeof text === "string" ? text : "", finish_reason: typeof reason === "string" ? reason : null };
}

// 후속 질문 고쳐 쓰기. 실패(호출 실패·빈 답·400자 초과)면 null.
async function rewriteQuestion(apiKey: string, model: string, messages: any[], deadline: number): Promise<string | null> {
  const convo = messages.map((m) => ({
    role: m.role,
    content: m.role === "assistant" ? stripCitations(m.content).slice(0, MAX_CONTEXT_ASSISTANT_CHARS) : m.content,
  }));
  try {
    const out = await chatCompletion(
      apiKey,
      model,
      [{ role: "system", content: REWRITE_SYSTEM_PROMPT }, ...convo],
      REWRITE_MAX_COMPLETION_TOKENS,
      stepTimeout(deadline, TIMEOUT_REWRITE_MS, "LLM_FAILED"),
    );
    const q = out.text.replace(/\s+/g, " ").trim();
    if (!q || q.length > MAX_REWRITE_CHARS) return null;
    return q;
  } catch {
    return null;
  }
}

async function embed(apiKey: string, input: string, deadline: number): Promise<number[]> {
  const data = await postJson(
    `${OPENAI_BASE}/embeddings`,
    { Authorization: `Bearer ${apiKey}` },
    { model: EMBED_MODEL, input },
    stepTimeout(deadline, TIMEOUT_EMBED_MS, "EMBED_FAILED"),
    "EMBED_FAILED",
  );
  const vec = data?.data?.[0]?.embedding;
  if (!Array.isArray(vec) || vec.length !== EMBED_DIM) throw new StepError("EMBED_DIM_MISMATCH", 502);
  if (!vec.every((x) => typeof x === "number" && Number.isFinite(x))) throw new StepError("EMBED_FAILED", 502);
  return vec;
}

async function search(
  baseUrl: string,
  anonKey: string,
  vec: number[],
  queryText: string,
  filters: Record<string, string[]>,
  k: number,
  deadline: number,
): Promise<any[]> {
  const rows = await postJson(
    `${baseUrl}/rest/v1/rpc/beol_rag_search`,
    { apikey: anonKey, Authorization: `Bearer ${anonKey}` },
    { query_embedding: toVectorLiteral(vec), query_text: queryText, filters, k },
    stepTimeout(deadline, TIMEOUT_SEARCH_MS, "SEARCH_FAILED"),
    "SEARCH_FAILED",
  );
  if (!Array.isArray(rows)) throw new StepError("SEARCH_FAILED", 502);
  return rows.slice(0, k);
}

// 검색된 행과 같은 파일의 chunk 전부(읽기 창 beol_rag_chunks, anon SELECT). 실패하거나 예산이 모자라면 null.
async function fetchSiblings(baseUrl: string, anonKey: string, rows: any[], deadline: number): Promise<any[] | null> {
  const ids = [...new Set(rows.map((r) => r.file_id).filter((f) => typeof f === "string" && /^[0-9a-f]+$/i.test(f)))];
  if (ids.length === 0) return [];
  const q = new URLSearchParams({
    select: "chunk_id,file_id,seq,content,labels,slide_image_bucket,slide_image_path",
    file_id: `in.(${ids.map((f) => `"${f}"`).join(",")})`,
    order: "file_id,seq",
  });
  try {
    const r = await fetch(`${baseUrl}/rest/v1/beol_rag_chunks?${q}`, {
      headers: { apikey: anonKey, Authorization: `Bearer ${anonKey}` },
      signal: AbortSignal.timeout(stepTimeout(deadline, TIMEOUT_SIBLINGS_MS, "SIBLINGS_FAILED")),
    });
    if (!r.ok) {
      await discard(r);
      return null;
    }
    const data = await r.json();
    return Array.isArray(data) ? data : null;
  } catch {
    return null;
  }
}

// 근거 그림 서명 URL. 버킷마다 한 번 호출한다. 실패하거나 예산이 모자란 경로는 null로 두고 ok=false.
async function signImages(
  baseUrl: string,
  anonKey: string,
  rows: any[],
  ttl: number,
  deadline: number,
): Promise<{ urls: Record<string, string | null>; ok: boolean }> {
  const urls: Record<string, string | null> = {};
  const byBucket = new Map<string, string[]>();
  for (const r of rows) {
    if (typeof r.slide_image_bucket !== "string" || typeof r.slide_image_path !== "string") continue;
    const list = byBucket.get(r.slide_image_bucket) ?? [];
    if (!list.includes(r.slide_image_path)) list.push(r.slide_image_path);
    byBucket.set(r.slide_image_bucket, list);
  }
  let ok = true;
  for (const [bucket, paths] of byBucket) {
    for (const p of paths) urls[p] = null;
    try {
      const items = await postJson(
        `${baseUrl}/storage/v1/object/sign/${encodeURIComponent(bucket)}`,
        { apikey: anonKey, Authorization: `Bearer ${anonKey}` },
        { expiresIn: ttl, paths },
        stepTimeout(deadline, TIMEOUT_SIGN_MS, "SIGN_FAILED"),
        "SIGN_FAILED",
      );
      if (!Array.isArray(items)) {
        ok = false;
        continue;
      }
      for (const it of items) {
        const signed = it?.signedURL;
        if (typeof it?.path !== "string" || typeof signed !== "string" || !signed) continue;
        if (/^https?:\/\//.test(signed)) urls[it.path] = signed;
        else urls[it.path] = `${baseUrl}/storage/v1${signed.startsWith("/") ? "" : "/"}${signed}`;
      }
      if (paths.some((p) => !urls[p])) ok = false;
    } catch {
      ok = false;
    }
  }
  return { urls, ok };
}

async function handle(req: Request, ctx: Ctx, deadline: number): Promise<Response> {
  if (req.method === "OPTIONS") {
    ctx.code = "OPTIONS";
    return new Response(null, { status: 204, headers: corsHeaders() });
  }
  if (req.method !== "POST") return fail(ctx, 405, "METHOD_NOT_ALLOWED");

  const declared = Number(req.headers.get("content-length") ?? "0");
  if (Number.isFinite(declared) && declared > MAX_BODY_BYTES) return fail(ctx, 400, "BAD_REQUEST_JSON");
  let body: unknown;
  try {
    const buf = await readBody(req);
    if (buf === null) return fail(ctx, 400, "BAD_REQUEST_JSON");
    body = JSON.parse(new TextDecoder().decode(buf));
  } catch {
    return fail(ctx, 400, "BAD_REQUEST_JSON");
  }

  const input = validateInput(body);
  if (!input.ok) return fail(ctx, 400, input.code);
  const { messages, filters, k, question } = input;
  ctx.k = k;

  const apiKey = Deno.env.get("OPENAI_API_KEY");
  const baseUrlRaw = Deno.env.get("SUPABASE_URL");
  const anonKey = Deno.env.get("SUPABASE_ANON_KEY");
  if (!apiKey || !baseUrlRaw || !anonKey) return fail(ctx, 500, "CONFIG_MISSING");
  const baseUrl = baseUrlRaw.replace(/\/+$/, "");
  const chatModel = (Deno.env.get("RAG_CHAT_MODEL") ?? "").trim() || DEFAULT_CHAT_MODEL;
  const maxTokens = positiveInt(Deno.env.get("RAG_MAX_COMPLETION_TOKENS"), DEFAULT_MAX_COMPLETION_TOKENS);
  const signTtl = positiveInt(Deno.env.get("RAG_SIGN_TTL"), DEFAULT_SIGN_TTL);

  try {
    const warnings: string[] = [];
    let searchQuery = question;
    // 남은 시간이 REWRITE_MIN_LEFT_MS 미만이면 고쳐 쓰기를 건너뛰고 원문으로 검색한다.
    if (needsRewrite(messages) && deadline - Date.now() >= REWRITE_MIN_LEFT_MS) {
      const rewritten = await rewriteQuestion(apiKey, chatModel, messages, deadline);
      if (rewritten) searchQuery = rewritten;
      else warnings.push("REWRITE_FAILED");
    }

    const vec = await embed(apiKey, searchQuery, deadline);
    const rows = await search(baseUrl, anonKey, vec, searchQuery, filters, k, deadline);

    if (rows.length === 0) {
      const none: Record<string, unknown> = {
        answer: noEvidenceAnswer(filters),
        rewritten_query: searchQuery,
        cited: [],
        evidence: [],
      };
      if (warnings.length > 0) none.warnings = warnings;
      return json(ctx, 200, "NO_EVIDENCE", none);
    }

    // 같은 파일의 다른 chunk도 근거로 붙인다. 못 불러오면 검색된 행만으로 답하고 경고를 남긴다.
    const siblingRows = await fetchSiblings(baseUrl, anonKey, rows, deadline);
    if (siblingRows === null) warnings.push("SIBLINGS_FAILED");
    const hitIds = new Set(rows.map((r) => r.chunk_id));
    const extra = (siblingRows ?? []).filter((r) => !hitIds.has(r.chunk_id));

    const signed = await signImages(baseUrl, anonKey, rows.concat(extra), signTtl, deadline);
    const evidence = attachSiblings(buildEvidence(rows, signed.urls), extra, signed.urls);
    ctx.n_evidence = evidence.length;
    if (!signed.ok) warnings.push("SIGN_FAILED");

    const answer = await chatCompletion(
      apiKey,
      chatModel,
      buildAnswerMessages(messages, evidence, question, searchQuery, Math.random() < CONFIRM_QUESTION_RATE),
      maxTokens,
      stepTimeout(deadline, TIMEOUT_ANSWER_MS, "LLM_FAILED"),
    );
    if (!answer.text.trim()) return fail(ctx, 502, "LLM_EMPTY");
    if (answer.finish_reason === "length") warnings.push("TRUNCATED");
    const fixed = finalizeAnswer(answer.text, evidence.length);

    const out: Record<string, unknown> = {
      answer: fixed.text,
      rewritten_query: searchQuery,
      cited: fixed.cited,
      evidence,
    };
    if (warnings.length > 0) out.warnings = warnings;
    return json(ctx, 200, signed.ok ? "OK" : "OK_SIGN_FAILED", out);
  } catch (e) {
    if (e instanceof StepError) return fail(ctx, e.status, e.code);
    throw e;
  }
}

Deno.serve(async (req: Request) => {
  const started = Date.now();
  const ctx: Ctx = { code: "INTERNAL", k: 0, n_evidence: 0 };
  let res: Response;
  try {
    res = await handle(req, ctx, started + TOTAL_BUDGET_MS);
  } catch {
    res = fail(ctx, 500, "INTERNAL");
  }
  console.log(JSON.stringify({ code: ctx.code, ms: Date.now() - started, k: ctx.k, n_evidence: ctx.n_evidence }));
  return res;
});
