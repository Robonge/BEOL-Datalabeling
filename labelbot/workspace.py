"""작업 폴더 경로, 코드 폴더 안 지정 거부, pipeline.json 설정, .env 읽기."""
import copy
import json
import os

from labelbot import util

CODE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DEFAULT_CONFIG = {
    "taxonomy_path": None,
    "input_root": None,
    "include_file_ids": [],
    "llm": {
        "transport": "http",
        "base_url": "https://api.openai.com/v1",
        "chat_path": "/chat/completions",
        "model": "",
        "api_key_env": "OPENAI_API_KEY",
        "auth_header": "Authorization",
        "extra_headers": {},
        "ca_file": None,
        "timeout": 60,
        "temperature": 0,
        "max_tokens": None,
        "max_tokens_param": "max_tokens",
        "response_format_json": False,
        "max_retries": 2,
        "workers": 4,
        "internal_host_suffixes": [],
    },
    "embedding": {
        "enabled": True,
        "transport": "http",
        "base_url": "https://api.openai.com/v1",
        "path": "/embeddings",
        "model": "text-embedding-3-small",
        "api_key_env": "OPENAI_API_KEY",
        "auth_header": "Authorization",
        "extra_headers": {},
        "ca_file": None,
        "timeout": 60,
        "batch_size": 64,
    },
    "supabase": {
        "enabled": False,
        "url": "",
        "url_env": "SUPABASE_URL",
        "table": "chunk_embeddings",
        "key_env": "SUPABASE_SERVICE_KEY",
        "batch_size": 100,
        "timeout": 60,
        "ca_file": None,
        # 슬라이드 JPG를 Storage에 올리고 행에 slide_image_* 열을 채운다(push-slides). 버킷은 private.
        "storage_enabled": False,
        "storage_bucket": "BEOL-labeling",
    },
    # 슬라이드 미리보기 JPG 렌더(slide-images). headless Edge/Chrome의 DevTools 캡처를 쓴다.
    "render": {"browser_path": None, "jpeg_quality": 85, "width_px": 1280, "timeout": 30},
    "flag": {"unknown_ratio_min": 0.5, "confidence_min": 0.7},
    "alerts": {"na_ratio_max": 0.30, "dup_ratio_min": 0.40},
    "limits": {
        "questions_per_chunk": 8,
        "images_per_chunk": 4,
        "chunk_char_limit": 6000,
        "query_k": 20,
    },
    "chunking": {"method": "slide"},
    "parse": {"image_min_bytes": 2048, "boilerplate_ratio": 0.6},
}


class WorkspaceError(Exception):
    pass


def load_env_file(path=None):
    """코드 폴더 루트 .env를 읽어 os.environ에 넣는다. 셸 값이 우선한다. 값은 출력하지 않는다."""
    path = path or os.path.join(CODE_ROOT, ".env")
    if not os.path.isfile(path):
        return []
    loaded = []
    with open(path, encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            if k.startswith("export "):
                k = k[7:].strip()
            v = v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                v = v[1:-1]
            if k and k not in os.environ and v:
                os.environ[k] = v
                loaded.append(k)
    return loaded


def _merge(base, over):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def _is_inside(child, parent):
    child = os.path.normcase(os.path.realpath(child))
    parent = os.path.normcase(os.path.realpath(parent))
    try:
        return os.path.commonpath([child, parent]) == parent
    except ValueError:
        return False


WORKSPACES_DIR = os.path.join(CODE_ROOT, "workspaces")


def is_forbidden_inside_code(path):
    """코드 폴더 안이면서 workspaces/ 밖이면 True. 작업 폴더는 workspaces/ 아래에만 둘 수 있다."""
    return _is_inside(path, CODE_ROOT) and not _is_inside(path, WORKSPACES_DIR)


class Workspace:
    SUBDIRS = ("inputs", "raw", "b64", "images", "slide_images", "screens", "inbox", "out", "reports", "logs")

    def __init__(self, root, create=True):
        if not root:
            raise WorkspaceError("WORKSPACE_REQUIRED")
        root = os.path.abspath(root)
        if is_forbidden_inside_code(root):
            raise WorkspaceError("WORKSPACE_INSIDE_CODE")
        self.root = root
        if create:
            os.makedirs(root, exist_ok=True)
            for d in self.SUBDIRS:
                os.makedirs(os.path.join(root, d), exist_ok=True)
        self.config = self._load_config()

    def path(self, *parts):
        return os.path.join(self.root, *parts)

    @property
    def work_db(self):
        return self.path("work.sqlite")

    @property
    def config_path(self):
        return self.path("pipeline.json")

    def _load_config(self):
        p = self.config_path
        user = {}
        if os.path.isfile(p):
            from labelbot.ingest import read_input

            user = json.loads(read_input(p, None, expect="text"))
        elif os.path.isdir(self.root):
            util.write_text(p, json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2) + "\n")
        return _merge(DEFAULT_CONFIG, user)

    @property
    def taxonomy_path(self):
        p = self.config.get("taxonomy_path")
        if p and not os.path.isabs(p):
            p = os.path.join(self.root, p)
        return p or self.path("taxonomy.xlsx")

    @property
    def input_root(self):
        p = self.config.get("input_root")
        if p and not os.path.isabs(p):
            p = os.path.join(self.root, p)
        return p or self.path("raw")

    def supabase_url(self):
        sb = self.config["supabase"]
        return sb.get("url") or os.environ.get(sb.get("url_env") or "", "")

    def config_hash(self):
        return util.hash_obj(self.config)
