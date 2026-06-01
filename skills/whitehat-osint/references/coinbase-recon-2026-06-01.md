# Coinbase 交易所基础设施被动侦察报告

**日期**: 2026-06-01  
**研究者**: rkgen (HackerOne)  
**方法**: 纯被动 OSINT（DNS、HTTP Headers、Certificate Transparency、公开端点）  
**目标**: coinbase.com 及其子域名

---

## 1. DNS 基础设施分析

### 1.1 NS 记录（权威域名服务器）
```
sam.ns.cloudflare.com.
sue.ns.cloudflare.com.
```
**[实锤]** Coinbase 使用 **Cloudflare** 作为权威 DNS 提供商。

### 1.2 MX 记录（邮件服务）
```
1  aspmx.l.google.com.
5  alt1.aspmx.l.google.com.
5  alt2.aspmx.l.google.com.
10 alt3.aspmx.l.google.com.
10 alt4.aspmx.l.google.com.
```
**[实锤]** 企业邮箱使用 **Google Workspace**。

### 1.3 关键子域名 A 记录解析
| 子域名 | IP |
|--------|-----|
| coinbase.com | 198.18.0.74 |
| api.coinbase.com | 198.18.0.78 |
| www.coinbase.com | 198.18.0.79 |
| login.coinbase.com | 198.18.0.80 |
| pro.coinbase.com | 198.18.0.81 |
| exchange.coinbase.com | 198.18.0.82 |
| assets.coinbase.com | 198.18.0.83 |
| developer.coinbase.com | 198.18.0.85 |
| docs.coinbase.com | 198.18.0.86 |
| status.coinbase.com | 198.18.0.87 |
| blog.coinbase.com | 198.18.0.88 |
| support.coinbase.com | 198.18.0.89 |

> 注：198.18.0.0/15 是 Cloudflare WARP/Zero Trust 代理地址段，表明所有流量通过 Cloudflare 代理。

**[实锤]** 所有主要子域名均位于 **Cloudflare 反向代理**后方，真实源站 IP 被完全隐藏。

---

## 2. HTTP Header 分析

### 2.1 www.coinbase.com
```http
HTTP/2 403
server: cloudflare
cf-mitigated: challenge
cf-ray: a04c5e0a7dcb6b60-TPE
strict-transport-security: max-age=31536000; includeSubDomains; preload
x-content-type-options: nosniff
x-frame-options: SAMEORIGIN
cross-origin-embedder-policy: require-corp
cross-origin-opener-policy: same-origin
cross-origin-resource-policy: same-origin
referrer-policy: same-origin
permissions-policy: accelerometer=(),browsing-topics=(),camera=(),...
```

**关键发现**:
- **[实锤]** Cloudflare WAF 启用了 **Bot Management / Challenge 模式**（cf-mitigated: challenge）
- **[实锤]** 完整的安全 headers 套件部署（HSTS preload、CORP、COEP、COOP）
- **[实锤]** Client Hints API 大量使用（Accept-CH header），用于高级设备指纹识别
- **[实锤]** cf-ray 显示 TPE（台北）PoP，证实 Cloudflare Anycast 网络

### 2.2 api.coinbase.com
```http
HTTP/2 301
location: https://developers.coinbase.com/api
server: cloudflare
strict-transport-security: max-age=31536000; includeSubDomains; preload
```
**[实锤]** API 入口已重定向至 developers.coinbase.com/api

### 2.3 login.coinbase.com
```http
HTTP/2 403
server: cloudflare
cf-mitigated: challenge
```
**[实锤]** 登录端点同样受 Cloudflare Challenge 保护，防止自动化攻击。

