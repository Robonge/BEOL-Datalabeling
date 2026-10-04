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
