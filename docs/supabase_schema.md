# Supabase 벡터 표 정의 (사외 PoC)

`push-vectors`가 쓰는 Supabase(Postgres + pgvector) 표다. 로컬 `work.sqlite`의 `chunk_embeddings`가 원본이고 이 표는 사본이다. `.sql` 파일은 허용 형식이 아니므로 SQL은 아래 코드 블록에 둔다. Supabase 대시보드의 SQL 편집기에 그대로 붙여넣어 실행할 수 있다.

- 표 이름은 `pipeline.json`의 `supabase.table`과 같아야 한다. PoC는 다른 앱과 같은 프로젝트를 쓰므로 `beol_chunk_embeddings`로 둔다.
- `vector(1536)`은 `text-embedding-3-small`의 차원이다. 임베딩 모델을 바꾸면 차원과 표를 함께 바꾼다.
- upsert 충돌 키는 `(chunk_id, model)`이다(`Prefer: resolution=merge-duplicates`, `on_conflict=chunk_id,model`).
- RLS를 켜고 정책을 두지 않는다. `service_role` 키로만 쓰고 읽는다. anon·authenticated 권한은 회수한다.
- RAG view·RPC는 아래 RAG 절 참고
- 경로 열은 두지 않는다. 파일명은 `file_name` 열에 둔다(2026-10-07 추가, 아래 "파일명 열" 절).
- work.sqlite·export의 `files.memo` 열은 항상 NULL이다(2026-10-07). 예전 taxonomy.xlsx `files` 시트의 맥락 메모 기능을 없애서 쓰지 않고, 하위 호환을 위해 열만 둔다.

```sql
create extension if not exists vector with schema extensions;

create table if not exists public.beol_chunk_embeddings (
  chunk_id   text        not null,
  model      text        not null,
  file_id    text        not null,
  file_name  text,
  seq        integer     not null,
  dim        integer     not null,
  embedding  extensions.vector(1536) not null,
  content    text,
  labels     jsonb       not null default '{}'::jsonb,
  run_id     text,
  updated_at timestamptz not null default now(),
  primary key (chunk_id, model),
  constraint beol_chunk_embeddings_dim_chk check (dim = 1536)
);

comment on table public.beol_chunk_embeddings is 'BEOL labelbot 사외 PoC: chunk 임베딩 사본. 로컬 work.sqlite chunk_embeddings가 원본.';

alter table public.beol_chunk_embeddings enable row level security;
revoke all on public.beol_chunk_embeddings from anon, authenticated;

create index if not exists beol_chunk_embeddings_file_idx on public.beol_chunk_embeddings (file_id);
create index if not exists beol_chunk_embeddings_hnsw_idx on public.beol_chunk_embeddings
  using hnsw (embedding extensions.vector_cosine_ops);
```

적재 확인:

```sql
select model, count(*), min(dim), max(dim) from public.beol_chunk_embeddings group by model;
```

## 파일명 열 (2026-10-07)

이미 만든 표에는 아래로 열을 추가한다. `push-vectors`가 work.sqlite `files.file_name`을 채운다. 파일명은 `label_hash` 해시에 함께 들어가므로, 열을 추가한 뒤 `push-vectors`를 다시 돌리면 기존 행도 채워진다.

```sql
alter table public.beol_chunk_embeddings add column if not exists file_name text;
```

## 슬라이드 미리보기 JPG (push-slides)

`slide-images`가 검수 화면과 같은 슬라이드 근사 미리보기를 JPG로 렌더해 로컬 `slide_images/<sha256>.b64`에 두고, `push-slides`가 Storage 버킷에 올린 뒤 위 표의 행에 아래 열을 채운다. 라벨(`labels`)과 `label_hash`는 바꾸지 않는다.

- 버킷: `pipeline.json`의 `supabase.storage_bucket`(기본 `BEOL-labeling`), private. `service_role` 키로만 올리고, 조회는 서명 URL로 한다.
- 객체 경로: `<file_id 앞 16자>/<슬라이드 번호 4자리>.jpg`(예: `177051f5eb72f156/0001.jpg`). 파일명은 넣지 않는다. 같은 경로는 덮어쓴다(`x-upsert: true`).
- `supabase.storage_enabled=true`일 때만 호출한다. 행이 있어야 열을 채우므로 `push-vectors` 다음에 부른다(행이 없으면 `ROW_MISSING`으로 남고 다음 실행에 다시 한다).
- 버킷 이름에 대문자가 거부되면 `beol-labeling`으로 만들고 `storage_bucket`만 바꾼다.

