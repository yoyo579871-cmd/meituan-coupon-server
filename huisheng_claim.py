#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
美团惠省优惠助手 - 云端自动领券脚本
接口: POST https://media.meituan.com/fulishemini/couponActivity/sendCouponByAi
与红包助手独立运行，互不影响
"""

import json
import sys
import os
import urllib.request

# ── 从环境变量读取配置 ────────────────────────────────────────────────
TOKEN = os.environ.get("MEITUAN_USER_TOKEN", "")
AI_SCENE = os.environ.get("MEITUAN_AI_SCENE", "df2abe45d02da3084ccf4b0e4b90646a")

BASE_URL = "https://media.meituan.com"
ISSUE_PATH = "/fulishemini/couponActivity/sendCouponByAi"


def fen_to_yuan(fen):
    """分转元"""
    if not fen:
        return "0"
    yuan = int(fen) / 100
    return str(int(yuan)) if yuan == int(yuan) else f"{yuan:.1f}"


def main():
    print("=" * 50)
    print("美团惠省优惠助手 - 云端自动领券")
    print("=" * 50)

    if not TOKEN:
        print("[FAIL] MEITUAN_USER_TOKEN 未设置！请在 GitHub Secrets 中配置。")
        sys.exit(1)

    # ── 构造请求 ────────────────────────────────────────────────────────
    url = BASE_URL + ISSUE_PATH
    body = json.dumps({"token": TOKEN, "aiScene": AI_SCENE}, ensure_ascii=False).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
            "X-Requested-With": "XMLHttpRequest",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8")
            result = json.loads(raw)
    except Exception as e:
        print(f"[FAIL] 网络异常: {e}")
        sys.exit(1)

    code = result.get("code")
    msg = result.get("msg", "")
    data = result.get("data") or {}

    print(f"[INFO] HTTP 200, code={code}, msg={msg}")

    # ── 解析结果 ────────────────────────────────────────────────────────
    if code == 200:
        coupons = data.get("couponList", [])
        activity_name = data.get("activityName", "未知活动")
        activity_link = data.get("activityLink", "")

        total_value = 0
        print(f"\n[OK] 领券成功！共 {len(coupons)} 张券")
        print(f"[OK] 活动：{activity_name}")
        if activity_link:
            print(f"[OK] 活动链接：{activity_link}")

        # 按品类统计
        categories = {}
        for c in coupons:
            name = c.get("couponName", "未知")
            value = int(c.get("couponValue", 0))
            price_limit = int(c.get("priceLimit", 0))
            total_value += value

            # 简单分类
            cat = "其他"
            if "外卖" in name:
                cat = "外卖"
            elif "闪购" in name:
                cat = "闪购"
            elif "堂食" in name:
                cat = "堂食"
            elif "旅游" in name or "度假" in name:
                cat = "旅游度假"
            elif "玩乐" in name or "变美" in name:
                cat = "玩乐变美"
            elif "医美" in name or "美容" in name:
                cat = "医美美容"
            elif "洗衣" in name or "家政" in name or "保洁" in name or "维修" in name or "家庭" in name:
                cat = "生活服务"
            elif "商超" in name or "果蔬" in name or "水果" in name:
                cat = "商超果蔬"
            elif "鲜花" in name:
                cat = "鲜花"
            elif "小象" in name:
                cat = "小象超市"
            elif "屈臣氏" in name:
                cat = "品牌专享"
            elif "神价" in name:
                cat = "神价频道"
            elif "证件" in name:
                cat = "生活服务"

            if cat not in categories:
                categories[cat] = {"count": 0, "value": 0, "coupons": []}
            categories[cat]["count"] += 1
            categories[cat]["value"] += value
            categories[cat]["coupons"].append(
                f"  {name} | 满{fen_to_yuan(price_limit)}减{fen_to_yuan(value)}"
            )

        print(f"\n  总价值: ¥{fen_to_yuan(total_value)}")
        print(f"\n--- 按品类汇总 ---")
        for cat, info in sorted(categories.items()):
            print(f"  [{cat}] {info['count']}张 | 价值¥{fen_to_yuan(info['value'])}")
            for c in info["coupons"]:
                print(c)

    elif code == 1014:
        print("[INFO] 今日已领取（code=1014），明天自动重试即可")
    elif code == 401:
        print("[FAIL] Token 已过期（code=401），需要重新认证！")
        sys.exit(1)
    elif code in (509, 50200):
        print("[INFO] 请求过于频繁（限流），稍后自动重试即可")
    else:
        print(f"[FAIL] 未知错误 (code={code}): {msg}")
        print(f"[DEBUG] {json.dumps(result, ensure_ascii=False)[:500]}")
        sys.exit(1)

    print("\n[DONE] 执行完毕")


if __name__ == "__main__":
    main()
