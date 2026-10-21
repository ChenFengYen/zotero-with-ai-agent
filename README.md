# Zotero AI Agent

使用 pyzotero 管理 Zotero 文獻庫的命令列工具。

CLI 設計以資料庫操作模型為基礎：**CRUD + Join + Dump**，讓操作直覺對應到「我要做什麼」而非「我要操作哪種資源」。

## 安裝

```bash
pip install -r requirements.txt
```

依賴：
- [pyzotero](https://github.com/urschrei/pyzotero) — Zotero API 客戶端
- [python-dotenv](https://github.com/theskumar/python-dotenv) — 環境變數管理

## 設定

在專案根目錄建立 `.env`：

```
ZOTERO_API_KEY=your_api_key
ZOTERO_LIBRARY_ID=your_library_id
ZOTERO_LIBRARY_TYPE=user
```

- API Key 從 [Zotero Settings](https://www.zotero.org/settings/keys) 取得
- Library ID 從 [Zotero Groups/Library](https://www.zotero.org/settings/keys) 頁面取得

## 使用方式

所有寫入操作支援 `--dry-run` 預覽模式。

### READ — 查詢

```bash
python zotero_agent.py read search <query>       # 搜尋文獻
python zotero_agent.py read get <key>             # 取得文獻詳細 metadata
python zotero_agent.py read tree                  # 樹狀結構顯示 collections
python zotero_agent.py read list <col_key>        # 列出 collection 內文獻
python zotero_agent.py read tags                  # 列出所有 tags
python zotero_agent.py read tags <tag>            # 列出某 tag 下的文獻
```

### CREATE — 新增

```bash
python zotero_agent.py create item <type> <title>          # 建立文獻
python zotero_agent.py create col <name> [--parent <key>]  # 建立 collection
python zotero_agent.py create tag <item_key> <tag1> [...]  # 為文獻加 tags
```

### UPDATE — 更新

```bash
python zotero_agent.py update rename col <key> <new_name>  # 重新命名 collection
python zotero_agent.py update rename tag <old> <new>       # 全域重命名 tag
python zotero_agent.py update move <col_key> [--parent <key>]  # 移動 collection
python zotero_agent.py update tag <item_key> <old> <new>   # 替換文獻的 tag
python zotero_agent.py update item <key> field=value       # 更新文獻欄位
```

### DELETE — 刪除

```bash
python zotero_agent.py delete item <key>          # 刪除文獻
python zotero_agent.py delete col <key>           # 刪除 collection（保留文獻）
python zotero_agent.py delete tag <tag>           # 全域刪除 tag
python zotero_agent.py delete cleanup             # 掃描問題 collections
```

`delete cleanup` 掃描三類問題：
- `deleted=True` 的 collections（桌面端刪除但伺服器殘留）
- 空的 leaf collections（無文獻、無子 collection）
- 重複名稱的 collections

### JOIN — 多篇比較

```bash
python zotero_agent.py join <key1> <key2> [...]   # 並列比較多篇文獻 metadata
```

逐欄位（標題、作者、日期、期刊、tags、摘要）顯示比較，適合評估相關文獻的異同。

### DUMP — 匯出引用

```bash
python zotero_agent.py dump "<query>" [--fmt list]     # 搜尋並匯出引用清單
python zotero_agent.py dump <key1> <key2> --fmt bibtex  # 指定文獻匯出 BibTeX
python zotero_agent.py dump "<query>" --fmt keys        # 只輸出 item keys
```

支援格式：
- `list`（預設）— 人類可讀的引用格式
- `bibtex` — BibTeX 格式
- `keys` — 僅 Zotero keys（適合 pipe 到其他指令）

## 文獻匯入 (import_papers.py)

獨立腳本，透過學術 API 匯入文獻。所有 metadata 來自 API 回傳，不經 LLM 生成。

```bash
# 單篇 DOI 匯入
python import_papers.py --doi 10.xxxx/xxxxx --collection <key> --tags tag1,tag2

# 批量 DOI 檔案匯入（一行一個 DOI，# 開頭為註解）
python import_papers.py --file dois.txt --collection <key> --tags tag1,tag2

# 標題搜尋，人工選擇後匯入
python import_papers.py --search "plant growth dynamics" --collection <key>

# 匯入 metadata + 下載 OA PDF
python import_papers.py --doi 10.xxxx/xxxxx --pdf --collection <key>

# 批量匯入 + PDF，指定輸出目錄
python import_papers.py --file dois.txt --pdf --pdf-dir /path/to/pdfs

# 預覽模式（含 PDF 來源探測）
python import_papers.py --file dois.txt --pdf --dry-run
```

使用的 API：
- **CrossRef** (`api.crossref.org`) — DOI 查詢（權威來源）和標題搜尋
- **OpenAlex** (`api.openalex.org`) — CrossRef 查無時的備援

### PDF 下載 (`--pdf`)

加上 `--pdf` 後，匯入 metadata 同時嘗試下載 OA PDF 至 `OV-Papers/PDF-raw/{citekey}.pdf`。

PDF 來源備援鏈（依序嘗試）：
1. **Unpaywall** — `url_for_pdf` 直接下載（最快，但常為 null）
2. **Semantic Scholar** — `openAccessPdf.url`（排除僅為 DOI 重定向的 URL）
3. **Europe PMC** — `fullTextUrl` 中 `documentStyle=pdf` 的連結
4. **PMC OA API** — 下載 tar.gz 包後解出 PDF（最慢但覆蓋率最高）

驗證機制：
- Magic bytes：確認檔案開頭為 `%PDF`
- 檔案大小：50KB–100MB（過小可能是錯誤頁面，過大可能是附錄合集）
- 已存在的 PDF 不會重複下載

Citekey 生成規則：`{firstauthor}{year}{firstword}`
- 連字號合併（如 "Time-Series" → "timeseries"）
- 跳過冠詞和介詞（a, an, the, of, in...）

限制：
- 僅支援 Open Access 論文；付費牆後的論文無法自動下載
- 部分出版商的直連 PDF 可能被封鎖（如 Elsevier、Springer 付費期刊）

特性：
- 自動偵測重複（比對 DOI 和標題）
- 無需安裝新套件（使用 Python 標準庫 + pyzotero）
- Rate limiting（0.5s 間隔）避免 API 封鎖
- 可選在 `.env` 中設定 `CROSSREF_EMAIL` 進入 CrossRef polite pool

## 自動 Tag 建議 (suggest_tags.py)

利用 OpenAlex 的概念標注 API 為 Zotero 文獻建議 tag。不依賴 LLM，零幻覺風險。

```bash
# 預覽：對無 tag 文獻建議
python suggest_tags.py --untagged --dry-run

# 預覽：對特定文獻
python suggest_tags.py --keys <KEY1> <KEY2> --dry-run

# 互動模式（逐篇確認 y/n/e）
python suggest_tags.py --untagged

# 批量模式（全部列出，確認一次套用）
python suggest_tags.py --untagged --batch

# 調整過濾參數
python suggest_tags.py --untagged --min-score 0.5 --min-level 3 --max-tags 5
```

資料流：DOI → OpenAlex API → concepts（score≥0.4, level≥2）→ tag_config.json 映射/過濾 → 確認後寫入

## Tag 配置 (tag_config.json)

統一管理所有 Zotero tag 的配置檔，取代舊的 `tag_taxonomy.json`。

結構：
- `tags`: 每個 tag 有 `category`（分類）和可選的 `openalex`（OpenAlex 概念名映射）
- `categories`: tag 分類定義（method, domain, application, model, species, physiology, status）
- `openalex_skip`: OpenAlex 概念的忽略清單，按原因分組

新增 tag 或調整映射時，只需編輯 `tag_config.json`，不需改程式碼。

## 已知限制

- `read search ""` 預設只回傳 100 筆（pyzotero 預設 limit）
- `read list <key>` 只查直屬 items，不含子 collection
- Windows 終端需加 `PYTHONIOENCODING=utf-8` 避免 cp950 編碼錯誤
- citekey 由 Better BibTeX 插件管理，無法透過 API 直接取得

## 注意事項

- 所有寫入操作（create, update, delete）需使用者確認後才執行
- `delete cleanup` 只做掃描報告，不會自動刪除任何東西
