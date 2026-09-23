#!/usr/bin/env python3
"""Signed WorkBuddy requests, explicit outcomes, and offline diagnostics."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import urllib.error
import urllib.request
from urllib.parse import urlsplit, parse_qs
from datetime import datetime, timedelta, timezone

ENDPOINT = "https://media.meituan.com/fulishemini/couponActivity/sendCouponWork"
DEFAULT_SCENE = "a0d4da77f918ab204d86c911fcdd0ce1"
CST = timezone(timedelta(hours=8))


class SigningError(Exception):
    """The client could not construct a complete signed request."""


def prepare_signed_request(body):
    """Keep the request body and signature values in memory, never in logs/argv."""
    try:
        result = subprocess.run(
            [os.environ.get("NODE_BINARY", "node"),
             str(Path(__file__).with_name("sign_workbuddy.cjs"))],
            input=body, capture_output=True, timeout=30, check=False,
        )
        if result.returncode != 0:
            raise SigningError()
        prepared = json.loads(result.stdout)
        url, headers = prepared["url"], prepared["headers"]
        parts = urlsplit(url)
        expected = urlsplit(ENDPOINT)
        query = parse_qs(parts.query)
        if (parts.scheme != expected.scheme or parts.netloc != expected.netloc
                or parts.path != expected.path or parts.fragment
                or not query.get("csecplatform") or not query.get("csecversion")
                or not isinstance(headers, dict)
                or not isinstance(headers.get("mtgsig"), str)
                or not headers["mtgsig"]
                or any(not isinstance(v, str) or "\r" in v or "\n" in v
                       for v in headers.values())
                or set(headers) != {"mtgsig"}):
            raise SigningError()
        return url, headers
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError):
        raise SigningError() from None


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


def target_coupon_count(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
        return 0
    coupons = payload["data"].get("couponList", [])
    if not isinstance(coupons, list):
        return 0
    return sum(isinstance(c, dict) and str(c.get("priceLimit")) == "4000"
               and str(c.get("couponValue")) == "2000" for c in coupons)


def record(status, exit_code, count=0, http_status=None, code=None, target_count=0):
    # Only allowlisted, non-credential fields are written to the step summary.
    result = {"status": status, "coupon_count": count,
              "http_status": http_status, "business_code": code,
              "target_40_20_count": target_count}
    print("[OUTCOME] " + json.dumps(result, ensure_ascii=False))
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        try:
            with open(summary_path, "a", encoding="utf-8") as summary:
                summary.write("\n### WorkBuddy coupon result\n\n")
                summary.write(f"- Status: `{status}`\n- Confirmed coupons: {count}\n")
                summary.write(f"- HTTP status: {http_status}\n- Business code: {code}\n")
                summary.write(f"- 满 40 减 20: {target_count}\n")
        except OSError:
            print("[WARN] Could not write the Actions step summary")
    return exit_code


def main(argv=None, opener=None, signer=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-config", action="store_true",
                        help="Show a credential fingerprint; make no HTTP request")
    parser.add_argument("--check-request", action="store_true",
                        help="Verify signed request construction without claiming")
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

    # Match JSON.stringify in the working WorkBuddy client. Sign these exact bytes.
    body = json.dumps({"token": token, "aiScene": scene, "version": 2},
                      ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    try:
        signed_url, signature_headers = (signer or prepare_signed_request)(body)
    except SigningError:
        print("[FAIL] Signing unavailable; no coupon request was sent")
        return record("signing_error_no_request", 1)
    print("[REQUEST] CLIGuard public parameters and mtgsig prepared; values omitted")
    if args.check_request:
        print("[CONFIG] No request was sent; claiming remains unverified")
        return record("signed_request_checked_only", 0)
    req = urllib.request.Request(signed_url, data=body, method="POST", headers={
        "Content-Type": "application/json",
        "X-Requested-With": "XMLHttpRequest",
        **signature_headers,
    })
    if opener is None:
        transport = urllib.request.build_opener()
        transport.addheaders = []
        opener = transport.open
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
    target_count = target_coupon_count(payload) if status == "claimed" else 0
    if status == "claimed" and target_count == 0:
        status, exit_code = "claimed_target_missing", 1
    code = payload.get("code") if isinstance(payload, dict) else None
    # Unexpected code types are untrusted content, never summary markup.
    code = code if type(code) is int else None
    message = (payload.get("msg") or payload.get("message") or "") if isinstance(payload, dict) else ""
    print(f"[RESULT] http={http_status} code={code} msg={safe_text(message, token)}")
    if status == "claimed":
        print(f"[SUCCESS] Confirmed {count} coupons; 满 40 减 20: {target_count}")
    elif status == "claimed_target_missing":
        print(f"[FAIL] Confirmed {count} other coupons, but no 满 40 减 20 in this response")
    elif status == "claim_rejected_reason_unknown":
        print("[FAIL] 发券失败，原因未确认；不能据此判定今日已领、开放时间或 Token 有效")
    elif status == "authentication_failed":
        print("[FAIL] Authentication failed; check the WorkBuddy credential")
    elif status == "no_coupons_confirmed":
        print("[FAIL] Success code but empty coupon list; no receipt confirmed")
    else:
        print(f"[FAIL] {status}")
    return record(status, exit_code, count, http_status, code, target_count)


if __name__ == "__main__":
    sys.exit(main())