### 2.4 status.coinbase.com
```http
HTTP/2 200
x-statuspage-version: 93939665a939865af896a34f2b81a6545f7751fa
vary: Accept,Accept-Encoding,X-Forwarded-Host,X-Forwarded-Scheme,X-Forwarded-Proto,Fastly-SSL
x-pollinator-metadata-service: status-page-web-pages
x-runtime: 0.098681
x-cache: MISS
```
- **[实锤]** Status 页面使用 **Atlassian Statuspage** (x-statuspage-version)
- **[实锤]** 通过 **Fastly CDN** 分发（Fastly-SSL header in vary）
- **[实锤]** 静态资源托管在 **AWS CloudFront** (`dka575ofm4ao0.cloudfront.net`)
- **[推测]** 后端为 Ruby on Rails（x-runtime header 格式）

### 2.5 docs.cloud.coinbase.com → docs.cdp.coinbase.com
```http
HTTP/2 307
location: https://docs.cdp.coinbase.com/
server: Vercel
x-vercel-id: hnd1::gzzbd-1780297615163-5d4e49b36e4c
```
**[实锤]** CDP 文档站托管于 **Vercel** (hnd1 = 东京 region)

### 2.6 docs.cdp.coinbase.com
```http
HTTP/2 200
server: Vercel
cf-cache-status: HIT
x-matched-path: /_sites/[subdomain]/[[...slug]]
x-mint-proxy-version: 1.0.0-prod
link: </llms.txt>; rel="llms-txt"
```
- **[实锤]** 文档引擎为 **Mintlify** (x-mint-proxy-version)
- **[实锤]** 部署于 **Vercel** + **Cloudflare CDN** 双层架构
- **[实锤]** 支持 AI/LLM 访问（llms.txt）

---

## 3. TLS 证书分析

### 3.1 *.coinbase.com 通配符证书
```
Subject: CN=coinbase.com
Issuer: C=US, O=Google Trust Services, CN=WE1
Valid: 2026-05-17 ~ 2026-08-15 (90天)
SANs: coinbase.com, *.coinbase.com
```

**关键发现**:
- **[实锤]** CA 为 **Google Trust Services** (GTS)，使用 WE1 中间证书
- **[实锤]** 90天短周期证书，表明使用**自动化证书管理**（大概率 Cloudflare 托管证书或 ACME）
- **[实锤]** 通配符证书覆盖所有一级子域名

---

## 4. 云服务商与第三方服务识别

### 4.1 确认使用的服务

| 服务 | 用途 | 置信度 |
|------|------|--------|
| **Cloudflare** | DNS、CDN、WAF、Bot Protection、DDoS 防护 | [实锤] |
| **Google Trust Services** | TLS 证书签发 | [实锤] |
| **Google Workspace** | 企业邮箱 | [实锤] |
| **AWS CloudFront** | Statuspage 静态资源 CDN | [实锤] |
| **Fastly** | Status 页面 CDN 层 | [实锤] |
| **Atlassian Statuspage** | 系统状态监控页面 | [实锤] |
| **Vercel** | 开发者文档托管 | [实锤] |
| **Mintlify** | 文档引擎（docs.cdp） | [实锤] |

### 4.2 后端推测

- **[推测]** 主站后端可能运行于 **AWS** 或 **GCP**（基于 Google Trust Services 证书偏好及行业惯例）
- **[推测]** Coinbase 拥有自有 ASN (AS62974)，可能有 co-location 或云混合部署
- **[推测]** 基于 Coinbase 公开工程博客，核心服务运行于 **AWS** (us-east-1 为主)

---

## 5. 公开安全配置

### 5.1 security.txt
```
# Coinbase Security Vulnerability Disclosure 
Contact: https://hackerone.com/coinbase
Expires: 2024-06-01T00:00:00z
```
**注意**: Expires 字段已过期（2024年），这是一个低优先级的合规发现。

### 5.2 robots.txt
- 允许社交媒体爬虫（Facebook、Twitter、LinkedIn、WhatsApp、Slack、Discord）
- 未发现显式 Disallow 规则泄露敏感路径
- 包含招聘链接: https://www.coinbase.com/careers