```sql
alter table public.beol_chunk_embeddings
  add column if not exists slide_image_bucket text,
  add column if not exists slide_image_path   text,
  add column if not exists slide_image_sha256 text,
  add column if not exists slide_image_width  integer,
  add column if not exists slide_image_height integer;

insert into storage.buckets (id, name, public)
  values ('BEOL-labeling', 'BEOL-labeling', false)
  on conflict (id) do nothing;
```

확인:

```sql
select id, public from storage.buckets where id = 'BEOL-labeling';
select count(*) filter (where slide_image_path is not null) as with_image, count(*) from public.beol_chunk_embeddings;
select name from storage.objects where bucket_id = 'BEOL-labeling' order by name limit 5;
```

## RAG 화면용 읽기 창·검색대·피드백 표 (2026-10-07)

RAG 웹 화면(`rag/beol_rag.html`)과 Edge Function `beol-rag-ask`가 쓰는 객체다. 위 절의 표·열·색인·pk는 바꾸지 않고 **추가만** 한다. 기본 표에 생성 열 `content_tsv`와 GIN 색인 하나를 더하지만, `push-vectors`는 보낸 열만 upsert하므로 적재에는 영향이 없다. 다른 앱의 표는 참조하지 않고 `beol_` 객체와 `storage.objects`의 정책 하나만 다룬다.

- **공개 범위**: anon·authenticated는 "완전한 행"만 읽는다. 완전한 행은 모델이 `text-embedding-3-small`이고 `labels.axes."Patterning/scheme"`가 비어 있지 않은 배열이며 `labels.doc_meta`가 있고(null 아님) 슬라이드 그림 경로가 있는 행이다. 판정은 함수 `beol_rag_is_complete` 하나로 하고 view·RPC·Storage 정책(view 경유)이 같이 쓴다. 옛 행은 지우지 않고 보이지만 않게 한다.
- **비공개 열**: `embedding`·`file_name`은 view와 RPC 반환에 넣지 않는다. view에 `name` 열도 두지 않는다(Storage 정책 안의 `name`이 view 열로 해석되면 조건이 깨진다).
- **쓰기**: anon·authenticated의 쓰기는 피드백 표 `beol_rag_feedback`의 insert 하나뿐이다(select·update·delete 없음, 크기 상한은 정책의 `with check`). 기본 표 `beol_chunk_embeddings`의 anon·authenticated 권한은 맨 위 절에서 회수한 그대로 둔다.
- **권한 순서**: 이 프로젝트는 기본 권한(`pg_default_acl`) 때문에 새 relation에 anon 쓰기 권한이, 새 함수에 anon 실행 권한이 자동으로 붙는다. 그래서 view·표는 `revoke all` 다음에 필요한 권한만 `grant`한다. 단일 표 view는 자동 갱신 가능 view라 쓰기 권한이 남으면 anon의 update·delete가 소유자 권한으로 기본 표에 닿는다.
- **슬라이드 그림**: 버킷 `BEOL-labeling`은 private로 둔다. public으로 바꾸면 옛 행 그림도 주소만으로 열리기 때문이다. Storage 정책은 완전한 행의 그림 객체만 anon select를 허용하고, 함수는 anon 키로 서명 URL을 만들어 준다(`POST /storage/v1/object/sign/BEOL-labeling`).
- **HNSW 대신 전수 cosine**: 검색대는 라벨 필터로 후보를 먼저 거른 뒤 후보 전체에 cosine 거리를 계산한다. HNSW는 근사 색인이라 필터와 함께 쓰면 후보 일부만 보고 걸러 맞는 행을 놓친다. 완전한 행이 수천 개가 될 때까지는 전수 계산이 정확하고 충분히 빠르다. 기존 HNSW 색인은 그대로 둔다.
- **단어 검색**: `to_tsvector('simple', content)` 생성 열과 GIN 색인을 쓴다. 질의 낱말은 OR로 묶고(`websearch_to_tsquery`), 점수는 `ts_rank_cd`다. 벡터 순위와 단어 순위는 RRF(`1/(60+순위)` 합)로 합친다. 동점은 `chunk_id`로 정렬해 순서가 매번 같다.
- **advisor 경고**: `security_definer_view`(`beol_rag_chunks`·`beol_rag_facets`)와 "anon이 실행할 수 있는 security definer 함수"(`beol_rag_search`)는 의도한 것이다. view는 기본 표(RLS on, 정책 없음)를 소유자 권한으로 읽어야 하고, RPC는 `embedding`이 필요해 기본 표를 직접 읽는다. 그 밖의 새 경고는 고친다.

