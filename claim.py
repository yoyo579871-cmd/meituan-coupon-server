#!/usr/bin/env python3
"""
美团自动领券 - GitHub Actions 版
15626208031（156****8031）
每天 11:00（北京时间）自动执行，免费，无需电脑开机
"""
import hashlib
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone, timedelta

# ── 从 GitHub Secrets 读取（本地测试用环境变量） ──
USER_TOKEN    = os.environ["MEITUAN_USER_TOKEN"]
PHONE_MASKED  = os.environ["MEITUAN_PHONE_MASKED"]
SUB_CHANNEL   = os.environ.get("MEITUAN_SUB_CHANNEL", "6511ba14351d4bbc8957722912b4c2d6")

BASE_URL = "https://peppermall.meituan.com"
CST = timezone(timedelta(hours=8))

# ── HTTP 工具 ──
def post(path, body=None):
    url = BASE_URL + path
    data = json.dumps(body).encode() if body else b"{}"
    req = urllib.request.Request(url, data=data, headers={
        "Content-Type": "application/json",
        "User-Agent": "GitHub-Actions/1.0"
    }, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return json.loads(e.read().decode())
    except Exception as e:
        return {"error": str(e)}

# ── 1. 验证 token ──
print("=" * 50)
print(f"[{datetime.now(CST).strftime('%Y-%m-%d %H:%M:%S')}] 美团自动领券 - 156****8031")
print("=" * 50)

verify = post(f"/eds/claw/login/token/verify?token={USER_TOKEN}")
if verify.get("code") != 0:
    print(f"[FAIL] Token 已失效 (code={verify.get('code')}): {verify.get('message')}")
    sys.exit(1)
print("[OK] Token 验证通过")

# ── 2. 计算 redeem code ──
today = datetime.now(CST).strftime("%Y%m%d")
raw = f"{USER_TOKEN}_{PHONE_MASKED}_{today}"
redeem_code = hashlib.md5(raw.encode()).hexdigest()
print(f"[INFO] 日期={today}  redeemCode={redeem_code[:16]}...")

# ── 3. 领券 ──
result = post("/eds/standard/equity/pkg/issue/claw", {
    "token": USER_TOKEN,
    "equityPkgRedeemCode": redeem_code,
    "phoneMasked": PHONE_MASKED,
    "subChannelCode": SUB_CHANNEL,
})

code = result.get("code")
if code == 0:
    success_list = result.get("data", {}).get("successEquityList", [])
    if success_list:
        total = len(success_list)
        total_yuan = sum(int(c.get("discountAmountYuanStr", 0)) for c in success_list)
        print(f"[SUCCESS] 领到 {total} 张券，面额共 {total_yuan} 元")
        for c in success_list:
            print(f"  - {c['userEquityName']}: {c['discountAmountYuanStr']}元 "
                  f"(满{c['priceLimitAmountYuanStr']}元)")
    else:
        print("[INFO] 今日已领取，无新券")
elif code and str(code) in ("4010",):
    print("[INFO] 今日已领取（防重复）")
else:
    msg = result.get("message", "未知错误")
    print(f"[FAIL] 领券失败 (code={code}): {msg}")
    sys.exit(1)

print("=" * 50)
print("[DONE] 执行完毕")
