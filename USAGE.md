# 小鹅通 PDF 抓取说明

当前脚本改成了和 `D:\code\xiaoe_quanzi_scraper` 类似的两阶段模式：

1. `login`
   在真实 Chrome 中手动登录，并保存 `storage_state.json`
2. `fetch`
   复用 `storage_state.json` 进入标签页，发现并下载 PDF

## 安装

```powershell
pip install -r requirements.txt
playwright install chromium
```

## 第一步：登录并保存状态

```powershell
python .\xiaoe_pdf_scraper.py login `
  --login-url "https://quanzi.xiaoe-tech.com/c_6784b0c7f2fe0_MvZcjz4r1642/feed_list?app_id=apphihyjorj6008" `
  --chrome-path "C:\Users\洛畔\AppData\Local\Google\Chrome\Application\chrome.exe"
```

登录成功并进入圈子页面后，回到终端按回车。默认会把登录态保存到：

- [state/storage_state.json](D:\code\mathpaperScraper\state\storage_state.json)

如果你已经有参考项目现成的登录态，也可以直接复用：

- [D:\code\xiaoe_quanzi_scraper\state\storage_state.json](D:\code\xiaoe_quanzi_scraper\state\storage_state.json)

## 第二步：抓取和下载

使用当前项目自己的登录态：

```powershell
python .\xiaoe_pdf_scraper.py fetch `
  --crawl-url "https://quanzi.xiaoe-tech.com/c_6784b0c7f2fe0_MvZcjz4r1642/tag_detail?listType=477732&tagName=%E8%AF%95%E9%A2%98&app_id=apphihyjorj6008" `
  --chrome-path "C:\Users\洛畔\AppData\Local\Google\Chrome\Application\chrome.exe"
```

或者直接使用参考项目的登录态：

```powershell
python .\xiaoe_pdf_scraper.py fetch `
  --crawl-url "https://quanzi.xiaoe-tech.com/c_6784b0c7f2fe0_MvZcjz4r1642/tag_detail?listType=477732&tagName=%E8%AF%95%E9%A2%98&app_id=apphihyjorj6008" `
  --chrome-path "C:\Users\洛畔\AppData\Local\Google\Chrome\Application\chrome.exe" `
  --storage-state "D:\code\xiaoe_quanzi_scraper\state\storage_state.json"
```

## 输出

- PDF 默认保存到 [downloads](D:\code\mathpaperScraper\downloads)
- 下载记录默认保存到 [downloads/manifest.json](D:\code\mathpaperScraper\downloads\manifest.json)

## 调试

只想先验证前几个详情页：

```powershell
python .\xiaoe_pdf_scraper.py fetch `
  --crawl-url "你的新标签页地址" `
  --chrome-path "C:\Users\洛畔\AppData\Local\Google\Chrome\Application\chrome.exe" `
  --max-details 5
```