아래 코드 블록 7개는 각각 독립 마이그레이션이다. 01부터 순서대로 그대로 적용한다(MCP `apply_migration` 이름 `beol_rag_01_is_complete` … `beol_rag_07_feedback`). 모두 멱등이라 같은 블록을 다시 적용해도 된다.

- 2026-10-07 보안·코드 검토 반영: view 2개에 `security_barrier`, Storage 정책에 버킷 이름 고정, 피드백 표는 열 단위 insert 권한(`id`·`created_at`은 서버 기본값)과 `evidence` 배열·길이 검사, 검색대는 질의의 따옴표·낱말 앞 `-`를 지운다. 이미 01~07을 적용한 DB에는 MCP 마이그레이션 `beol_rag_08_harden_views`(03·04·06·07 블록의 바뀐 부분)와 `beol_rag_09_search_query_cleanup`(05 블록)으로 올렸다. 피드백 정책의 배열 길이 검사를 `case`로 감싼 07 블록 변경은 `beol_rag_10_feedback_policy_case`로 올렸다. 새 DB는 아래 블록만 순서대로 적용하면 같다.

### 01_is_complete — 완전한 행 판정

```sql
create or replace function public.beol_rag_is_complete(labels jsonb, slide_image_path text, model text)
returns boolean
language sql
immutable
set search_path = ''
as $$
  select model = 'text-embedding-3-small'
     and (case
            when jsonb_typeof(labels->'axes'->'Patterning/scheme') = 'array'
              then jsonb_array_length(labels->'axes'->'Patterning/scheme') > 0
            else false
          end)
     and labels ? 'doc_meta'
     and jsonb_typeof(labels->'doc_meta') <> 'null'
     and slide_image_path is not null
$$;
```

### 02_tsv — 단어 검색 생성 열과 GIN 색인

```sql
alter table public.beol_chunk_embeddings
  add column if not exists content_tsv tsvector
  generated always as (to_tsvector('simple', coalesce(content, ''))) stored;

create index if not exists beol_chunk_embeddings_tsv_idx
  on public.beol_chunk_embeddings using gin (content_tsv);
```

### 03_chunks_view — 완전한 행 읽기 창

```sql
create or replace view public.beol_rag_chunks
with (security_invoker = false, security_barrier = true)
as
select
  e.chunk_id,
  e.file_id,
  left(e.file_id, 16) as file_id16,
  e.seq,
  e.run_id,
  regexp_replace(split_part(e.content, E'\n', 1), '^#\s*', '') as title,
  e.content,
  e.labels,
  e.labels->'doc_meta' as doc_meta,
  e.slide_image_bucket,
  e.slide_image_path,
  e.slide_image_width,
  e.slide_image_height,
  e.updated_at
from public.beol_chunk_embeddings e
where public.beol_rag_is_complete(e.labels, e.slide_image_path, e.model);

revoke all on public.beol_rag_chunks from public, anon, authenticated;
grant select on public.beol_rag_chunks to anon, authenticated;
```

### 04_facets_view — 축별 값 목록

`n`은 그 값을 가진 완전한 행(chunk) 수다. 축 묶음이 객체가 아니거나 축 값이 배열이 아니면 건너뛴다.

```sql
create or replace view public.beol_rag_facets
with (security_invoker = false, security_barrier = true)
as
select
  a.key as axis,
  v.value as value,
  count(distinct c.chunk_id)::int as n
from public.beol_rag_chunks c
cross join lateral jsonb_each(
  case when jsonb_typeof(c.labels->'axes') = 'object' then c.labels->'axes' else '{}'::jsonb end
) as a(key, value)
cross join lateral jsonb_array_elements_text(
  case when jsonb_typeof(a.value) = 'array' then a.value else '[]'::jsonb end
) as v(value)
group by a.key, v.value;

revoke all on public.beol_rag_facets from public, anon, authenticated;
grant select on public.beol_rag_facets to anon, authenticated;
```

### 05_search_rpc — hybrid 검색대

- `filters`: `{"축": ["값", …], …}`. 축 안은 OR, 축끼리는 AND다. 값이 빈 배열인 축은 필터 없음으로 본다. 객체가 아니거나 값이 배열이 아니면 `BAD_FILTER`.
- `k`는 1~8로 자른다. `query_text`가 비면 단어 순위는 빈 집합이다.
- 벡터 순위는 후보 전체(상한 200)에, 단어 순위는 `content_tsv @@ q`인 후보(상한 200)에만 매긴다. `vector_similarity`는 `1 - cosine 거리`다.

