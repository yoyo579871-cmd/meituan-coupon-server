#!/usr/bin/env python3
"""
美团自动领券 - GitHub Actions 版
15626208031（156****8031）
"""
import hashlib
import json
import os
import sys
import traceback
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta

# ── 环境变量 ──
USER_TOKEN   = os.environ.get("MEITUAN_USER_TOKEN", "")
PHONE_MASKED = os.environ.get("MEITUAN_PHONE_MASKED", "")
SUB_CHANNEL  = os.environ.get("MEITUAN_SUB_CHANNEL", "6511ba14351d4bbc8957722912b4c2d6")

BASE_URL = "https://peppermall.meituan.com"
CST = timezone(timedelta(hours=8))

print(f"[ENV] TOKEN={USER_TOKEN[:16] if USER_TOKEN else 'EMPTY'}... | PHONE={PHONE_MASKED} | CHANNEL={SUB_CHANNEL}")
print(f"[ENV] Python={sys.version}")

if not USER_TOKEN:
    print("[FATAL] MEITUAN_USER_TOKEN 未设置！请检查 GitHub Secrets。")
    sys.exit(1)
if not PHONE_MASKED:
    print("[FATAL] MEITUAN_PHONE_MASKED 未设置！请检查 GitHub Secrets。")
    sys.exit(1)


def http_post(path, body=None):
    """HTTP POST 请求，返回 dict"""
    url = BASE_URL + path
    payload = json.dumps(body).encode("utf-8") if body else b"{}"
    print(f"[HTTP] POST {path}")
    print(f"[HTTP] Body: {payload.decode()[:200]}")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "GitHub-Actions/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8")
            print(f"[HTTP] Response: {raw[:500]}")
            return json.loads(raw)
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8")
        print(f"[HTTP] HTTPError {e.code}: {raw[:500]}")
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"error": f"HTTP {e.code}", "raw": raw}
    except Exception as e:
        print(f"[HTTP] Exception: {traceback.format_exc()}")
        return {"error": str(e)}


# ── 主流程 ──
print("=" * 50)
print(f"[{datetime.now(CST).strftime('%Y-%m-%d %H:%M:%S')}] 美团自动领券 - {PHONE_MASKED}")
print("=" * 50)

# 1. 验证 token
try:
    verify = http_post(f"/eds/claw/login/token/verify?token={USER_TOKEN}")
except Exception as e:
    print(f"[FATAL] token 验证请求异常: {e}")
    traceback.print_exc()
    sys.exit(1)

if verify.get("code") != 0:
    print(f"[FAIL] Token 已失效 (code={verify.get('code')}): {verify.get('message', verify)}")
    # 打印完整响应帮助排查
    print(f"[DEBUG] Full response: {json.dumps(verify, ensure_ascii=False)}")
    sys.exit(1)
print("[OK] Token 验证通过")

# 2. 计算 redeem code
today = datetime.now(CST).strftime("%Y%m%d")
raw = f"{USER_TOKEN}_{PHONE_MASKED}_{today}"
redeem_code = hashlib.md5(raw.encode()).hexdigest()
print(f"[CALC] date={today} pk={raw[:20]}{PHONE_MASKED}")
print(f"[CALC] redeemCode={redeem_code}")

# 3. 领券
try:
    result = http_post("/eds/standard/equity/pkg/issue/claw", {
        "token": USER_TOKEN,
        "equityPkgRedeemCode": redeem_code,
        "phoneMasked": PHONE_MASKED,
        "subChannelCode": SUB_CHANNEL,
    })
except Exception as e:
    print(f"[FATAL] 领券请求异常: {e}")
    traceback.print_exc()
    sys.exit(1)

code = result.get("code")
msg = result.get("message", "")

print(f"[RESULT] code={code} msg={msg}")

if code == 0:
    data = result.get("data", {})
    success_list = data.get("successEquityList", [])
    fail_list = data.get("failEquityList", [])
    if success_list:
        total = len(success_list)
        total_yuan = sum(float(c.get("equityAmount", 0)) for c in success_list)
        print(f"[SUCCESS] 领到 {total} 张券，面额共 {total_yuan} 元")
        for c in success_list:
            print(f"  - {c.get('equityName', '?')}: {c.get('equityAmount', 0)}元 "
                  f"(满{c.get('equityThreshold', 0)}元) 有效期:{c.get('endTimeText', '?')}")
    elif fail_list:
        print(f"[WARN] {len(fail_list)} 张券领取失败")
        for c in fail_list:
            print(f"  - {c.get('equityName', '?')}: {c.get('failReason', '?')}")
    else:
        # 可能今天已领过
        print("[INFO] 已无新券可领（可能今日已领取）")
elif code == 4010:
    print("[INFO] 今日已领取（code=4010）")
elif code == 40008:
    print("[INFO] 今日已领取或领取过于频繁（code=40008），明天自动重试即可")
else:
    print(f"[FAIL] 领券失败 (code={code}): {msg}")
    print(f"[DEBUG] Full response: {json.dumps(result, ensure_ascii=False)[:500]}")
    sys.exit(1)

print("=" * 50)
print("[DONE] 执行完毕")
