#!/usr/bin/env python3
"""
Agent AI ringkas: Groq + terminal + edit fail + push ke GitHub.
Hanya guna Python standard (tiada pip install).

Guna:
  cd /laluan/projek-anda             # mesti repo git (git init / git clone)
  python3 agent.py

Kali pertama, ejen akan minta kunci Groq dan token GitHub (input tersembunyi)
dan tawarkan untuk simpan dalam ~/.agent_keys.json (kebenaran fail 600).
Pembolehubah env GROQ_API_KEY / GITHUB_TOKEN diutamakan jika ada.

Pilihan:
  --auto         jangan tanya kebenaran (BERISIKO)
  --model X      guna model tertentu (jika tiada, ejen senaraikan model
                 sebenar dari Groq dan anda pilih; pilihan disimpan)
  --reset-keys   padam kunci tersimpan dan minta semula
"""
import base64, getpass, json, os, re, subprocess, sys, time
import urllib.request, urllib.error

os.system("clear")
API = "https://api.groq.com/openai/v1/chat/completions"
MODEL_FILE = os.path.expanduser("~/.agent_model")
MODELS_URL = "https://api.groq.com/openai/v1/models"
UA = ("Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Mobile Safari/537.36")
AUTO = "--auto" in sys.argv
# Lalai: SEMUA projek ditolak ke satu repo tetap (sesuai token terhad kepada repo itu).
# --repo NAMA tukar repo tetap; --bebas = repo berasingan bagi setiap projek.
if "--bebas" in sys.argv:
    FIXED_REPO = None
elif "--repo" in sys.argv:
    FIXED_REPO = sys.argv[sys.argv.index("--repo") + 1]
else:
    FIXED_REPO = "Lele-2"
MODEL = None
if "--model" in sys.argv:
    MODEL = sys.argv[sys.argv.index("--model") + 1]
elif os.path.exists(MODEL_FILE):
    MODEL = open(MODEL_FILE, encoding="utf-8").read().strip() or None

ROOT = os.path.realpath(os.getcwd())
GH_API = os.environ.get("AGENT_GH_API", "https://api.github.com")
GH_GIT = os.environ.get("AGENT_GH_GIT", "https://github.com")
DEFAULT_OWNER = "lele59-png"  # digunakan jika GitHub tak dapat dihubungi
_OWNER = None
CONFIG = os.path.expanduser("~/.agent_keys.json")
KEY = None
GH_TOKEN = None

PUSH_RULE = (
    f"Simpan setiap projek dalam subfolder sendiri (contoh: calculator/index.html). "
    f"Semua projek ditolak ke SATU repo tetap ({FIXED_REPO}): panggil git_push "
    f"dengan mesej sahaja, JANGAN beri repo atau folder. "
    if FIXED_REPO else
    "Simpan setiap projek dalam subfolder sendiri bernama projek itu "
    "(contoh: calculator/index.html). Bila pengguna minta push projek X, panggil "
    "git_push dengan repo=X (nama ringkas, huruf kecil). Repo dicipta jika belum ada. ")

SYSTEM = f"""Kamu ejen pengaturcaraan. Direktori kerja: {ROOT}.
Guna tool untuk baca/tulis fail, jalankan arahan shell, dan push ke GitHub.
{PUSH_RULE}Jika workflow/Actions gagal, JANGAN minta
pengguna salin log: guna tool cek_actions untuk baca sendiri ralatnya.
Buat perubahan kecil dan jelas.
Jawab dalam Bahasa Melayu kecuali kod."""

