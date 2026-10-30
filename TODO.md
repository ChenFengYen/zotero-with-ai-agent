# TODO

## Completed

### `suggest_tags.py` — OpenAlex 概念自動 tag 建議 ✅

利用 OpenAlex concepts API 為文獻建議 tag，已通過 122 篇全量測試。

Tag 配置已外部化至 `tag_config.json`，新增/調整映射不需改程式碼。

## Decided (2026-10-21)

### 搬出 vault，成為獨立目錄

現況：放在 vault 根目錄，靠 vault `.gitignore` 排除；skill 與 vault_health 用相對路徑呼叫。

順序：
1. 先 commit 並推送（`import_papers.py`、`suggest_tags.py`、`tag_config.json` 從未進版控）
2. 搬到 vault 外（如 `C:\Users\ChenFengYen\zotero-ai-agent\`），各機設環境變數 `ZOTERO_AGENT_DIR`
3. vault 端改引用：兩個 skill、`settings.local.json`、`vault_health.py:513`、`TOOL_REFERENCE`、`LiteratureSearchGuide`
4. 實跑 `read tree`、`suggest_tags --dry-run`、`vault_health --zotero` 驗證
5. vault `CLAUDE_HISTORY` 記一句；刪 vault `.gitignore` 的排除行

.160 不使用 `/suggest-tags`、`/classify-ref`（使用者 10-21 確認），環境變數只需在 .154 設定。

進度：✅ 五步全部完成（2026-10-30）。第 1 步 `99fbc3a`；第 2 步搬到此處並設 `ZOTERO_AGENT_DIR=C:/Users/ChenFengYen/zotero-ai-agent`；第 3 步 vault 9 檔 56 處已改；第 4 步 `read tree`、`suggest_tags --dry-run`、`vault_health --zotero` 從新位置實跑皆正常；第 5 步 vault 內舊副本、`.gitignore` 排除行已刪，`CLAUDE_HISTORY` v2.22 已記。

### `import_papers.py --pdf` 停用或改寫

預設路徑寫死 `OV-Papers/PDF-raw`（07-31 已改名），執行會在 vault 根目錄建資料夾並被 obsidian-git 推送；檔名不是 BBT citekey，也不會掛到 Zotero 條目上。方向：PDF 一律交給 Zotero＋ZotFile。

## Planned Features

### 補 DOI 工具

期刊論文 611 篇中 297 篇無 DOI（多為拖 PDF 入庫）。以標題＋第一作者＋年份查 Crossref，只接受高吻合結果，產審核表，使用者確認後才寫回。

### tag_config.json 持續完善

隨使用發現新的 OpenAlex 概念需要映射或過濾時，更新 `tag_config.json`：
- 新 tag：加到 `tags` 中，標註 `category` 和 `openalex` 映射
- 新噪音：加到 `openalex_skip` 的對應分組中

### 新文獻入庫自動觸發 tag 建議

目前需手動跑 `suggest_tags.py`。未來可：
- 在 `import_papers.py` 匯入後自動呼叫 suggest_tags
- 或搭配排程定期掃描未標記文獻
