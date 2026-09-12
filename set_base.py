# -*- coding: utf-8 -*-
"""
路径移植工具 —— 把各脚本里硬编码的项目根目录 BASE 改成"当前脚本所在目录"。

背景: 本仓库所有脚本原本写死了绝对路径
    BASE = r"c:/Users/sailor/WorkBuddy/2026-09-11-09-02-22"
克隆到别的机器/目录后需要统一改写。

用法:
    python set_base.py              # 只看会改哪些文件, 不写入 (dry-run)
    python set_base.py --apply      # 实际改写, 原文件备份为 *.py.bak
    python set_base.py --check      # 只检查; 有文件仍指向别处则退出码 1 (可用于 CI)
    python set_base.py --revert     # 从 *.py.bak 还原

改写内容:
    所有形如  BASE = r"..."   或   BASE=r"..."   的单行赋值
    路径统一写成正斜杠形式 (Windows 的 Python 两种都认)

另外会列出其它仍指向原机器的绝对路径 (如 futuapi 工具目录、Python 解释器),
这些需要你按自己的环境手工确认 —— 工具不强改, 免得改错。
"""
import os, re, sys, glob

HERE = os.path.dirname(os.path.abspath(__file__))
TARGET = HERE.replace("\\", "/")
SELF = os.path.basename(os.path.abspath(__file__))


def same_path(a, b):
    """Windows 路径比较: 忽略大小写与结尾斜杠 (文件里常写小写 c:/)"""
    return a.rstrip("/\\").lower() == b.rstrip("/\\").lower()

BASE_RE = re.compile(r'(?m)^(?P<head>\s*BASE\s*=\s*r?)(?P<q>["\'])(?P<path>[^"\'\n]*)(?P=q)')
ABS_RE = re.compile(r'["\']([A-Za-z]:/[^"\'\n]{8,})["\']')


def py_files():
    out = []
    for p in sorted(glob.glob(os.path.join(HERE, "**", "*.py"), recursive=True)):
        if "__pycache__" in p:
            continue
        out.append(p)
    return out


def plan():
    """返回 (需改写的文件列表, 其它绝对路径清单)"""
    todo, others = [], {}
    for p in py_files():
        name = os.path.basename(p)
        if name == SELF:
            continue
        try:
            s = open(p, encoding="utf-8").read()
        except Exception as e:
            print(f"  [!] 读取失败 {name}: {e}")
            continue
        hits = list(BASE_RE.finditer(s))
        if hits and any(not same_path(m.group("path"), TARGET) for m in hits):
            todo.append((p, len(hits)))
        for m in ABS_RE.finditer(s):
            v = m.group(1)
            if same_path(v, TARGET):
                continue
            if "__pycache__" in v:
                continue
            others.setdefault(os.path.basename(p), set()).add(v)
    return todo, others


def show_others(others):
    if not others:
        return
    print("\n" + "=" * 92)
    print("其它仍指向原机器的绝对路径 (需你手工确认, 本工具不改):")
    print("=" * 92)
    for f, vals in sorted(others.items()):
        for v in sorted(vals):
            print(f"  {f:<32} {v}")
    print("\n  提示: 若指向 futuapi 工具目录, 改成你自己的路径, 或用 futu.OpenQuoteContext 替代;")
    print("        若指向 python.exe, 建议改成 sys.executable。")


def main():
    args = set(sys.argv[1:])
    todo, others = plan()
    print("=" * 92)
    print(f"当前目录 (目标 BASE): {TARGET}")
    print("=" * 92)

    if "--revert" in args:
        n = 0
        for p in py_files():
            bak = p + ".bak"
            if os.path.exists(bak):
                os.replace(bak, p); n += 1
                print(f"  还原 {os.path.basename(p)}")
        print(f"\n共还原 {n} 个文件")
        return 0

    if "--check" in args:
        if todo:
            print(f"❌ 有 {len(todo)} 个文件的 BASE 仍指向别处:")
            for p, n in todo:
                print(f"   {os.path.basename(p)}")
            return 1
        print("✅ 所有脚本的 BASE 都已指向当前目录")
        show_others(others)
        return 0

    if not todo:
        print("✅ 无需修改: 所有脚本的 BASE 都已指向当前目录")
        show_others(others)
        return 0

    print(f"将修改 {len(todo)} 个文件:")
    changed = 0
    for p, n in todo:
        try:
            s = open(p, encoding="utf-8").read()
        except Exception as e:
            print(f"  [!] {os.path.basename(p)} 读取失败: {e}"); continue
        new = BASE_RE.sub(lambda m: f'{m.group("head")}{m.group("q")}{TARGET}{m.group("q")}', s)
        if new == s:
            continue
        if "--apply" in args:
            if not os.path.exists(p + ".bak"):
                open(p + ".bak", "w", encoding="utf-8", newline="").write(s)
            open(p, "w", encoding="utf-8", newline="").write(new)
            print(f"  ✅ 已改写 {os.path.basename(p)}  (原文件备份为 {os.path.basename(p)}.bak)")
        else:
            print(f"  · {os.path.basename(p)}  ({n} 处)")
        changed += 1

    if "--apply" in args:
        print(f"\n完成: 改写 {changed} 个文件。用 python set_base.py --check 复验。")
    else:
        print(f"\n(dry-run) 以上 {changed} 个文件将被改写。加 --apply 实际执行。")
    show_others(others)
    return 0


if __name__ == "__main__":
    sys.exit(main())
