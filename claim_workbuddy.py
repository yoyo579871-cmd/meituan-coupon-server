#!/usr/bin/env python3
"""
美团 WorkBuddy 专属券 - 云端自动领券
入口与本地「美团生活助手」完全一致：
    POST https://media.meituan.com/fulishemini/couponActivity/sendCouponWork
凭证：pt-passport token，从环境变量 MEITUAN_PT_TOKEN 读取（GitHub Secrets 维护）
注意：脚本内不硬编码任何用户凭证。
"""
import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta

TOKEN    = os.environ.get("MEITUAN_PT_TOKEN", "").strip()
AI_SCENE = os.environ.get("MEITUAN_AI_SCENE", "a0d4da77f918ab204d86c911fcdd0ce1").strip()

BASE_URL = "https://media.meituan.com"
ISSUE_PATH = "/fulishemini/couponActivity/sendCouponWork"
CST = timezone(timedelta(hours=8))

print("=" * 56)
print(f"[{datetime.now(CST).strftime('%Y-%m-%d %H:%M:%S')}] 美团 WorkBuddy 专属券 - 云端自动领券")
print("=" * 56)

if not TOKEN:
    print("[FATAL] MEITUAN_PT_TOKEN 未设置！请在仓库 Settings -> Secrets 中添加。")
    sys.exit(1)

# 只打印前缀与长度，绝不输出完整 token
print(f"[ENV] TOKEN={TOKEN[:8]}... (len={len(TOKEN)}) | aiScene={AI_SCENE[:8]}...")

body = {"token": TOKEN, "aiScene": AI_SCENE, "version": 2}
req = urllib.request.Request(
    BASE_URL + ISSUE_PATH,
    data=json.dumps(body).encode("utf-8"),
    headers={
        "Content-Type": "application/json; charset=utf-8",
        "User-Agent": "GitHub-Actions/1.0",
    },
    method="POST",
)

try:
    with urllib.request.urlopen(req, timeout=25) as r:
        raw = r.read().decode("utf-8")
except urllib.error.HTTPError as e:
    raw = e.read().decode("utf-8")
    print(f"[HTTPError] status={e.code}")
except Exception as e:
    print(f"[FATAL] 请求异常: {e}")
    sys.exit(1)

try:
    resp = json.loads(raw)
except Exception:
    print("[FATAL] 响应解析失败，原文前300字符：")
    print(raw[:300])
    sys.exit(1)

code = resp.get("code")
msg = resp.get("msg") or resp.get("message") or ""
print(f"[RESULT] code={code} msg={msg}")


def yuan(fen):
    """分转元"""
    try:
        return int(fen) / 100
    except (TypeError, ValueError):
        return 0


def fmt_time(v):
    """兼容时间戳(ms)或字符串"""
    if not v:
        return "?"
    try:
        return datetime.fromtimestamp(int(v) / 1000, CST).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(v)


if code == 200:
    data = resp.get("data") or {}
    coupons = data.get("couponList") or []
    if coupons:
        total = sum(yuan(c.get("couponValue", 0)) for c in coupons)
        print(f"[SUCCESS] 领到 {len(coupons)} 张券，面额共 {total:.0f} 元")
        for c in coupons:
            name = c.get("couponName") or c.get("name") or "?"
            print(
                f"  - {name}: 满{yuan(c.get('priceLimit', 0)):.0f}减{yuan(c.get('couponValue', 0)):.0f}"
                f" 有效期 {fmt_time(c.get('couponStartTime'))} 至 {fmt_time(c.get('couponEndTime'))}"
            )
    else:
        print("[INFO] 接口返回成功，但本次无券列表（今日券池为空）")
elif code == 1014:
    print("[INFO] 今日已领取（code=1014），每天一次，明天自动重试即可")
elif code == 401:
    print("[FAIL] 登录态已过期（code=401）")
    print("       → 请在本地重新登录美团账号，并把新的 pt-passport token")
    print("         更新到 GitHub Secret：MEITUAN_PT_TOKEN")
    sys.exit(1)
elif code in (509, 50200):
    print(f"[INFO] 请求过于频繁（code={code}），稍后重试即可")
else:
    print(f"[FAIL] 领券失败 code={code} msg={msg}")
    print("[DEBUG] " + raw[:400])
    sys.exit(1)

print("=" * 56)
print("[DONE] 执行完毕")
