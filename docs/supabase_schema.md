# Supabase 벡터 표 정의 (사외 PoC)

`push-vectors`가 쓰는 Supabase(Postgres + pgvector) 표다. 로컬 `work.sqlite`의 `chunk_embeddings`가 원본이고 이 표는 사본이다. `.sql` 파일은 허용 형식이 아니므로 SQL은 아래 코드 블록에 둔다. Supabase 대시보드의 SQL 편집기에 그대로 붙여넣어 실행할 수 있다.

- 표 이름은 `pipeline.json`의 `supabase.table`과 같아야 한다. PoC는 다른 앱과 같은 프로젝트를 쓰므로 `beol_chunk_embeddings`로 둔다.
- `vector(1536)`은 `text-embedding-3-small`의 차원이다. 임베딩 모델을 바꾸면 차원과 표를 함께 바꾼다.
- upsert 충돌 키는 `(chunk_id, model)`이다(`Prefer: resolution=merge-duplicates`, `on_conflict=chunk_id,model`).
- RLS를 켜고 정책을 두지 않는다. `service_role` 키로만 쓰고 읽는다. anon·authenticated 권한은 회수한다.
- 파일명과 경로 열은 두지 않는다.

```sql
create extension if not exists vector with schema extensions;

create table if not exists public.beol_chunk_embeddings (
  chunk_id   text        not null,
  model      text        not null,
  file_id    text        not null,
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
