# -*- coding: utf-8 -*-
import os, subprocess, sys

GIT = r"C:/Users/sailor/.workbuddy/binaries/PortableGit/versions/1.2.0/cmd/git.exe"
CA  = r"C:/Users/sailor/.workbuddy/binaries/PortableGit/versions/1.2.0/mingw64/etc/ssl/certs/ca-bundle.crt"
os.chdir(r"C:/Users/sailor/WorkBuddy/2026-09-11-09-02-22")
def g(*a, **kw):
    r = subprocess.run([GIT, "-c", f"http.sslCAInfo={CA}"] + list(a),
                       capture_output=True, text=True, encoding="utf-8", errors="replace", **kw)
    return r

r = g("remote", "-v")
print("[remote]")
url = ""
for line in r.stdout.splitlines():
    if "(push)" in line:
        url = line.split()[1]
print("  ", url.split("@")[-1][:80] if "@" in url else url[:100])
print("  含令牌:", "@github.com" in url)

r = g("status", "--short")
changed = [l for l in r.stdout.splitlines() if l.strip()]
print("\n[status] 变更文件:")
for l in changed: print("  ", l)

if not changed:
    print("  无变更, 退出"); sys.exit(0)

print("\n[add]")
print(g("add", "-A").stdout.strip() or "  ok")

msg = "docs: 补充 v23 选股标准与标的池构成说明\n\n- 新增 美股选股标准与标的池_v23.md\n- README 报告索引加入 v23"
r = g("commit", "-m", msg)
print("\n[commit]")
print(r.stdout.strip() or r.stderr.strip())

r = g("push", "origin", "HEAD")
print("\n[push]")
print(r.stdout.strip() or r.stderr.strip())

r = g("log", "--oneline", "-2")
print("\n[log]")
print(r.stdout.strip())

r = g("status", "--short")
print("\n[status after]", repr(r.stdout.strip()) or "(clean)")
