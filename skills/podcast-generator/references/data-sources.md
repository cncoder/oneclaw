# 数据源

## 圆桌派（按需实时采集）

圆桌派不依赖 digest 或预采集数据，每次生成时实时搜索：

- LLM 生成 4-6 个中英文搜索词（覆盖不同角度）
- Google CDP 搜索 → 逐页提取正文 + 页内链接
- 3 层递归深度爬取（depth-1 最多 6 篇，depth-2 追 4 个，depth-3 追 2 个）
- 权威域名加分排序（arxiv +10, reuters +9, bloomberg +9 等）
- 自动跳过低质量站（CSDN, 百家号, 知乎等内容农场）
- CDP 不可用时降级 DuckDuckGo snippet
- `--sources` 手动指定 URL，`--context` 注入额外背景

## 每日日报板块

板块配置在 `config/sections.yaml`，增删板块不碰 Python 代码。

### 主板块

| 类别 | 板块 | Collector | 采集方式 |
|------|------|-----------|----------|
| 洞察 | AI 洞察、Lena 说 | LLM 生成（Phase 2） | — |
| 天气 | 今日天气 | weather | API |
| 市场 | 美股市场 | yahoo_stock | API |
| 市场 | Crypto/Web3 | crypto + theblock | API |
| 新闻 | AI 动态 | situation | API |
| 新闻 | 财经要闻 | bloomberg_news | CDP |
| 新闻 | 国际大事 | world_news | API |
| 新闻 | 网络安全 | security | API |
| 社交 | X/Twitter 热点 | twitter | RSSHub（CDP 降级） |
| 社交 | Threads 热门 | threads | CDP |
| 社交 | Reddit 热门 | reddit | API |
| 社交 | Instagram | instagram | CDP |
| 发现 | Perplexity 发现 | perplexity | CDP |
| 发现 | HN 精选 | news | API |
| 发现 | GitHub 推荐 | github_smart | API |
| 生活 | 影视推荐 | entertainment | API |
| 生活 | 数码 3C | digital_tech | API |
| 生活 | App 推荐 | app_recommend | CDP |

### 辅助 Collector（无独立板块，数据合并或被其他模块引用）

| Key | Collector | 合并到 |
|-----|-----------|--------|
| theblock | theblock | crypto |
| hacker_news_detailed | hacker_news | — |
| product_hunt | product_hunt | — |
| worldmonitor | worldmonitor | — |
| perplexity_finance | perplexity_finance | — |
| wsj_markets | wsj_markets | — |
| global_markets | global_markets | — |
| rsshub_feeds | rsshub_feeds | — |
| yahoo_hk | yahoo_hk | — |

### 采集架构

- API 类 collector：8 线程并行
- CDP 类 collector：串行（Chrome 单实例限制）
- 两组并发执行
- 每个 collector 有独立 timeout（30-120s）

## Digest 模块

`src/digest/` 独立于日报，更轻量：

| 源 | 采集方式 |
|----|---------|
| Hacker News | API |
| GitHub Trending | CDP |
| Product Hunt | CDP |
| CoinDesk | CDP |
| X Timeline | CDP |

输出到 `data/digests/{date}/digest.json`。日报 Phase 1 可交叉引用近 7 天 digest。

配置在 `src/digest_config.yaml`，定义了兴趣领域权重（AI/LLM > AWS > Web3 > 量化 > 摄影 > 户外 > GitHub > 日本旅行）。

## 添加新数据源

1. 在 `src/daily/collectors/` 创建新 collector 模块
2. 在 `config/sections.yaml` 添加板块配置
3. 设置 `cdp: true/false`、`timeout`、`priority`
4. 重启日报即可生效，不需要改 main.py
