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

## 已知限制

- `read search ""` 預設只回傳 100 筆（pyzotero 預設 limit）
- `read list <key>` 只查直屬 items，不含子 collection
- Windows 終端需加 `PYTHONIOENCODING=utf-8` 避免 cp950 編碼錯誤
- citekey 由 Better BibTeX 插件管理，無法透過 API 直接取得

## 注意事項

- 所有寫入操作（create, update, delete）需使用者確認後才執行
- `delete cleanup` 只做掃描報告，不會自動刪除任何東西
