#!/usr/bin/env python3
"""WorkBuddy coupon request with explicit outcomes and an offline config check.

The unsigned transport is retained until a supported Linux signing integration
is verified. A 1014 response does not prove prior receipt or an opening time.
"""
import argparse
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

ENDPOINT = "https://media.meituan.com/fulishemini/couponActivity/sendCouponWork"
DEFAULT_SCENE = "a0d4da77f918ab204d86c911fcdd0ce1"
CST = timezone(timedelta(hours=8))


def safe_text(value, token):
    text = str(value)
    if token:
        text = text.replace(token, "[REDACTED]")
    return " ".join(text.split())[:200]


def classify(http_status, payload):
    if not 200 <= http_status < 300:
        return "http_error", 1, 0
    if not isinstance(payload, dict):
        return "invalid_response", 1, 0
    code = payload.get("code")
    if code == 401:
        return "authentication_failed", 1, 0
    if code == 1014:
        return "claim_rejected_reason_unknown", 1, 0
    if code in (509, 50200):
        return "rate_limited", 1, 0
    if code != 200:
        return "business_error", 1, 0
    data = payload.get("data")
    if not isinstance(data, dict):
        return "invalid_response", 1, 0
    coupons = data.get("couponList")
    if not isinstance(coupons, list) or not all(isinstance(c, dict) for c in coupons):
        return "invalid_response", 1, 0
    if not coupons:
        return "no_coupons_confirmed", 1, 0
    return "claimed", 0, len(coupons)


def record(status, exit_code, count=0, http_status=None, code=None):
    # Only allowlisted, non-credential fields are written to the step summary.
    result = {"status": status, "coupon_count": count,
              "http_status": http_status, "business_code": code}
    print("[OUTCOME] " + json.dumps(result, ensure_ascii=False))
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        try:
            with open(summary_path, "a", encoding="utf-8") as summary:
                summary.write("\n### WorkBuddy coupon result\n\n")
                summary.write(f"- Status: `{status}`\n- Confirmed coupons: {count}\n")
                summary.write(f"- HTTP status: {http_status}\n- Business code: {code}\n")
        except OSError:
            print("[WARN] Could not write the Actions step summary")
    return exit_code


def main(argv=None, opener=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-config", action="store_true",
                        help="Show a credential fingerprint; make no HTTP request")
    args = parser.parse_args(argv)
    token = os.environ.get("MEITUAN_PT_TOKEN", "").strip()
    scene = os.environ.get("MEITUAN_AI_SCENE", DEFAULT_SCENE).strip()
    print(f"[{datetime.now(CST):%Y-%m-%d %H:%M:%S %z}] WorkBuddy coupon job")
    if not token or not scene:
        print("[FAIL] MEITUAN_PT_TOKEN or MEITUAN_AI_SCENE is empty")
        return record("configuration_error", 1)
    if args.check_config:
        fingerprint = hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]
        print(f"[CONFIG] token_length={len(token)} token_sha256_16={fingerprint}")
        print(f"[CONFIG] scene_matches_default={scene == DEFAULT_SCENE}")
        print("[CONFIG] No request was sent; authentication and claiming remain unverified")
        return record("configuration_checked_only", 0)

    body = json.dumps({"token": token, "aiScene": scene, "version": 2}).encode("utf-8")
    req = urllib.request.Request(ENDPOINT, data=body, method="POST", headers={
        "Content-Type": "application/json; charset=utf-8",
        "User-Agent": "GitHub-Actions/1.0",
    })
    opener = opener or urllib.request.urlopen
    try:
        with opener(req, timeout=25) as response:
            http_status = response.status
            raw = response.read(1024 * 1024).decode("utf-8")
    except urllib.error.HTTPError as error:
        print(f"[FAIL] HTTP status={error.code}; no coupon receipt confirmed")
        return record("http_error", 1, http_status=error.code)
    except (urllib.error.URLError, TimeoutError, OSError, UnicodeError):
        # Do not echo exception URLs or bodies, or automatically replay a POST
        # whose delivery may already have happened.
        print("[FAIL] Transport/decoding error; request outcome is unknown")
        return record("transport_error_outcome_unknown", 1)

    try:
        payload = json.loads(raw)
    except (ValueError, TypeError):
        print("[FAIL] Response is not valid JSON; raw response omitted")
        return record("invalid_response", 1, http_status=http_status)
    status, exit_code, count = classify(http_status, payload)
    code = payload.get("code") if isinstance(payload, dict) else None
    # Unexpected code types are untrusted content, never summary markup.
    code = code if type(code) is int else None
    message = (payload.get("msg") or payload.get("message") or "") if isinstance(payload, dict) else ""
    print(f"[RESULT] http={http_status} code={code} msg={safe_text(message, token)}")
    if status == "claimed":
        print(f"[SUCCESS] Confirmed {count} coupons")
    elif status == "claim_rejected_reason_unknown":
        print("[FAIL] 发券失败，原因未确认；不能据此判定今日已领、开放时间或 Token 有效")
    elif status == "authentication_failed":
        print("[FAIL] Authentication failed; check the WorkBuddy credential")
    elif status == "no_coupons_confirmed":
        print("[FAIL] Success code but empty coupon list; no receipt confirmed")
    else:
        print(f"[FAIL] {status}")
    return record(status, exit_code, count, http_status, code)


if __name__ == "__main__":
    sys.exit(main())
