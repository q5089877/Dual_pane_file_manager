# 左右分欄檔案總管 (Dual Pane File Manager)

> 適用於 Windows 的鍵盤導向雙欄檔案瀏覽器，內建網路磁碟搜尋功能。  
> 使用 Python 3.10+ 與 PyQt6 開發。

**平台：** 僅支援 Windows &nbsp;·&nbsp; **版本：** 1.3.0 &nbsp;·&nbsp; **授權：** MIT

---

## 為什麼要做這個工具

Windows 檔案總管應付日常使用綽綽有餘，但當你需要頻繁在專案資料夾間跳轉、跨 NAS 複製檔案、或追查上週改動的某個檔案時，它就顯得力不從心。

這個工具針對以下三個痛點而生：

- **沒有雙欄視窗** — 在兩個資料夾間切換只能靠 Alt+Tab 反覆跳窗
- **網路搜尋不可靠** — Windows 搜尋無法穩定索引 UNC 路徑或 SMB 磁碟
- **過度依賴滑鼠** — 改名、複製、移動每一步都得抓滑鼠

---

## 快速開始

```bash
# 1. 複製專案
git clone https://github.com/q5089877/Dual_pane_file_manager.git
cd Dual_pane_file_manager

# 2. 建立虛擬環境（建議）
python -m venv venv
venv\Scripts\activate

# 3. 安裝相依套件
pip install -r requirements.txt

# 4. 設定
copy config.example.json config.json

# 5. 啟動
python main.py
```

---

## 功能介紹

### 雙欄導航

- 左右各一欄，每欄最多可開啟 **5 個獨立分頁**
- `Tab` 在同一欄內循環切換分頁 · `` ` `` 在左右兩欄間切換焦點
- 完整的瀏覽歷程 — `Alt+←` / `Alt+→` 前後巡覽
- 可直接輸入路徑的網址列
- 首頁 (`home://`) 顯示所有磁碟與 Windows 快速存取資料夾
- 每欄三種視圖模式：**詳細列表**、**樹狀圖**、**圖示縮圖格**

### 檔案操作

所有主要操作均可透過鍵盤完成：

| 按鍵 | 功能 |
|------|------|
| `F2` | 重新命名（行內編輯） |
| `Alt+F2` | 加上日期後綴改名（`_YYYYMMDD`） |
| `F3` / `X` | 移動到對面欄 |
| `F4` / `C` | 複製到對面欄 |
| `F5` | 重新整理 |
| `F7` | 新增資料夾 |
| 右鍵 → 新增文字檔 | 在目前資料夾建立空白 `.txt` |
| `Del` | 送入資源回收筒 |
| `Shift+Del` | 永久刪除 |
| `Ctrl+C / X / V` | 系統剪貼簿 複製 / 剪下 / 貼上 |
| `Ctrl+Z` | 復原上一次的移動、改名或刪除 |
| `Ctrl+D` | 釘選 / 取消釘選 |
| `Ctrl+F` | 開啟搜尋面板 |
| `Space` | 切換檔案預覽 |

右鍵選單與工具列還提供：

- 在原位製作副本（自動加流水號後綴）
- 將資料夾打包為 `.zip` 壓縮檔（日期戳記命名）
- 解壓縮 `.zip` / `.tar.gz` / `.tar.bz2` / `.tar.xz` — 智慧判斷目標資料夾
- 直接將剪貼簿中的圖片或文字貼成新檔案
- 將資料夾輸出為 ASCII 樹狀圖（存為 `.txt`，自動以記事本開啟）
- 將資料夾內容輸出為 AI context（Markdown + 原始碼，用於 LLM 提示詞）

**復原** 涵蓋每個工作階段最近 10 次的移動、改名與刪除操作。  
**OneDrive 感知**：離線雲端佔位符會被自動偵測並跳過，不會觸發下載。

### 檔案預覽

按 `Space` 在側邊開啟預覽面板；再按一次 `Space` 則以全螢幕 Quick Look 浮窗顯示。