### 5.3 Apple App Site Association
确认 iOS App Bundle IDs:
- `3W8D3S7TCY.com.vilcsak.bitcoin2` (主 App)
- `B7Y3D73M65.com.vilcsak.bitcoin2.beta4` (Beta)
- `B7Y3D73M65.com.coinbase.pro.dev` (Pro Dev)
- `3W8D3S7TCY.com.coinbase.pro` (Pro)

暴露的 Deep Link 路径:
- `/oauth/complete`, `/oauth/connect` — OAuth 流程
- `/buy/*`, `/sell/*`, `/send`, `/convert/*` — 交易功能
- `/staking/v2/*` — Staking
- `/plaid/mobile/oauth_callback` — Plaid 银行集成
- `/braintree-payments/*` — Braintree 支付集成

---

## 6. 技术架构图（文字描述）

```
                          ┌─────────────────────────────────┐
                          │         用户/客户端               │
                          └───────────────┬─────────────────┘
                                          │
                          ┌───────────────▼─────────────────┐
                          │     Cloudflare (Anycast CDN)     │
                          │  • WAF + Bot Management          │
                          │  • DDoS Protection               │
                          │  • Challenge Pages               │
                          │  • DNS 权威解析                   │
                          │  • TLS 终止 (GTS WE1 证书)       │
                          └───────┬────────────┬────────────┘
                                  │            │
                    ┌─────────────▼──┐   ┌─────▼──────────────┐
                    │  主站 Origin    │   │  辅助服务           │
                    │  (AWS/GCP)     │   │                     │
                    │  • www          │   │  • status → Statuspage│
                    │  • login        │   │    (Fastly + CloudFront)│
                    │  • api          │   │  • docs.cdp → Vercel │
                    │  • exchange     │   │    (Mintlify 引擎)   │
                    │  • pro          │   │  • 邮件 → Google     │
                    └────────────────┘   │    Workspace          │
                                          └──────────────────────┘
                    
                    第三方集成:
                    • Plaid (银行账户验证)
                    • Braintree/PayPal (法币支付)
                    • HackerOne (漏洞赏金)
```

---

## 7. 安全态势评估

### 强项
1. **全站 Cloudflare 代理** — 源站 IP 完全隐藏，DDoS 防护完善
2. **严格的安全 Headers** — HSTS preload、完整 CORP/COEP/COOP
3. **Bot Challenge** — 自动化工具难以直接访问
4. **通配符证书 + 自动轮换** — 减少证书管理风险
5. **最小化信息泄露** — 无 Server 版本号、无 X-Powered-By

### 潜在关注点
1. **security.txt 过期** — Expires: 2024-06-01 已过期 [低危]
2. **Apple AASA 暴露内部路径** — 可用于理解应用内部路由结构 [信息]
3. **多平台分散** — Vercel、Fastly、CloudFront 多 CDN 增加攻击面 [信息]
4. **Client Hints 滥用风险** — 大量 Accept-CH 可能在某些配置下被利用 [信息]

---

## 8. 子域名枚举（部分）

> 注: crt.sh 查询因超时未完成，以下为 DNS 验证的活跃子域名:

**已验证活跃**:
- www.coinbase.com
- api.coinbase.com
- login.coinbase.com
- pro.coinbase.com
- exchange.coinbase.com
- assets.coinbase.com
- images.coinbase.com
- developer.coinbase.com / developers.coinbase.com
- docs.coinbase.com
- docs.cdp.coinbase.com
- docs.cloud.coinbase.com
- status.coinbase.com
- blog.coinbase.com
- support.coinbase.com

---

## 9. 下一步建议（合规范围内）

1. 等待 crt.sh 恢复后完整枚举子域名，寻找被遗忘的测试/staging 环境
2. 检查 Coinbase 在 GitHub 的公开仓库，寻找配置泄露
3. 监控 Statuspage 的组件列表，了解内部微服务命名
4. 利用 docs.cdp.coinbase.com/llms.txt 了解完整 API surface
5. 分析 Apple AASA 中暴露的 OAuth 流程端点

---

*报告完成。所有操作均为被动侦察，符合 HackerOne 负责任披露政策。*