```sql
create or replace function public.beol_rag_search(
  query_embedding extensions.vector(1536),
  query_text text,
  filters jsonb default '{}'::jsonb,
  k int default 5
)
returns table (
  chunk_id text,
  file_id text,
  seq int,
  content text,
  labels jsonb,
  slide_image_bucket text,
  slide_image_path text,
  slide_image_width int,
  slide_image_height int,
  vector_similarity double precision,
  text_score real,
  vector_pos int,
  text_pos int,
  rrf_score double precision
)
language plpgsql
stable
security definer
set search_path = public, extensions, pg_temp
as $$
#variable_conflict use_column
declare
  flt jsonb := coalesce(filters, '{}'::jsonb);
  lim int := least(greatest(coalesce(k, 5), 1), 8);
  qtext text := btrim(coalesce(query_text, ''));
  q tsquery := null;
begin
  if jsonb_typeof(flt) <> 'object' then
    raise exception 'BAD_FILTER';
  end if;
  if exists (select 1 from jsonb_each(flt) as x where jsonb_typeof(x.value) <> 'array') then
    raise exception 'BAD_FILTER';
  end if;
  -- 따옴표(구 검색)와 낱말 앞 '-'(부정)를 지워 모든 낱말을 OR로 묶는다.
  qtext := btrim(regexp_replace(translate(qtext, '"', ' '), '(^|\s)-+', '\1', 'g'));
  if qtext <> '' then
    q := websearch_to_tsquery('simple', regexp_replace(qtext, '\s+', ' or ', 'g'));
  end if;

  return query
  with cand as materialized (
    select
      e.chunk_id,
      e.file_id,
      e.seq,
      e.content,
      e.labels,
      e.slide_image_bucket,
      e.slide_image_path,
      e.slide_image_width,
      e.slide_image_height,
      e.embedding,
      e.content_tsv
    from public.beol_chunk_embeddings e
    where public.beol_rag_is_complete(e.labels, e.slide_image_path, e.model)
      and not exists (
        select 1
        from jsonb_each(flt) as fl
        where jsonb_array_length(fl.value) > 0
          and not coalesce(
            (e.labels->'axes'->fl.key) ?| array(select jsonb_array_elements_text(fl.value)),
            false
          )
      )
  ),
  vec as (
    select
      c.chunk_id,
      (row_number() over (order by c.embedding <=> query_embedding, c.chunk_id))::int as vector_pos
    from cand c
    order by c.embedding <=> query_embedding, c.chunk_id
    limit 200
  ),
  txt as (
    select
      c.chunk_id,
      ts_rank_cd(c.content_tsv, q) as text_score,
      (row_number() over (order by ts_rank_cd(c.content_tsv, q) desc, c.chunk_id))::int as text_pos
    from cand c
    where q is not null
      and c.content_tsv @@ q
    order by ts_rank_cd(c.content_tsv, q) desc, c.chunk_id
    limit 200
  ),
  fused as (
    select
      coalesce(v.chunk_id, t.chunk_id) as chunk_id,
      t.text_score,
      v.vector_pos,
      t.text_pos,
      (coalesce(1.0 / (60 + v.vector_pos), 0) + coalesce(1.0 / (60 + t.text_pos), 0))::double precision as rrf_score
    from vec v
    full outer join txt t on t.chunk_id = v.chunk_id
  )
  select
    c.chunk_id,
    c.file_id,
    c.seq,
    c.content,
    c.labels,
    c.slide_image_bucket,
    c.slide_image_path,
    c.slide_image_width,
    c.slide_image_height,
    (1 - (c.embedding <=> query_embedding))::double precision as vector_similarity,
    fu.text_score,
    fu.vector_pos,
    fu.text_pos,
    fu.rrf_score
  from fused fu
  join cand c on c.chunk_id = fu.chunk_id
  order by fu.rrf_score desc, fu.text_pos nulls last, fu.vector_pos nulls last, fu.chunk_id
  limit lim;
end;
$$;

revoke execute on function public.beol_rag_search(extensions.vector(1536), text, jsonb, int) from public;
grant execute on function public.beol_rag_search(extensions.vector(1536), text, jsonb, int) to anon, authenticated, service_role;
```

### 06_storage_policy — 완전한 행 그림만 anon 읽기

