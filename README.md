# mathpaperScraper

一个基于 Python + Playwright 的小鹅通鹅圈子 PDF 抓取工具，目标是稳定抓取“数学试卷 / 数学答案”并保留原始 PDF 文件名。

当前实现重点解决了这几个问题：

- 登录依赖真实 Chrome，而不是纯 HTTP 模拟
- 支持先登录再抓取，避免每次重新扫码
- 支持更换抓取地址，不需要改代码
- 只下载数学试卷和数学答案，过滤掉其他学科
- 支持先做统计，再决定是否全量下载
- 下载结果带 `manifest.json`，便于去重和断点续跑

## 项目结构

```text
mathpaperScraper/
├─ README.md
├─ requirements.txt
├─ xiaoe_pdf_scraper.py
├─ USAGE.md
├─ .gitignore
├─ downloads/              # 运行后生成，默认下载目录
└─ state/                  # 运行后生成，默认登录态目录
```

## 环境要求

- Windows
- Python 3.11+
- Google Chrome 或 Chrome for Testing

## 安装

```powershell
pip install -r requirements.txt
playwright install chromium
```

## 工作流程

脚本采用两阶段模式：

1. `login`
   在真实 Chrome 中打开圈子页面，手动登录，并保存 `storage_state.json`
2. `fetch`
   复用 `storage_state.json` 抓取标签页、详情页中的 PDF

## 1. 登录并保存状态

默认登录页参数已经内置，但你也可以显式传入：

```powershell
python .\xiaoe_pdf_scraper.py login `
  --login-url "https://quanzi.xiaoe-tech.com/c_6784b0c7f2fe0_MvZcjz4r1642/feed_list?app_id=apphihyjorj6008" `
  --chrome-path "C:\Users\洛畔\AppData\Local\Google\Chrome\Application\chrome.exe"
```

完成登录并进入圈子页面后，回到终端按回车。默认会保存到：

- `state/storage_state.json`

## 2. 抓取并下载数学 PDF

默认下载到项目下的 `downloads` 目录：

```powershell
python .\xiaoe_pdf_scraper.py fetch `
  --crawl-url "https://quanzi.xiaoe-tech.com/c_6784b0c7f2fe0_MvZcjz4r1642/tag_detail?listType=477732&tagName=%E8%AF%95%E9%A2%98&app_id=apphihyjorj6008" `
  --chrome-path "C:\Users\洛畔\AppData\Local\Google\Chrome\Application\chrome.exe" `
  --output-dir "D:\code\mathpaperScraper\downloads"
```

## 更换爬取地址

地址参数已经保留为命令行参数，不用改代码。

登录地址：

- `--login-url`

抓取地址：

- `--crawl-url`

兼容旧参数：

- `--feed-url` 等价于 `--login-url`
- `--tag-url` 等价于 `--crawl-url`

例如切换到另一个标签页：

```powershell
python .\xiaoe_pdf_scraper.py fetch `
  --crawl-url "新的标签页地址" `
  --chrome-path "C:\Users\洛畔\AppData\Local\Google\Chrome\Application\chrome.exe"
```

## 只做统计，不下载

如果你想先确认一共能访问多少详情页、多少数学 PDF 候选，可以先跑：

```powershell
python .\xiaoe_pdf_scraper.py fetch `
  --crawl-url "你的标签页地址" `
  --chrome-path "C:\Users\洛畔\AppData\Local\Google\Chrome\Application\chrome.exe" `
  --stats-only
```

## 调试时只抓前 N 个详情页

```powershell
python .\xiaoe_pdf_scraper.py fetch `
  --crawl-url "你的标签页地址" `
  --chrome-path "C:\Users\洛畔\AppData\Local\Google\Chrome\Application\chrome.exe" `
  --max-details 5
```

## 当前筛选规则

脚本会尽量只保留“数学试卷 / 数学答案”：

- 包含 `数学`
- 同时包含 `卷`、`试卷`、`答案` 中的至少一个
- 排除 `语文 / 英语 / 物理 / 化学 / 生物 / 历史 / 地理 / 政治`

如果后续你要放宽或收紧规则，可以调整 `xiaoe_pdf_scraper.py` 中的这些常量：

- `MATH_INCLUDE_KEYWORDS`
- `PAPER_INCLUDE_KEYWORDS`
- `SUBJECT_EXCLUDE_KEYWORDS`

## 输出说明

- PDF 默认输出到 `downloads/`
- 下载记录默认输出到 `downloads/manifest.json`
- 登录态默认输出到 `state/storage_state.json`

`manifest.json` 里会记录：

- PDF 原始链接
- 最终保存路径
- 文件大小
- 下载时间

## 已知注意点

- 小鹅通登录态会过期，`storage_state.json` 失效后需要重新执行 `login`
- 某些情况下页面虽然已经登录成功，但文案变化会让自动校验偏保守；当前脚本会尽量保存状态并在 `fetch` 时继续验证
- 站点上的 PDF 链接通常带临时签名，所以稳定方案不是长期复用旧 PDF 链接，而是每次重新进入页面发现链接
- 页面如果继续改版，最稳的方向仍然是“真实浏览器 + 登录态 + 网络响应提取”

## 常见问题

### 1. Chrome 可以打开，但脚本提示找不到浏览器

显式传入：

```powershell
--chrome-path "C:\Users\洛畔\AppData\Local\Google\Chrome\Application\chrome.exe"
```

### 2. 登录后仍提示状态失效

重新执行：

```powershell
python .\xiaoe_pdf_scraper.py login --chrome-path "C:\Users\洛畔\AppData\Local\Google\Chrome\Application\chrome.exe"
```

然后再执行 `fetch`。

### 3. 只想保留数学，不要其他学科

当前脚本已经按这个策略过滤，不会主动下载其他学科。

## 主要命令速查

登录：

```powershell
python .\xiaoe_pdf_scraper.py login `
  --login-url "登录页地址" `
  --chrome-path "C:\Users\洛畔\AppData\Local\Google\Chrome\Application\chrome.exe"
```

统计：

```powershell
python .\xiaoe_pdf_scraper.py fetch `
  --crawl-url "抓取页地址" `
  --chrome-path "C:\Users\洛畔\AppData\Local\Google\Chrome\Application\chrome.exe" `
  --stats-only
```

下载：

```powershell
python .\xiaoe_pdf_scraper.py fetch `
  --crawl-url "抓取页地址" `
  --chrome-path "C:\Users\洛畔\AppData\Local\Google\Chrome\Application\chrome.exe" `
  --output-dir "D:\code\mathpaperScraper\downloads"
```