TOOLS = [
    {"type": "function", "function": {
        "name": "run_shell", "description": "Jalankan arahan shell dalam direktori kerja.",
        "parameters": {"type": "object", "properties": {
            "command": {"type": "string"}}, "required": ["command"]}}},
    {"type": "function", "function": {
        "name": "read_file", "description": "Baca fail teks.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}}, "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "write_file", "description": "Tulis (ganti) fail teks.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"]}}},
    {"type": "function", "function": {
        "name": "cek_actions",
        "description": "Semak run GitHub Actions terbaru sesuatu repo dan paparkan "
                       "langkah serta mesej ralat jika gagal.",
        "parameters": {"type": "object", "properties": {
            "repo": {"type": "string", "description": "nama repo (lalai: origin folder semasa)"},
            "folder": {"type": "string", "description": "subfolder projek"}}}}},
    {"type": "function", "function": {
        "name": "git_push",
        "description": "git add -A, commit, dan push ke GitHub. Beri 'repo' untuk "
                       "tolak projek ke repo bernama itu (dicipta jika belum ada).",
        "parameters": {"type": "object", "properties": {
            "message": {"type": "string", "description": "mesej commit"},
            "repo": {"type": "string", "description": "nama repo GitHub, cth. calculator"},
            "folder": {"type": "string", "description": "subfolder projek (lalai: sama dengan repo)"},
            "branch": {"type": "string", "description": "lalai: main/cawangan semasa"},
            "pages": {"type": "boolean", "description": "auto-cipta workflow GitHub Pages untuk projek web (lalai: true)"}},
            "required": ["message"]}}},
]


def safe_path(p):
    full = os.path.realpath(os.path.join(ROOT, p))
    if full != ROOT and not full.startswith(ROOT + os.sep):
        raise ValueError("Laluan di luar direktori kerja ditolak.")
    return full


# Lalai: hanya PUSH (dan arahan berisiko) yang minta kebenaran.
ALLOW = set() if "--tanya" in sys.argv else {"shell", "tulis"}
DANGER = re.compile(
    r"(\brm\s+-\w*[rRfF]|\bgit\s+push\b|\bgit\s+reset\s+--hard|--force\b"
    r"|\bgit\s+clean\b|\bmkfs|\bdd\s+if=|\bsudo\b|\bchmod\s+-R|\bchown\s+-R"
    r"|>\s*/dev/|:\(\)\s*\{|\bcurl\b.*\|\s*(ba)?sh|\bwget\b.*\|\s*(ba)?sh)")


def confirm(what, kind="lain", remember=True):
    if AUTO or kind in ALLOW:
        return True
    opts = f"[y] sekali  [a] sentiasa ({kind})  [N] tolak" if remember else "[y] ya  [N] tolak"
    a = input(f"\n⚠ Benarkan?  {what}\n{opts} > ").strip().lower()
    if a == "a" and remember:
        ALLOW.add(kind)
        print(f"✔ '{kind}' dibenarkan sentiasa sehingga ejen ditutup.")
        return True
    return a == "y"


def sh(cmd, extra_env=None, timeout=120, cwd=None):
    env = {**os.environ, **(extra_env or {})}
    try:
        r = subprocess.run(cmd, shell=True, cwd=cwd or ROOT, capture_output=True,
                           text=True, timeout=timeout, env=env)
        out = (r.stdout + r.stderr).strip()
        return f"[exit {r.returncode}]\n{out[-6000:]}"
    except subprocess.TimeoutExpired:
        return "[timeout]"


def tool_run_shell(command):
    if DANGER.search(command):
        label = "push melalui shell" if "git push" in command else "arahan berisiko"
        if not confirm(f"{label}: {command}", "berisiko", remember=False):
            return "Ditolak oleh pengguna."
    elif not confirm(f"shell: {command}", "shell"):
        return "Ditolak oleh pengguna."
    return sh(command)


def tool_read_file(path):
    with open(safe_path(path), encoding="utf-8", errors="replace") as f:
        return f.read()[-12000:]


