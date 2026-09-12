# -*- coding: utf-8 -*-
"""
美股因子策略 —— Windows 一键菜单
=================================
由 一键运行.bat 双击调用（也可命令行 python _menu.py）。

菜单:
  1. 每日实盘信号更新   检查/启动 Futu OpenD -> 跑 _update_signal.py -> 显示选股快照
  2. 完整回测重跑       $3000 与 $1500 两档全量（含 AI），可选 --fast 跳过 AI
  3. 推送 GitHub        显式 add -> 中文提交 -> push -> API 回读校验
  4. 一键自检           _update_signal.py --self-test（98 项）
  5. 查看最新选股快照
  0. 退出

设计铁律（与项目纪律一致）:
  - 推送时绝不 git add -A；只提交用户确认过的显式文件清单
  - 提交信息一律先落盘成 .txt 再 commit -F（Bash 内联会吞掉 $，本机不吃这个亏）
  - git 不在 PATH，必须显式给路径 + GIT_EXEC_PATH
  - 推送用 origin HEAD:main（本机 remote-tracking 引用建不起来，-u/租约会报 stale info）
"""

import os
import sys
import json
import time
import socket
import subprocess

# ==================== 路径与常量 ====================
BASE = os.path.dirname(os.path.abspath(__file__))
PY = r"C:\Users\sailor\AppData\Local\Programs\Python\Python312\python.exe"
GIT = r"C:\Users\sailor\.workbuddy\binaries\PortableGit\versions\1.2.0\cmd\git.exe"
GIT_EXEC = r"C:\Users\sailor\.workbuddy\binaries\PortableGit\versions\1.2.0\mingw64\libexec\git-core"
OPEND_LNK = r"C:\Users\sailor\Desktop\Futu OpenD.lnk"
OPEND_HOST, OPEND_PORT = "127.0.0.1", 11111
PROXY = "127.0.0.1:10809"
GIT_REMOTE = "https://github.com/SailorChina/us-stock-factor-backtest"

# 永远不提交的临时产物（前缀/后缀匹配）
NEVER_PREFIX = ("_gen_", "_analyze", "_push_", "_gh_", "_commitmsg", "_tmp", "_menu_out")
NEVER_EXACT = {"portfolio.json", "_gen_compare_out.txt"}

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


# ==================== 基础工具 ====================
def hr(title=""):
    print("\n" + "=" * 78)
    if title:
        print("  " + title)
        print("=" * 78)


def git_env():
    e = dict(os.environ)
    e.update({
        "GIT_EXEC_PATH": GIT_EXEC,
        "GIT_TERMINAL_PROMPT": "0",
        "GCM_INTERACTIVE": "never",
        "PATH": os.path.dirname(GIT) + os.pathsep + os.environ.get("PATH", ""),
        "PYTHONIOENCODING": "utf-8",
    })
    return e


