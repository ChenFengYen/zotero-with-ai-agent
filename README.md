# Zotero AI Agent

使用 pyzotero + Claude CLI 管理 Zotero 文獻庫的命令列工具。

核心策略：**扁平化文獻管理** — 將深層巢狀 collections 轉為「兩層 collections + 多維 tags」，搭配 AI 驅動的 tag taxonomy 確保標記一致性。

## 安裝

```bash
pip install -r requirements.txt
```

依賴：
- [pyzotero](https://github.com/urschrei/pyzotero) — Zotero API 客戶端
- [python-dotenv](https://github.com/theskumar/python-dotenv) — 環境變數管理
- [Claude CLI](https://docs.anthropic.com/en/docs/claude-code) — AI 功能需要（taxonomy 建立、自動標記）

## 設定

在專案根目錄建立 `.env`：

```
ZOTERO_API_KEY=your_api_key
ZOTERO_LIBRARY_ID=your_library_id
ZOTERO_LIBRARY_TYPE=user
ZOTFILE_DIR=C:\path\to\zotfile\pdfs
```

- API Key 從 [Zotero Settings](https://www.zotero.org/settings/keys) 取得
- Library ID 從 [Zotero Groups/Library](https://www.zotero.org/settings/keys) 頁面取得
- `ZOTFILE_DIR` 為 ZotFile 管理的 PDF 目錄，供 PDF 分析功能使用

## 使用方式

所有寫入操作支援 `--dry-run` 預覽模式。

### 文獻 CRUD

```bash
python zotero_agent.py items list [-n 25]           # 列出最近文獻
python zotero_agent.py items search <query>          # 搜尋文獻
python zotero_agent.py items get <key>               # 取得文獻詳細資料
python zotero_agent.py items create <type> <title>   # 建立文獻
python zotero_agent.py items update <key> field=val   # 更新文獻欄位
python zotero_agent.py items delete <key>            # 刪除文獻
```

### Collection 操作

```bash
python zotero_agent.py col list                      # 列出所有 collections
python zotero_agent.py col tree                      # 樹狀結構顯示
python zotero_agent.py col items <key>               # 列出 collection 內文獻
python zotero_agent.py col create <name> [--parent <key>]
python zotero_agent.py col delete <key>              # 刪除 collection（保留文獻）
python zotero_agent.py col rename <key> <new_name>
python zotero_agent.py col move <key> [--parent <key>]
python zotero_agent.py col add-item <col_key> <item_key>
python zotero_agent.py col rm-item <col_key> <item_key>
python zotero_agent.py col flatten [--dry-run]       # 扁平化到兩層
```

### Tag 操作

```bash
python zotero_agent.py tag list                              # 列出所有 tags
python zotero_agent.py tag list-items <tag>                   # 列出 tag 下的文獻
python zotero_agent.py tag add <item_key> <tag1> [tag2 ...]   # 加 tags
python zotero_agent.py tag remove <item_key> <tag1> [...]     # 移除 tags
python zotero_agent.py tag rename <old> <new>                 # 全域重命名 tag
python zotero_agent.py tag delete <tag>                       # 全域刪除 tag
```

### Tag Taxonomy（AI 驅動）

```bash
python zotero_agent.py tag taxonomy build [-n 50]             # AI 分析文獻建立分類表
python zotero_agent.py tag taxonomy show                      # 顯示分類表
python zotero_agent.py tag taxonomy edit add <category> <tag>  # 新增 tag 到分類
python zotero_agent.py tag taxonomy edit remove <category> <tag>
```

Taxonomy 儲存在 `tag_taxonomy.json`，結構如下：

```json
{
  "version": 1,
  "categories": {
    "domain":  { "description": "研究領域", "tags": ["deep-learning", "plant-phenotyping", ...] },
    "method":  { "description": "研究方法", "tags": ["image-segmentation", "transfer-learning", ...] },
    "status":  { "description": "閱讀狀態", "tags": ["to-read", "reading", "read", "reference"] }
  }
}
```

### AI 自動標記

```bash
python zotero_agent.py tag auto <item_key> [--yes]            # 單篇自動標記
python zotero_agent.py tag auto-batch <collection_key> [--yes] # 批次自動標記
```

- Claude 分析文獻的 metadata 和 PDF 內容，從 taxonomy 中建議 tags
- 預設需用戶確認，`--yes` 跳過確認
- 只會建議 taxonomy 中已註冊的 tags

### PDF 分析

```bash
python zotero_agent.py pdf find <citekey>                     # 尋找 PDF 檔案
python zotero_agent.py analyze <key> [-p "prompt"] [--first-page]  # Claude 分析 PDF
```

## 扁平化策略

`col flatten` 將 depth >= 2 的 collections 拍平，處理流程（由最深層往上）：

1. 將 collection 名稱轉為 tag（加前綴 `col:`，如 `col:YOLO`）
2. 為該 collection 內所有文獻加上此 tag
3. 將文獻移到 depth-1 的祖先 collection
4. 刪除該 collection

好處：
- 文獻可透過多個 tag 交叉查詢，不受單一 collection 路徑限制
- 保留原始組織資訊（`col:` 前綴 tag 可追溯來源）
- 兩層 collections 維持大分類可瀏覽性

## 典型工作流程

```bash
# 1. 初次設定：建立 tag taxonomy
python zotero_agent.py tag taxonomy build -n 50

# 2. 扁平化現有 collections
python zotero_agent.py col flatten --dry-run    # 先預覽
python zotero_agent.py col flatten              # 確認後執行

# 3. 為現有文獻自動標記
python zotero_agent.py tag auto-batch <collection_key> --yes

# 4. 日常：新文獻加入後手動標記
python zotero_agent.py tag auto <item_key> --yes
```

## 未來規劃

參見 [TODO.md](TODO.md)。