| 格式 | 預覽方式 |
|------|---------|
| 圖片（JPG、PNG、BMP、GIF…） | 背景執行緒解碼，UI 完全不凍結 |
| PDF / `.ai` | PyMuPDF · 可設定頁數上限（SD 模式） |
| 文字 / 原始碼 | Highlight.js 語法高亮（透過 WebEngine） |
| CSV / XLSX | HTML 表格 — 顯示前 15 列 |
| ZIP / 7z | 檔案清單 |
| DOCX | 純文字擷取 |
| Markdown | 渲染為 HTML |
| SVG | 行內渲染 |
| 音訊（MP3、FLAC、OGG…） | 透過 mutagen 顯示 ID3/Vorbis 標籤 |
| 字型（TTF、OTF） | 內嵌字元預覽 |

預覽透過 150 ms 防抖計時器在背景執行緒載入，快速上下瀏覽時不會阻塞介面。

### 網路搜尋

以 **SQLite FTS5** 為核心，支援本機與網路磁碟的全文搜尋。

搜尋面板透過 `Ctrl+F` 以嵌入式方式（無模態對話框）開啟。

**主節點 / 消費者節點架構：**

```
[主節點機器]
  掃描本機磁碟 + 指定的網路路徑
  → 將索引發布至 NAS 上的共用資料夾

[任何設定了消費者模式的機器]
  讀取共用索引
  → 跨磁碟即時搜尋，無需自行掃描
```

- 篩選條件：大小（`> 1 MB` 至 `> 1 GB`）、日期（今日 / 本週 / 本月 / 自訂），以及萬用字元模式（`*.pdf`、`report_?.docx`）
- 搜尋結果以每批 50 筆的方式串流顯示；點擊結果直接跳至其所在資料夾
- 個人索引（`personal.db`）會在系統閒置時自動建立
- 主節點索引在兩個資料庫槽（`index_A` / `index_B`）間輪換，支援熱切換且零停機

### 釘選與我的最愛

**釘選**（`Ctrl+D`）：快速書籤，顯示於工具列下拉選單中。
- 可附加備註（5 秒自動確認對話框）
- 標記為「重要」可永久保留；一般釘選項目閒置超過 14 天後會顯示提醒
- 將資料夾拖曳至釘選按鈕可靜默新增

**我的最愛**：透過專屬對話框管理的命名路徑群組。
- 建立、重新命名、刪除群組
- 一鍵將目前資料夾加入任意群組

### 主題與語言

兩種內建介面語言，依 Windows 地區設定自動偵測：
- `zh_TW` — 繁體中文
- `en_US` — English

主題色彩定義於 `theme.json`，並透過 `styles.qss` 套用 — Python 程式碼中沒有任何硬編碼顏色。預設主題（「調光護眼」）採用深藍色調，針對長時間使用優化。

### 自動更新

應用程式在啟動 10 秒後檢查 GitHub Releases。若有新版本，狀態列會出現更新按鈕；點擊後在背景下載安裝程式並自動啟動。

---

## 設定說明

將 `config.example.json` 複製為 `config.json` 並依需求調整。

| 鍵值 | 說明 | 預設值 |
|------|------|--------|
| `language` | 介面語言：`zh_TW` 或 `en_US` | `zh_TW` |
| `left_tabs` | 左欄啟動時開啟的路徑 | `["C:\\"]` |
| `right_tabs` | 右欄啟動時開啟的路徑 | `["C:\\"]` |
| `restore_last_session` | 啟動時恢復上次開啟的分頁 | `true` |
| `confirm_before_delete` | 送入資源回收筒前詢問確認 | `true` |
| `preview_font_size` | 文字預覽的字型大小 | `14` |
| `pdf_preview_max_pages` | PDF 預覽渲染的最大頁數 | `3` |
| `search_limit` | 搜尋最多回傳的結果數 | `1000` |
| `remote_index_root` | 共用搜尋索引資料夾的路徑（網路磁碟） | `""` |
| `is_master_node` | `true` = 此機器負責建立並發布索引 | `false` |
| `monitored_paths` | 主節點掃描的路徑清單 | `[]` |
| `exclude_exts` | 建立索引時略過的副檔名 | `[]` |
| `exclude_dirs` | 建立索引時略過的資料夾名稱 | `[]` |