def git(args, timeout=300, capture=True):
    """执行 git。capture=True 返回 (rc, out, err)；否则输出直通控制台。"""
    cmd = [GIT] + list(args)
    if capture:
        r = subprocess.run(cmd, cwd=BASE, env=git_env(), capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    r = subprocess.run(cmd, cwd=BASE, env=git_env(), timeout=timeout)
    return r.returncode, "", ""


def pyrun(script, args=None, timeout=None, capture=False):
    cmd = [PY, os.path.join(BASE, script)] + list(args or [])
    print("\n$ " + " ".join(f'"{c}"' if " " in c else c for c in cmd))
    t0 = time.time()
    try:
        if capture:
            r = subprocess.run(cmd, cwd=BASE, capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=timeout)
            return r.returncode, r.stdout, r.stderr
        rc = subprocess.run(cmd, cwd=BASE, timeout=timeout).returncode
        return rc, "", ""
    except subprocess.TimeoutExpired:
        print(f"  超时（>{timeout}s），已中止。")
        return -1, "", "timeout"
    finally:
        print(f"  [耗时 {time.time() - t0:.1f}s]")


def ask(prompt, default=""):
    try:
        s = input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        return default
    return s or default


def port_open(host, port, timeout=0.6):
    s = socket.socket()
    s.settimeout(timeout)
    try:
        s.connect((host, port))
        return True
    except OSError:
        return False
    finally:
        s.close()


# ==================== 1. 每日实盘信号更新 ====================
def ensure_opend(wait=120):
    """检查 Futu OpenD 端口；未就绪则用桌面快捷方式启动并等待。"""
    if port_open(OPEND_HOST, OPEND_PORT):
        print(f"  Futu OpenD 已在 {OPEND_PORT} 端口就绪。")
        return True
    print(f"  端口 {OPEND_PORT} 未就绪 —— 正在启动 Futu OpenD ...")
    if not os.path.exists(OPEND_LNK):
        print(f"  ❌ 找不到快捷方式: {OPEND_LNK}")
        print("     请手动启动 OpenD 后再重试。")
        return False
    try:
        os.startfile(OPEND_LNK)          # Windows: 用关联程序打开 .lnk
    except Exception as ex:
        print(f"  ❌ 启动失败: {ex}")
        return False
    for k in range(wait // 3):
        time.sleep(3)
        if port_open(OPEND_HOST, OPEND_PORT):
            print(f"  ✅ OpenD 已就绪（等待 {(k + 1) * 3}s）。")
            return True
    print(f"  ❌ 等待 {wait}s 后端口仍未就绪。请检查 OpenD 是否登录。")
    return False


def update_signal():
    hr("1. 每日实盘信号更新")
    print("  默认口径：Vortex Top2；闸门 $5M 开启。")
    print("  [1] 10 日调仓（v26/v34 风险调整冠军，推荐）")
    print("  [2] 21 日调仓（月频，生产默认值）")
    rb = ask("  选择调仓周期 [1]: ", "1")
    rebal = "10" if rb != "2" else "21"

    print("  [1] $1,500   [2] $3,000   [3] 默认（¥10,000 / 汇率 ≈ $1,490）")
    cp = ask("  选择本金 [1]: ", "1")
    cap_args = {"1": ["--capital", "1500"], "2": ["--capital", "3000"], "3": []}[cp if cp in "123" else "1"]

    if not ensure_opend():
        return
    rc, _, _ = pyrun("_update_signal.py", ["--rebal", rebal] + cap_args, timeout=900)
    if rc == 0:
        print("\n  ✅ 信号更新完成。")
        show_snapshot()
    else:
        print(f"\n  ❌ 信号更新失败（rc={rc}）。")


# ==================== 2. 完整回测重跑 ====================
def rerun_backtest():
    hr("2. 完整回测重跑")
    print("  两档本金各跑一遍全策略排名（69 策略 + 3 基准）。")
    print("  [1] --fast 跳过 AI 家族（约 1 分钟，AI 全在榜尾，不影响冠军判定）")
    print("  [2] 全量含 AI（约 15 分钟）")
    m = ask("  选择 [1]: ", "1")
    extra = ["--fast"] if m != "2" else []

    for script, cap in (("_rank_all_strategies.py", 3000), ("_rank_all_1500.py", 1500)):
        p = os.path.join(BASE, script)
        if not os.path.exists(p):
            print(f"  ⚠ 跳过 {script}（文件不存在）")
            continue
        hr(f"本金 ${cap:,} —— {script}")
        rc, _, _ = pyrun(script, extra, timeout=None)
        print(f"  {'✅' if rc == 0 else '❌'} {script} rc={rc}")
    print("\n  结果：_rank_all.json / _rank_all_1500.json（可用菜单 3 推送）")


# ==================== 3. 推送 GitHub ====================
def gh_token():
    """从 Windows 凭据管理器读 PAT。blob 是 UTF-16LE，用 utf-8 解会得到乱码。"""
    try:
        import ctypes
        import ctypes.wintypes as wt

        class CRED(ctypes.Structure):
            _fields_ = [("Flags", wt.DWORD), ("Type", wt.DWORD), ("TargetName", wt.LPWSTR),
                        ("Comment", wt.LPWSTR), ("LastWritten", wt.FILETIME),
                        ("CredentialBlobSize", wt.DWORD), ("CredentialBlob", ctypes.POINTER(ctypes.c_char)),
                        ("Persist", wt.DWORD), ("AttributeCount", wt.DWORD), ("Attributes", ctypes.c_void_p),
                        ("TargetAlias", wt.LPWSTR), ("UserName", wt.LPWSTR)]

        adv = ctypes.windll.advapi32
        adv.CredReadW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, ctypes.POINTER(ctypes.POINTER(CRED))]
        adv.CredReadW.restype = wt.BOOL
        p = ctypes.POINTER(CRED)()
        if not adv.CredReadW("git:https://github.com", 1, 0, ctypes.byref(p)):
            return None
        c = p.contents
        raw = ctypes.string_at(c.CredentialBlob, c.CredentialBlobSize)
        adv.CredFree(p)
        return raw.decode("utf-16-le").strip().rstrip("\x00")
    except Exception:
        return None


def api_get(url, token, tries=4):
    import urllib.request
    op = urllib.request.build_opener(urllib.request.ProxyHandler({"http": PROXY, "https": PROXY}))
    op.addheaders = [("User-Agent", "menu-verify"), ("Authorization", "token " + token),
                     ("Accept", "application/vnd.github+json")]
    last = None
    for _ in range(tries):
        try:
            with op.open(url, timeout=90) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as ex:          # 大响应走代理会 IncompleteRead，重试即可
            last = ex
            time.sleep(1.5)
    raise last


def readback():
    """推送后回读远端目录校验（失败则退化为 ls-remote 比 SHA）。"""
    tok = gh_token()
    if not tok:
        print("  ⚠ 读不到凭据管理器里的 PAT，退化为 ls-remote 比 SHA。")
        rc, o, e = git(["ls-remote", "origin", "HEAD"], timeout=90)
        rc2, o2, _ = git(["rev-parse", "HEAD"])
        ok = rc == 0 and rc2 == 0 and o.split()[0] == o2.strip()
        print(f"  远端 {o.split()[0][:12] if o else '?'} / 本地 {o2.strip()[:12]}"
              f"  -> {'✅ 一致' if ok else '❌ 不一致'}")
        return ok
    try:
        repo = "SailorChina/us-stock-factor-backtest"
        d = api_get(f"https://api.github.com/repos/{repo}/git/trees/main?recursive=1", tok)
        names = [t["path"] for t in d.get("tree", []) if t["type"] == "blob"]
        c = api_get(f"https://api.github.com/repos/{repo}/commits/main", tok)
        # 只校验【本次提交碰到的文件】—— 全仓库扫描会把历史遗留文件误报成"脏"
        # （例如 v26 就提交的 _gen_report_v26.py 会被 _gen_ 前缀命中，但它不是本次产物）
        touched = [f["filename"] for f in c.get("files", [])]
        bad = [n for n in touched
               if n.endswith(".log") or n.startswith(NEVER_PREFIX) or n in NEVER_EXACT]
        print(f"  远端文件总数 {len(names)} | 最新 commit {c['sha'][:12]} | 本次变更 {len(touched)} 个")
        print(f"  本次变更含临时/日志文件: {bad or 'NONE'}")
        print(f"  {GIT_REMOTE}/commit/{c['sha'][:12]}")
        return not bad
    except Exception as ex:
        print(f"  ⚠ API 回读失败（{type(ex).__name__}），请用浏览器确认：{GIT_REMOTE}")
        return True


def push_github():
    hr("3. 推送 GitHub")

    # --- 收集候选文件 ---
    rc, out, err = git(["status", "--short"])
    if rc != 0:
        print("  ❌ git status 失败：", err.strip()[:200])
        return
    cands, skipped = [], []
    for line in out.splitlines():
        if not line.strip():
            continue
        st, path = line[:2], line[3:].strip()
        path = path.strip('"')
        if any(path.startswith(p) for p in NEVER_PREFIX) or path in NEVER_EXACT or path.endswith(".log"):
            skipped.append(path)
            continue
        cands.append((st.strip(), path))

    if not cands:
        print("  没有需要提交的改动（临时文件已按规则排除）。")
        if skipped:
            print("  已排除：", ", ".join(skipped[:10]))
        return

    print("  候选文件：")
    for i, (st, p) in enumerate(cands, 1):
        tag = "已跟踪-修改" if st == "M" else ("新增" if st in ("A", "??") else st)
        print(f"    {i:>2}. [{tag}] {p}")
    if skipped:
        print("  已排除（临时产物）：", ", ".join(skipped[:10]))

    sel = ask("\n  提交全部输入 y；逐个选择请输入序号（空格分隔）；取消直接回车: ")
    if not sel:
        print("  已取消。")
        return
    if sel.lower() == "y":
        chosen = [p for _, p in cands]
    else:
        idx = []
        for t in sel.replace(",", " ").split():
            if t.isdigit() and 1 <= int(t) <= len(cands):
                idx.append(int(t) - 1)
        if not idx:
            print("  没有有效序号，已取消。")
            return
        chosen = [cands[i][1] for i in idx]

    # --- 提交信息：必须落盘再 -F（Bash 内联会吞 $，这里也统一走文件） ---
    print("\n  提交信息标题（一行，必填）:")
    title = ask("  > ")
    if not title:
        print("  标题为空，已取消。")
        return
    print("  正文补充（可留空，回车结束；输入 . 结束多行）:")
    body_lines = []
    while True:
        b = ask("  > ")
        if b in ("", "."):
            break
        body_lines.append(b)
    body = "\n".join(body_lines)
    body += ("\n\n本次提交文件:\n" + "\n".join("  - " + p for p in chosen)) if body else \
            "本次提交文件:\n" + "\n".join("  - " + p for p in chosen)

    msg_path = os.path.join(BASE, "_commitmsg_menu.txt")
    with open(msg_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(title + "\n\n" + body + "\n")

    rc, o, e = git(["add"] + chosen)
    print("  git add:", "OK" if rc == 0 else "FAIL", e.strip()[:200])
    if rc != 0:
        return

    # 提交前再看一眼暂存区，防止误带
    rc, staged, _ = git(["diff", "--cached", "--name-only"])
    staged = [x for x in staged.splitlines() if x.strip()]
    print(f"  暂存区 {len(staged)} 个文件，确认提交？")
    if ask("  输入 y 提交: ").lower() != "y":
        git(["reset"])           # 取消暂存，文件改动保留
        print("  已取消并撤销暂存（改动仍在磁盘上）。")
        return

    rc, o, e = git(["commit", "-F", "_commitmsg_menu.txt"])
    print((o or e).strip()[:500])
    if rc != 0:
        return

    rc, o, e = git(["push", "origin", "HEAD:main"], timeout=300)
    print((o or e).strip()[:500])
    if rc != 0:
        print("  ❌ 推送失败。若提示 stale info，说明远端被推进过 —— 先到浏览器确认再处理。")
        return
    print("  ✅ 推送完成，开始回读校验 ...")
    ok = readback()
    print("  " + ("✅ 校验通过" if ok else "⚠ 校验发现问题，请人工确认"))

    try:
        os.remove(msg_path)
    except OSError:
        pass


# ==================== 4. 一键自检 ====================
def self_test():
    hr("4. 一键自检（_update_signal.py --self-test）")
    rc, _, _ = pyrun("_update_signal.py", ["--self-test"], timeout=900)
    print("  " + ("✅ 全部通过" if rc == 0 else f"❌ 有失败项（rc={rc}）"))


# ==================== 5. 查看选股快照 ====================
def show_snapshot():
    p = os.path.join(BASE, "signal_snapshot.json")
    if not os.path.exists(p):
        print("  （尚无 signal_snapshot.json，请先跑菜单 1）")
        return
    try:
        d = json.load(open(p, encoding="utf-8"))
    except Exception as ex:
        print(f"  读取失败: {ex}")
        return
    hr("最新选股快照")
    for k in ("date", "strategy", "rebal", "topk", "capital", "pool_size"):
        if k in d:
            print(f"  {k:<10}: {d[k]}")
    picks = d.get("picks") or d.get("top") or d.get("selection")
    if isinstance(picks, list):
        print("\n  标的:")
        for it in picks:
            if isinstance(it, dict):
                print("    " + "  ".join(f"{k}={v}" for k, v in it.items()))
            else:
                print("    " + str(it))
    if "next_exec_day" in d:
        print(f"\n  下次调仓日: {d['next_exec_day']}")


# ==================== 主菜单 ====================
MENU = """
==============================================================================
   美股因子策略 —— 一键菜单       仓库: SailorChina/us-stock-factor-backtest
==============================================================================
   [1] 每日实盘信号更新   检查/启动 Futu OpenD -> 跑信号 -> 显示选股
   [2] 完整回测重跑       $3,000 与 $1,500 两档全策略排名
   [3] 推送 GitHub        显式 add -> 中文提交 -> push -> 回读校验
   [4] 一键自检           _update_signal.py --self-test（98 项）
   [5] 查看最新选股快照
   [0] 退出
------------------------------------------------------------------------------
"""

ACTIONS = {"1": update_signal, "2": rerun_backtest, "3": push_github,
           "4": self_test, "5": show_snapshot}


def main():
    if not os.path.exists(PY):
        print(f"❌ 找不到 Python: {PY}")
        return 1
    if not os.path.exists(GIT):
        print(f"⚠ 找不到 git: {GIT}（菜单 3 将不可用）")
    while True:
        print(MENU)
        c = ask("  请选择 [0]: ", "0")
        if c == "0":
            print("  再见。")
            return 0
        fn = ACTIONS.get(c)
        if not fn:
            print(f"  无效选项: {c}")
            continue
        try:
            fn()
        except Exception as ex:
            print(f"\n  ❌ 执行出错: {type(ex).__name__}: {ex}")
        ask("\n  按回车返回菜单 ...")


if __name__ == "__main__":
    sys.exit(main())