```sql
drop policy if exists beol_rag_anon_read_slides on storage.objects;

create policy beol_rag_anon_read_slides on storage.objects
  for select to anon, authenticated
  using (
    bucket_id = 'BEOL-labeling'
    and (bucket_id, name) in (select c.slide_image_bucket, c.slide_image_path from public.beol_rag_chunks c)
  );
```

### 07_feedback — 피드백 표 (anon insert만)

화면은 `evidence`에 `[{n, chunk_id, scores}]`만 넣는다. 검증용 시험 행은 `comment='verify'`로 넣고 확인 뒤 지운다.

```sql
create table if not exists public.beol_rag_feedback (
  id         uuid        primary key default gen_random_uuid(),
  created_at timestamptz not null default now(),
  session_id text,
  question   text        not null,
  answer     text        not null,
  evidence   jsonb       not null default '[]'::jsonb,
  verdict    text        not null check (verdict in ('good', 'bad')),
  comment    text
);

alter table public.beol_rag_feedback enable row level security;
revoke all on public.beol_rag_feedback from public, anon, authenticated;
-- id·created_at은 서버 기본값만 쓰도록 열 단위로 준다.
grant insert (session_id, question, answer, evidence, verdict, comment) on public.beol_rag_feedback to anon, authenticated;

drop policy if exists beol_rag_feedback_insert on public.beol_rag_feedback;
create policy beol_rag_feedback_insert on public.beol_rag_feedback
  for insert to anon, authenticated
  with check (
    verdict in ('good', 'bad')
    and char_length(question) <= 2000
    and char_length(answer) <= 8000
    and pg_column_size(evidence) <= 16384
    -- 배열이 아니면 jsonb_array_length가 오류를 내므로 case로 먼저 거른다.
    and case when jsonb_typeof(evidence) = 'array' then jsonb_array_length(evidence) <= 9 else false end
    and coalesce(char_length(comment), 0) <= 1000
    and coalesce(char_length(session_id), 0) <= 100
  );

notify pgrst, 'reload schema';
```

확인:

```sql
-- AC1: 한 문장 안에서 비교한다(적재 중에도 같은 스냅숏). same = true, broken_rows = 0
select
  (select count(*) from public.beol_rag_chunks) as view_rows,
  (select count(*) from public.beol_chunk_embeddings e
     where public.beol_rag_is_complete(e.labels, e.slide_image_path, e.model)) as complete_rows,
  (select count(*) from public.beol_rag_chunks)
    = (select count(*) from public.beol_chunk_embeddings e
         where public.beol_rag_is_complete(e.labels, e.slide_image_path, e.model)) as same,
  (select count(*) from public.beol_rag_chunks c
     where c.slide_image_path is null
        or c.doc_meta is null
        or jsonb_typeof(c.doc_meta) = 'null'
        or jsonb_typeof(c.labels->'axes'->'Patterning/scheme') is distinct from 'array'
        or jsonb_array_length(case when jsonb_typeof(c.labels->'axes'->'Patterning/scheme') = 'array'
                                   then c.labels->'axes'->'Patterning/scheme' else '[]'::jsonb end) = 0) as broken_rows;

-- 권한 ①: beol_rag_chunks·beol_rag_facets는 SELECT만, beol_rag_feedback은 표 단위 권한 0행
select table_name, grantee, privilege_type
from information_schema.role_table_grants
where table_schema = 'public'
  and table_name like 'beol\_rag\_%' escape '\'
  and grantee in ('anon', 'authenticated')
order by table_name, grantee, privilege_type;

-- 권한 ①-2: beol_rag_feedback은 열 단위 INSERT만(id·created_at 없음, 6열 × 2역할 = 12행)
select grantee, column_name, privilege_type
from information_schema.column_privileges
where table_schema = 'public'
  and table_name = 'beol_rag_feedback'
  and grantee in ('anon', 'authenticated')
order by grantee, column_name;

-- 권한 ②: 기본 표는 0행(①의 like로는 나오지 않으므로 따로 묻는다)
select table_name, grantee, privilege_type
from information_schema.role_table_grants
where table_schema = 'public'
  and table_name = 'beol_chunk_embeddings'
  and grantee in ('anon', 'authenticated');

-- 열 점검: 0행
select table_name, column_name
from information_schema.columns
where table_schema = 'public'
  and table_name in ('beol_rag_chunks', 'beol_rag_facets')
  and column_name in ('file_name', 'embedding', 'name');
```
