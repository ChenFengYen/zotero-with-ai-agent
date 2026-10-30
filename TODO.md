# TODO

## Completed

### `suggest_tags.py` — OpenAlex 概念自動 tag 建議 ✅

利用 OpenAlex concepts API 為文獻建議 tag。Tag 配置外部化至 `tag_config.json`，新增或調整映射不需改程式碼。

### 工具與知識庫分開存放 ✅

本 repo 可以放在 Obsidian vault 之外，由環境變數 `ZOTERO_AGENT_DIR` 指向；搭配的 vault 工具（如 vault 健康檢查）透過這個變數找到 `.env`。放在 vault 裡時，必須用 vault 的 `.gitignore` 排除本目錄，否則 `.env` 會隨 vault 同步出去。

### `import_papers.py --pdf` 不再有預設下載目錄 ✅

預設目錄若從腳本位置推算，腳本一搬家，PDF 就跟著寫到錯的地方。現在 `--pdf` 實際下載時必須給 `--pdf-dir`；`--pdf --dry-run` 只探測來源，照舊可用。PDF 的主要入口仍是 Zotero（搭配 ZotFile 改名歸檔）。

## Planned Features

### 補 DOI 工具

拖 PDF 入庫的文獻常沒有 DOI，而 `suggest_tags.py` 只吃 DOI，這些文獻因此拿不到 tag 建議。規則：

- DOI 字串只能由程式從 API 回應取得，不經 LLM 生成。
- 以標題＋第一作者姓＋年份（±1）查 CrossRef，全部吻合才列入審核表；可疑的交使用者判斷，查無留空。
- arXiv 預印本直接用 `10.48550/arXiv.<id>`。
- 產生審核表，使用者確認後才寫回 Zotero。

### tag_config.json 持續完善

隨使用發現新的 OpenAlex 概念需要映射或過濾時，更新 `tag_config.json`：
- 新 tag：加到 `tags` 中，標註 `category` 和 `openalex` 映射
- 新噪音：加到 `openalex_skip` 的對應分組中

### 新文獻入庫自動觸發 tag 建議

目前需手動跑 `suggest_tags.py`。未來可：
- 在 `import_papers.py` 匯入後自動呼叫 suggest_tags
- 或搭配排程定期掃描未標記文獻
