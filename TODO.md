# TODO

## Planned Features

### `tag auto-new` — 自動標記新文獻

偵測最近新增但尚未標記的文獻，自動套用 taxonomy tags。

**設計思路：**

1. 用 Zotero API 查詢最近 N 天內新增的文獻（`dateAdded` 排序）
2. 篩選出沒有任何 taxonomy tags 的文獻（排除已標記過的）
3. 對每篇執行 `auto_tag_item()`

**CLI：**
```bash
python zotero_agent.py tag auto-new [--days 7] [--yes]
```

**可選進階：** 搭配 Windows Task Scheduler 設定每週執行，達成全自動化。

**暫不實作的理由：**
- 目前文獻量不大，手動 `tag auto` 或 `tag auto-batch` 即可
- 每次呼叫 Claude CLI 有 API 成本
- Taxonomy 會隨研究方向演變，定期手動檢視更合適