def tool_write_file(path, content):
    if not confirm(f"tulis fail: {path} ({len(content)} aksara)", "tulis"):
        return "Ditolak oleh pengguna."
    full = safe_path(path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        f.write(content)
    return f"Ditulis: {path}"


def gh_api(method, path, data=None):
    req = urllib.request.Request(
        GH_API + path, json.dumps(data).encode() if data is not None else None,
        {"Authorization": f"Bearer {GH_TOKEN}", "User-Agent": UA,
         "Accept": "application/vnd.github+json",
         "Content-Type": "application/json"}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.load(e)
        except Exception:
            return e.code, {}
    except (urllib.error.URLError, TimeoutError) as e:
        return 0, {"message": str(e)}


def gh_owner():
    """Nama pengguna GitHub pemilik token (cache)."""
    global _OWNER
    if not _OWNER:
        st, d = gh_api("GET", "/user")
        _OWNER = d.get("login") if st == 200 else None
    return _OWNER or DEFAULT_OWNER


PAGES_YML = """name: Deploy Pages
on:
  push:
    branches: [main]
  workflow_dispatch:
permissions:
  contents: read
  pages: write
  id-token: write
jobs:
  deploy:
    runs-on: ubuntu-latest
    environment:
      name: github-pages
      url: ${{ steps.d.outputs.page_url }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/configure-pages@v5
      - uses: actions/upload-pages-artifact@v3
        with:
          path: .
      - id: d
        uses: actions/deploy-pages@v4
"""


def find_sites(wd):
    """Folder (relatif) yang ada index.html: '' = akar, atau subfolder satu tahap."""
    found = []
    if os.path.isfile(os.path.join(wd, "index.html")):
        found.append("")
    try:
        for d in sorted(os.listdir(wd)):
            if not d.startswith(".") and os.path.isfile(os.path.join(wd, d, "index.html")):
                found.append(d)
    except OSError:
        pass
    return found


def ensure_workflow(wd):
    """Projek web tanpa workflow -> cipta pages.yml. True jika dicipta."""
    wf_dir = os.path.join(wd, ".github", "workflows")
    if not find_sites(wd):
        return False
    if os.path.isdir(wf_dir) and any(f.endswith((".yml", ".yaml")) for f in os.listdir(wf_dir)):
        return False
    os.makedirs(wf_dir, exist_ok=True)
    with open(os.path.join(wf_dir, "pages.yml"), "w", encoding="utf-8") as f:
        f.write(PAGES_YML)
    return True


def origin_slug(wd):
    r = sh("git remote get-url origin", cwd=wd)
    m = re.search(r"[:/]([^/:]+)/([^/]+?)(?:\.git)?\s*$", r.split("\n", 1)[-1])
    return (m.group(1), m.group(2)) if m else (None, None)


def enable_pages(owner, name):
    """Aktifkan GitHub Pages (sumber: GitHub Actions). Pulangkan (ok, mesej)."""
    st, d = gh_api("POST", f"/repos/{owner}/{name}/pages", {"build_type": "workflow"})
    if st in (200, 201, 409):
        return True, "Pages aktif"
    note = str(d.get("message", ""))[:90]
    if st in (403, 404):
        note += " (token tiada kebenaran 'Pages')"
    return False, f"Pages belum aktif ({st}): {note}"


def tool_git_push(message, repo=None, folder=None, branch=None, pages=True):
    if not ensure_token():
        return "❌ Token GitHub tiada. Taip /token untuk masukkan."
    owner = gh_owner()
    wd = ROOT
    if FIXED_REPO:  # repo tetap: abaikan repo/folder dari model
        repo, folder = FIXED_REPO, None
    if repo:
        repo = re.sub(r"[^A-Za-z0-9._-]", "-", repo.strip()).strip("-.")[:100]
        if not repo:
            return "❌ Nama repo tidak sah."
    sub = None if FIXED_REPO else (folder or repo)
    if sub and os.path.isdir(safe_path(sub)):
        wd = safe_path(sub)
    elif folder:
        return f"❌ Folder '{folder}' tiada."
    if repo and not os.path.isdir(os.path.join(wd, ".git")):
        sh("git init -b main", cwd=wd)
    elif not os.path.isdir(os.path.join(wd, ".git")):
        return "❌ Folder ini bukan repo git. Beri nama repo."

    is_new = False
    if repo:
        st, _ = gh_api("GET", f"/repos/{owner}/{repo}")
        if st == 404 and FIXED_REPO:
            return (f"❌ Repo {owner}/{repo} tak dijumpai atau token tiada akses.\n"
                    "→ Semak nama repo/token, atau jalankan dengan --bebas.")
        if st == 404:
            is_new = True
        elif st != 200:
            return f"❌ Tak dapat semak repo ({st}). Semak token/rangkaian."
    elif not sh("git remote get-url origin", cwd=wd).startswith("[exit 0]"):
        return "❌ Tiada remote origin. Beri nama repo."

    if not branch:
        # symbolic-ref berfungsi walaupun belum ada commit (rev-parse gagal)
        r = subprocess.run("git symbolic-ref --short HEAD", shell=True, cwd=wd,
                           capture_output=True, text=True)
        branch = r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else "main"
    if not subprocess.run("git config user.email", shell=True, cwd=wd,
                          capture_output=True, text=True).stdout.strip():
        sh(f'git config user.name "{owner}"', cwd=wd)
        sh(f'git config user.email "{owner}@users.noreply.github.com"', cwd=wd)

    wf_created = ensure_workflow(wd) if pages else False

    # --- satu-satunya kebenaran: PUSH (termasuk cipta repo baharu jika perlu)
    status = sh("git status --short", cwd=wd)
    target = f"{owner}/{repo}" if repo else "origin"
    if is_new:
        target += "  (repo BAHARU akan dicipta)"
    if wf_created:
        target += "\n  + fail .github/workflows/pages.yml (auto)"
    if not confirm(f"PUSH ke {target}\n  folder: {os.path.relpath(wd, ROOT)}  "
                   f"cawangan: {branch}\n  mesej: {message}\n{status}", "push"):
        return "Ditolak oleh pengguna."

    if is_new:
        private = True
        if not AUTO:
            private = input("Repo awam (a) atau peribadi (p)? [p] > ").strip().lower() != "a"
        st, d = gh_api("POST", "/user/repos", {"name": repo, "private": private})
        if st not in (200, 201):
            return (f"❌ Gagal cipta repo ({st}): {str(d.get('message', ''))[:120]}\n"
                    "→ Token perlu skop 'repo' (classic) atau akses semua repo.")
    if repo:
        url = f"{GH_GIT}/{owner}/{repo}.git"
        if sh("git remote get-url origin", cwd=wd).startswith("[exit 0]"):
            sh(f"git remote set-url origin {url}", cwd=wd)
        else:
            sh(f"git remote add origin {url}", cwd=wd)

    has_wf = pages and os.path.isfile(os.path.join(wd, ".github", "workflows", "pages.yml"))
    p_owner, p_name = (owner, repo) if repo else origin_slug(wd)
    pages_ok, pages_msg = (False, "")
    if has_wf and p_name:
        pages_ok, pages_msg = enable_pages(p_owner, p_name)

    auth = base64.b64encode(f"x-access-token:{GH_TOKEN}".encode()).decode()
    git = f'git -c http.extraHeader="Authorization: Basic {auth}" '
    log = [sh("git add -A", cwd=wd), sh("git commit -m " + json.dumps(message), cwd=wd)]
    out = sh(git + f"push -u origin {branch}", cwd=wd)
    if any(k in out for k in ("rejected", "fetch first", "non-fast-forward")):
        log.append("Repo jauh ada kandungan lain, cuba gabung (pull)...")
        log.append(sh(git + f"pull origin {branch} --allow-unrelated-histories "
                            "--no-rebase --no-edit", cwd=wd))
        out = sh(git + f"push -u origin {branch}", cwd=wd)
    log.append(out)
    text = "\n---\n".join(log).replace(auth, "***").replace(GH_TOKEN, "***")
    if "[exit 0]" in out:
        link = f"https://github.com/{owner}/{repo}" if repo else ""
        extra = ""
        if has_wf and p_name:
            if not pages_ok:  # cuba semula selepas ada kandungan dalam repo
                pages_ok, pages_msg = enable_pages(p_owner, p_name)
            if pages_ok:
                base = f"https://{p_owner}.github.io/{p_name}/"
                urls = [base + (d + "/" if d else "") for d in find_sites(wd)[:4]]
                extra = ("\n🌐 Laman (siap ~1 minit, lihat tab Actions):\n   "
                         + "\n   ".join(urls))
            else:
                extra = (f"\n⚠ {pages_msg}\n   → Repo mesti AWAM. Aktifkan sekali sahaja: "
                         "Settings → Pages → Source: GitHub Actions.")
        return f"✅ Push berjaya. {link}{extra}\n" + text
    hint = ""
    if "workflow" in out and ("refusing" in out or "scope" in out):
        hint = "→ Token perlu kebenaran 'workflow' (classic: tanda skop workflow).\n"
    elif any(k in out for k in ("Authentication failed", "403", "Permission", "denied")):
        hint = "→ Token salah atau tiada kebenaran. Taip /token untuk tukar.\n"
    return "❌ Push gagal.\n" + hint + text


def resolve_slug(repo=None, folder=None):
    """(owner, nama) daripada nama repo yang diberi, atau origin folder."""
    repo = repo or FIXED_REPO
    if repo:
        name = re.sub(r"[^A-Za-z0-9._-]", "-", repo.strip()).strip("-.")[:100]
        return gh_owner(), name
    wd = safe_path(folder) if folder else ROOT
    return origin_slug(wd)


def tool_cek_actions(repo=None, folder=None):
    if not ensure_token():
        return "❌ Token GitHub tiada. Taip /token untuk masukkan."
    owner, name = resolve_slug(repo, folder)
    if not name:
        return "❌ Beri nama repo."
    st, d = gh_api("GET", f"/repos/{owner}/{name}/actions/runs?per_page=1")
    if st != 200:
        tip = " → Token perlu kebenaran 'Actions: Read'." if st in (403, 404) else ""
        return f"❌ Tak dapat baca Actions {owner}/{name} ({st}).{tip}"
    runs = d.get("workflow_runs", [])
    if not runs:
        return f"Tiada run di {owner}/{name}. Belum ada workflow atau belum dicetus."
    r = runs[0]
    lines = [f"{r.get('name')}: {r.get('status')} / {r.get('conclusion') or '-'}",
             str(r.get("html_url", ""))]
    if r.get("conclusion") != "failure":
        return "\n".join(lines)
    st, j = gh_api("GET", f"/repos/{owner}/{name}/actions/runs/{r['id']}/jobs")
    for job in (j.get("jobs", []) if st == 200 else []):
        if job.get("conclusion") != "failure":
            continue
        bad = [x["name"] for x in job.get("steps", []) if x.get("conclusion") == "failure"]
        lines.append(f"❌ Job '{job.get('name')}' gagal di langkah: {', '.join(bad) or '?'}")
        cr = str(job.get("check_run_url", ""))
        if cr:
            st2, ann = gh_api("GET", cr.replace(GH_API, "") + "/annotations")
            for a_ in (ann if st2 == 200 and isinstance(ann, list) else []):
                if a_.get("annotation_level") == "failure":
                    lines.append("   " + " ".join(str(a_.get("message", "")).split())[:160])
    text = "\n".join(lines)
    if "Not Found" in text:
        text += ("\n→ Biasanya Pages belum aktif atau repo peribadi. "
                 "Taip /pages untuk aktifkan & semak.")
    return text


def tool_pages(repo=None, folder=None):
    """Semak keterlihatan repo dan aktifkan GitHub Pages."""
    if not ensure_token():
        return "❌ Token GitHub tiada. Taip /token untuk masukkan."
    owner, name = resolve_slug(repo, folder)
    if not name:
        return "❌ Beri nama repo."
    st, d = gh_api("GET", f"/repos/{owner}/{name}")
    if st != 200:
        return f"❌ Repo {owner}/{name} tak dapat dibaca ({st})."
    vis = "peribadi" if d.get("private") else "awam"
    ok, msg = enable_pages(owner, name)
    out = f"Repo {owner}/{name} ({vis}). {msg}"
    if ok:
        out += f"\n🌐 https://{owner}.github.io/{name}/  (jalankan semula workflow di tab Actions)"
    elif vis == "peribadi":
        out += "\n→ Pages percuma perlukan repo AWAM (Settings → General → Danger Zone → Change visibility)."
    return out


FUNCS = {"cek_actions": tool_cek_actions, "run_shell": tool_run_shell, "read_file": tool_read_file,
         "write_file": tool_write_file, "git_push": tool_git_push}


HINTS = {401: "Kunci Groq salah/luput. Jalankan: python3 agent.py --reset-keys",
         403: "Disekat (cuba matikan VPN).",
         404: "Model/URL tidak wujud. Taip /model.",
         413: "Terlalu besar. Mulakan semula sesi.",
         429: "Had kadar. Tunggu seminit atau /model.",
         400: "Permintaan ditolak. Cuba /model atau arahan lebih ringkas."}


def short_err(code, raw):
    """Ringkaskan ralat API kepada satu baris."""
    try:
        msg = json.loads(raw)["error"]["message"]
    except Exception:
        msg = raw
    msg = " ".join(str(msg).split())[:140]
    hint = HINTS.get(code, "")
    return f"❌ Ralat {code}: {msg}" + (f"\n   → {hint}" if hint else "")


def wait_seconds(err):
    """Baca 'try again in 1m2.5s' / '18.36s' / '300ms' dari mesej Groq."""
    m = re.search(r"try again in ((?:[\d.]+(?:ms|m|s))+)", err)
    if not m:
        return 20
    total = 0.0
    for num, unit in re.findall(r"([\d.]+)(ms|m|s)", m.group(1)):
        total += float(num) * {"ms": 0.001, "s": 1, "m": 60}[unit]
    return min(total + 1, 90)


def chat(messages):
    """Hantar ke Groq. Cuba semula jika kena had kadar (429) / ralat server."""
    body = json.dumps({"model": MODEL, "messages": messages, "tools": TOOLS,
                       "tool_choice": "auto", "temperature": 0.2}).encode()
    for attempt in range(6):
        req = urllib.request.Request(API, body, {
            "Content-Type": "application/json",
            "Accept": "application/json",
            # Cloudflare (Groq) menyekat UA lalai "Python-urllib" -> ralat 1010
            "User-Agent": UA,
            "Authorization": f"Bearer {KEY}"})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.load(r)["choices"][0]["message"]
        except urllib.error.HTTPError as e:
            err = e.read().decode()
            if e.code in (400, 404) and "model" in err and (
                    "not_found" in err or "decommissioned" in err):
                print(f"\nModel '{MODEL}' tidak tersedia. Pilih model lain.")
                choose_model()
                body = json.dumps({"model": MODEL, "messages": messages,
                                   "tools": TOOLS, "tool_choice": "auto",
                                   "temperature": 0.2}).encode()
                continue
            if e.code in (429, 500, 502, 503) and attempt < 5:
                w = wait_seconds(err) if e.code == 429 else 5
                print(f"\n⏳ Ralat {e.code}, tunggu {w:.0f}s "
                      f"({attempt + 1}/5)...")
                time.sleep(w)
                continue
            print("\n" + short_err(e.code, err))
            return None
        except (urllib.error.URLError, TimeoutError) as e:
            print(f"\n❌ Ralat rangkaian: {str(e)[:100]}\n   → Semak internet/VPN.")
            return None
    return None


SECRET_RE = re.compile(r"(github_pat_[A-Za-z0-9_]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|gsk_[A-Za-z0-9]{20,})")


def redact(text):
    """Sembunyikan kunci/token supaya tak pernah sampai ke model."""
    for secret in (KEY, GH_TOKEN):
        if secret:
            text = text.replace(secret, "***")
    return SECRET_RE.sub("***", str(text))


def run_turn(messages):
    written = set()  # elak model tulis fail sama berulang kali
    for _ in range(15):  # had langkah untuk elak gelung tanpa henti
        msg = chat(messages)
        if msg is None:
            return
        messages.append({k: v for k, v in msg.items() if v is not None})
        calls = msg.get("tool_calls")
        if not calls:
            print("\n" + (msg.get("content") or ""))
            return
        for c in calls:
            name = c["function"]["name"]
            if name == "write_file":
                key = c["function"]["arguments"]
                if key in written:
                    print("\n↺ write_file sama diulang, dilangkau.")
                    messages.append({"role": "tool", "tool_call_id": c["id"],
                                     "content": "Fail ini SUDAH ditulis dengan isi sama. "
                                                "Jangan tulis semula. Teruskan: fail lain "
                                                "yang belum ada, atau git_push."})
                    continue
                written.add(key)
            try:
                args = json.loads(c["function"]["arguments"] or "{}")
                print(f"\n→ {name} {json.dumps(args, ensure_ascii=False)[:200]}")
                result = FUNCS[name](**args)
            except Exception as e:
                result = f"Ralat: {type(e).__name__}: {e}"
                print(f"\n❌ {name} gagal: {type(e).__name__}: {str(e)[:120]}")
            else:
                print(result[:800])
            messages.append({"role": "tool", "tool_call_id": c["id"],
                             "content": redact(result)})
    print("\n(Berhenti: had 15 langkah dicapai.)")


SKIP = ("whisper", "tts", "guard", "orpheus", "playai", "embed", "safeguard")


def list_models():
    req = urllib.request.Request(MODELS_URL, headers={
        "Authorization": f"Bearer {KEY}", "User-Agent": UA,
        "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.load(r)["data"]
    return sorted(m["id"] for m in data
                  if m.get("active", True)
                  and not any(k in m["id"].lower() for k in SKIP))


def choose_model():
    """Ambil senarai model sebenar dari Groq dan biar pengguna pilih."""
    global MODEL
    try:
        ids = list_models()
    except Exception as e:
        sys.exit(f"Tak dapat ambil senarai model: {e}")
    if not ids:
        sys.exit("Tiada model ditemui untuk kunci ini.")
    print("\nModel tersedia:")
    for i, m in enumerate(ids, 1):
        print(f"  {i}. {m}")
    while True:
        c = input("Pilih nombor model > ").strip()
        if c.isdigit() and 1 <= int(c) <= len(ids):
            MODEL = ids[int(c) - 1]
            break
    with open(MODEL_FILE, "w", encoding="utf-8") as f:
        f.write(MODEL)
    print(f"Model dipilih: {MODEL}")


def ask_secret(label, prefix_hint, required):
    while True:
        v = getpass.getpass(f"Masukkan {label} ({prefix_hint})"
                            f"{'' if required else ', Enter untuk langkau'}: ").strip()
        if v or not required:
            return v
        print("Wajib diisi.")


def save_keys():
    fd = os.open(CONFIG, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"groq": KEY, "github": GH_TOKEN}, f)
    os.chmod(CONFIG, 0o600)
    print(f"✔ Disimpan di {CONFIG}")


def ensure_token(force=False):
    """Pastikan ada token GitHub; jika tiada, minta terus (input tersembunyi)."""
    global GH_TOKEN, _OWNER
    if GH_TOKEN and not force:
        return True
    print("\n🔑 Token GitHub diperlukan untuk push.")
    print("   Cipta di github.com/settings/tokens (classic, skop: repo + workflow)")
    t = ask_secret("token GitHub", "ghp_... atau github_pat_...", False)
    if not t:
        return False
    old_tok, GH_TOKEN, _OWNER = GH_TOKEN, t, None
    st, d = gh_api("GET", "/user")
    if st == 401:
        print("❌ Token ditolak GitHub (salah/luput).")
        GH_TOKEN = old_tok
        return False
    if st == 200:
        print(f"✔ Log masuk sebagai {d.get('login')}")
    if input("Simpan token supaya tak ditanya lagi? [Y/n] > ").strip().lower() != "n":
        save_keys()
    return True


def load_keys():
    """Urutan: env -> fail simpanan -> tanya pengguna."""
    global KEY, GH_TOKEN
    if "--reset-keys" in sys.argv and os.path.exists(CONFIG):
        os.remove(CONFIG)
        print("Kunci tersimpan dipadam.")
    saved = {}
    if os.path.exists(CONFIG):
        try:
            with open(CONFIG, encoding="utf-8") as f:
                saved = json.load(f)
        except (OSError, ValueError):
            saved = {}
    KEY = os.environ.get("GROQ_API_KEY") or saved.get("groq")
    GH_TOKEN = os.environ.get("GITHUB_TOKEN") or saved.get("github")

    asked = False
    if not KEY:
        KEY = ask_secret("kunci API Groq", "bermula gsk_", True)
        asked = True
    if not GH_TOKEN:
        GH_TOKEN = ask_secret("token GitHub", "github_pat_... atau ghp_...", False)
        asked = True

    if asked and input("Simpan kunci dalam ~/.agent_keys.json? [y/N] > ").strip().lower() == "y":
        save_keys()


def banner():
    home = os.path.expanduser("~")
    folder = ROOT.replace(home, "~", 1) if ROOT.startswith(home) else ROOT
    line = "─" * 34
    print(f"\n{line}\n 🤖 Agent AI + GitHub\n{line}")
    print(f" Model  : {MODEL}")
    print(f" Folder : {folder}")
    print(f" GitHub : {'sedia' if GH_TOKEN else 'tiada token (diminta bila push)'}")
    print(f" Repo   : {FIXED_REPO + ' (tetap)' if FIXED_REPO else 'ikut projek (--bebas)'}")
    print(f" Izin   : {'semua auto (--auto)' if AUTO else 'tanya hanya untuk PUSH' if 'shell' in ALLOW else 'tanya semua (--tanya)'}")
    help_text()


def help_text():
    print("\n Arahan")
    if FIXED_REPO:
        print(f"  /push [mesej]         tolak ke {FIXED_REPO}")
    else:
        print("  /push <repo> [mesej]  tolak projek ke repo")
        print("  /push                 tolak folder semasa")
    print("  /actions [repo]       semak Actions & ralatnya")
    print("  /pages [repo]         aktifkan/semak GitHub Pages")
    print("  /model                tukar model")
    print("  /token                masukkan/tukar token GitHub")
    print("  /help                 papar bantuan")
    print("  exit                  keluar")
    print("\n Contoh")
    print("  buat calculator dan push")
    print("  /push calculator siap" if not FIXED_REPO else "  /push kalkulator siap")
    print("─" * 34)


def main():
    load_keys()
    if not MODEL:
        choose_model()
    banner()
    messages = [{"role": "system", "content": SYSTEM}]
    while True:
        try:
            q = input("\nanda> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if q in ("exit", "quit"):
            break
        if q == "/model":
            choose_model()
            continue
        if q.startswith(("/actions", "/pages")):
            parts = q.split(None, 1)
            fn = tool_cek_actions if parts[0] == "/actions" else tool_pages
            print(fn(repo=parts[1] if len(parts) > 1 else None))
            continue
        if q == "/token":
            ensure_token(force=True)
            continue
        if q in ("/help", "/?"):
            help_text()
            continue
        if q.startswith("/push"):
            if FIXED_REPO:  # /push [mesej]
                msg = q[5:].strip() or "update"
                res = tool_git_push(msg)
            else:           # /push [repo] [mesej]
                parts = q.split(None, 2)
                repo = parts[1] if len(parts) > 1 else None
                msg = parts[2] if len(parts) > 2 else "update"
                res = tool_git_push(msg, repo=repo)
            print(res if res.startswith("❌") or "gagal" in res.split("\n")[0]
                  else res.split("\n")[0])
            continue
        if SECRET_RE.search(q) or (GH_TOKEN and GH_TOKEN in q) or (KEY and KEY in q):
            print("🔒 Mesej mengandungi kunci/token, TIDAK dihantar.")
            print("   Jangan taip kunci di sini. Guna: python3 agent.py --reset-keys")
            continue
        if q:
            messages.append({"role": "user", "content": q})
            run_turn(messages)


if __name__ == "__main__":
    main()