### 可攜式模式

若 `config.json` 與 `main.py`（或 `.exe`）放在同一資料夾，應用程式會以**可攜式模式**運行，所有設定與日誌均存於同一資料夾，而非 `%LOCALAPPDATA%`。

---

## 網路搜尋設定

### 主節點（負責建立索引的機器）

```jsonc
// config.json
{
  "is_master_node": true,
  "monitored_paths": ["C:\\Projects", "K:\\SharedWork"],
  "remote_index_root": "K:\\SearchIndex",
  "max_depth": 7
}
```

主節點依照排程（預設每日 02:00）掃描 `monitored_paths`，並將結果寫入 `remote_index_root`。所有消費者節點均從此處讀取。

### 消費者節點（其他所有機器）

```jsonc
{
  "is_master_node": false,
  "remote_index_root": "K:\\SearchIndex"
}
```

將 `remote_index_root` 設為同一個共用資料夾即可。搜尋結果將包含主節點發布的索引，除此之外無需其他設定。

> **安全提示：** 管理員後門（`Ctrl+Shift+Alt+A`）使用儲存在 `master_node_password` 中的密碼。在共用環境中部署前，請務必修改預設密碼（`"1235"`）。

---

## 編譯為獨立執行檔

```bash
build_portable.bat
```

需要 PyInstaller。輸出位於 `dist/DualPaneFileManager/`，為可攜式資料夾形式。  
安裝程式腳本（`installer.iss`）使用 Inno Setup 進行打包。

---

## 專案結構

```
Dual_pane_file_manager/
├── core/                   # 核心業務邏輯 — 零 PyQt 引入
│   ├── config_manager.py   # config.json + theme.json 讀寫
│   ├── file_ops.py         # 所有磁碟 I/O（複製、移動、壓縮、刪除）
│   ├── interfaces.py       # 所有 View 的 abc.ABC 合約定義
│   └── models/             # 資料結構
├── ui/
│   ├── panes/              # ExplorerPane — 複合視圖
│   ├── presenters/         # MVP Presenters
│   ├── widgets/            # 可重用元件（預覽、搜尋、對話框）
│   └── windows/            # 主視窗
├── network_search/         # SQLite FTS5 索引器與搜尋引擎
├── tests/                  # pytest 單元測試
├── langs/                  # 多語言 — zh_TW.json、en_US.json
├── styles.qss              # Qt 樣式表（Python 中不含顏色）
├── theme.json              # 目前啟用的色彩主題
├── config.example.json     # 設定範本
└── main.py                 # 程式入口
```

架構嚴格遵循 **MVP（Model-View-Presenter）**：
- `core/` 不引入任何 PyQt
- 所有 View 均實作 `core/interfaces.py` 中的 `abc.ABC` 介面
- Presenter 透過建構子注入接收 View 與 Model 實例

---

## 相依套件

```
Python          3.10+
PyQt6           6.10+
PyQt6-WebEngine 6.10+   （預覽面板）
PyMuPDF                 （PDF 預覽）
Send2Trash              （資源回收筒）
winshell + pywin32      （Windows Shell 整合）
openpyxl                （XLSX 預覽）
python-docx             （DOCX 預覽）
mutagen                 （音訊 Metadata）
Markdown                （Markdown 預覽）
Pillow                  （影像處理）
py7zr                   （7z 解壓縮）
```

一次安裝所有套件：

```bash
pip install -r requirements.txt
```

> 本應用程式僅支援 Windows。`winshell` 與 `pywin32` 在 macOS / Linux 上沒有對應套件。

---

## 執行測試

```bash
pytest tests/
```

---

## 授權

MIT — 詳見 [LICENSE](LICENSE)
