# WorkBuddy 领券修复与验收

## 为什么以前能领，现在没有满 40 减 20

2026-09-23 核对了三条独立流程，时间均为 UTC+8：

| 流程 | 证据 | 结论 |
|---|---|---|
| 红包助手 `peppermall.meituan.com/eds/standard/equity/pkg/issue/claw` | [09-14 04:02](https://github.com/yoyo579871-cmd/meituan-coupon-server/actions/runs/34779485173) 返回 40-20；[09-15 05:12](https://github.com/yoyo579871-cmd/meituan-coupon-server/actions/runs/34897482259) 返回同名 40-12，两次代码均为 b429d91 | 服务端返回的券面额改变 |
| 惠省 `media.meituan.com/fulishemini/couponActivity/sendCouponByAi` | [09-11 04:41](https://github.com/yoyo579871-cmd/meituan-coupon-server/actions/runs/34527840935) 成功；[09-12 04:46](https://github.com/yoyo579871-cmd/meituan-coupon-server/actions/runs/34645939551) 返回 1014 发券失败 | 旧脚本误报已领，绿色不能证明领取成功 |
| WorkBuddy `media.meituan.com/fulishemini/couponActivity/sendCouponWork` | 09-20 新增；[09-23 06:09](https://github.com/yoyo579871-cmd/meituan-coupon-server/actions/runs/35790790384) 云端失败；10:51:35 本机执行同一 Python 脚本也失败；10:51:50 原 WorkBuddy 流程成功 36 张，含 40-20 | 新脚本与可工作的本地请求不等价 |

尚无证据证明官方简单地迁移了入口。旧渠道券内容变化、新渠道请求实现不完整是两个独立问题。1014 只是服务端失败码，不能据此断定已领取、活动未开放、Token 有效或 IP 风控。

## 本次修复

本地 WorkBuddy 的无网络请求构造检查实际生成了 `csecplatform`、`csecversion` 查询参数及非空 `mtgsig` 请求头。原云端代码遗漏了这些处理。

- 使用与成功本地客户端字节完全相同的 CLIGuard 1.3.1 核心，调用 `addCommonParams` 和 `signRequest`。
- JSON 使用紧凑 UTF-8 字节；对前 16200 字节计算 MD5，再对已添加公共参数的 URL 签名。发送的正文与签名正文相同。
- 补齐 `X-Requested-With: XMLHttpRequest`，取消原来的 `GitHub-Actions/1.0` 自定义 User-Agent。
- 签名缺失或组件不可用时立即失败，不发送无签名请求。
- 只有 code=200、券列表有效且含满 40 减 20 才显示目标领取成功。领到其他券但缺目标券会返回 `claimed_target_missing`，并保留已领数量。
- 网络超时和 1014 不自动重放 POST；输出不包含 Token、签名值或完整原始响应。

## 组件来源和完整性

组件从 WorkBuddy 官方客户端所配置的专家市场分发地址下载：

https://acc-1258344699.cos.accelerate.myqcloud.com/workbuddy/expert-marketplace/bundles/meituan-living-assistant.tar.gz

官方 WorkBuddy 应用的 `EXPERT_CENTER_COS_CONFIG.baseUrl` 和 `ExpertPluginService` bundle 地址构造与该 URL 一致。下载包中的签名核心与本机成功领取所用 1.0.9 插件的核心文件 SHA-256 完全一致。

- 下载包 SHA-256：`ec9e9d2e2758ae7fdfff2b1ffc454bc9b8e2ef153989fb6f68d34e8bfa24e07b`
- `cliguard.js` SHA-256：`eff1a324fdec2201ef021da00d02e64324cbf59e1328966718e4a43c6b6626cf`
- `package.json` SHA-256：`99f781a091ab69ef851a7a20802d413092171e94333603a6953afaaf5a7aeeff`

仓库只包含下载器和接入代码，不重新发布组件源码。下载器严格校验两个签名文件的固定哈希，只提取这两个普通文件到 `.runtime/cliguard`。整包 SHA-256 仅用于诊断，不作为安装门槛：官方重新压缩、修改打包元数据或无关文件，不应使完全相同的签名核心失效。任何签名文件内容变化仍会停止安装。

下载大小限制为 10 MiB，解压内容限制为 32 MiB；拒绝重复目标文件、链接和超大文件。仅针对组件 GET 下载的暂时故障进行最多 3 次尝试；领取 POST 仍不自动重试。安装失败会记录具体阶段及安全的错误码，不输出原始响应。

工作流安装并校验组件后立即保存这两个文件的缓存，再执行领取。领取被拒绝不会再导致组件缓存丢失。不复制或缓存本机账号、设备标识或用户目录。

## 09-24 安装故障修复

[09-24 06:17 定时运行](https://github.com/yoyo579871-cmd/meituan-coupon-server/actions/runs/35927507810) 在安装 SDK 时停止，未发出领取请求。官方包最后修改时间为 09-23 19:23:21（UTC+8），从 478280 字节变为 478282 字节，整包 SHA-256 变为 `05e3c8b044af2430ffd996ab7b959a0498766eb7eb75dd4f9fad2f10c6ebd3a1`，但全部文件内容以及上述两个签名文件的 SHA-256 均未变化。旧安装器对当前包能稳定复现整包校验失败。

同时，原缓存使用 job 成功后保存的方式；09-23 的领取被拒绝导致缓存没有保存，09-24 因此必须重新下载。修复保留签名核心的原有校验值，将缓存保存提前，并允许无关打包变化。

## 检查和运行

```bash
python -m unittest -v
node --test test_sign_workbuddy.cjs
python install_workbuddy_sdk.py
# 设置 MEITUAN_PT_TOKEN 和 WORKBUDDY_CLIGUARD_MODULE 后：
python claim_workbuddy.py --check-config
python claim_workbuddy.py --check-request
```

`--check-config` 只输出脱敏指纹，`--check-request` 验证签名构造；二者都不调用领取接口，不能当作领券成功。GitHub 手动任务默认勾选 `check_only`，会完成两项检查。取消勾选才实际请求领取。

定时计划仍为 UTC 19:17，即北京时间／新加坡时间次日 03:17。GitHub 排队延迟不固定，不能按历史延迟推算保证执行时刻。

## 验收边界

09-24 11:33 的[主分支真实运行](https://github.com/yoyo579871-cmd/meituan-coupon-server/actions/runs/35951934328) 已返回 HTTP 200、业务 code=200、消息“成功”，领取 33 张券；这是新的云端实际发券成功记录。安装、签名、接口请求均走通，组件缓存也在领取之前成功保存。

这次 `target_40_20_count=0`，所以状态为 `claimed_target_missing`，工作流仍显示失败。它表示领券成功但未拿到指定面额，不能再解释成整次发券被拒绝。目标券成功仍要求实际响应中的数量大于 0。

已安装的 WorkBuddy 官方插件 1.0.9 显示说明为“前3天必得40-20、每日必得38-16外卖券”。因此不能承诺每天固定获得 40-20；此次目标券缺失与活动限制相符，但接口未返回账号资格详情，具体发券规则仍以平台为准。当前日志没有保存其他券的面额，不能据此确认本次是否包含 38-16。
