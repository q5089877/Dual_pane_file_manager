# Dual Pane File Manager — 產品定位與功能清單

## 一、程式定位

**面向對象**：在 Windows 企業/辦公室環境中，需要管理本機與網路磁碟（NAS / K: 槽）的知識工作者、IT 人員。  
**核心痛點**：Windows 檔案總管對深層 NAS 資料夾瀏覽效率差、跨磁碟搜尋慢、缺乏跨欄操作支援。  
**定位**：介於 Total Commander（雙欄操作）與 Everything（索引搜尋）之間，深度整合本機與 K: 槽 SQLite 索引，提供「瀏覽 + 操作 + 搜尋 + 預覽」一體化工作台。

---

## 二、架構概覽

```
UI 層 (PyQt6)
  ├── MainWindow          主視窗：工具列、雙側 CustomTabWidget
  ├── ExplorerPane        單個檔案瀏覽欄（View 適配器）
  │     ├── FileTreeView  詳細清單視圖（QTreeView）
  │     ├── FileListView  圖示/縮圖視圖（QListView）
  │     └── NavPanel      首頁面板（磁碟 + 常用資料夾）
  ├── PreviewPanel        嵌入式預覽（接管對側欄）
  └── 各 Dialog/Popup     設定、搜尋、重命名、常用路徑...

Presenter 層
  ├── ExplorerPresenter   路徑歷史、刪除、建立資料夾、超級貼上
  └── MainWindowPresenter 系統計時、背景掃描排程

Model / Core 層
  ├── ConfigManager       config.json / theme.json 讀寫、多語言
  ├── FileOps             所有磁碟 I/O、回收桶、壓縮、OneDrive 偵測
  └── IndexManager        SQLite 搜尋索引（master.db / personal.db）

network_search/
  ├── IndexManager        搜尋引擎（multi-DB ATTACH）
  └── ScannerWorker       背景掃描 → 寫入 DB → 發佈 NAS slot
```

架構規範：嚴格 MVP；View 不含業務邏輯；Model 禁止引入 PyQt；樣式統一由 `styles.qss` + `theme.json` 控制。

---

## 三、細部功能清單

### 3.1 檔案瀏覽

| 功能 | 說明 |
|------|------|
| **雙欄布局** | 左右兩側各自獨立，水平分割線可拖動 |
| **多分頁** | 每側最多 5 個分頁；分頁右鍵可新增/關閉/加書籤/輸出樹狀圖 |
| **三種視圖模式** | 首頁（`home://`）、詳細清單（TreeView）、圖示縮圖（GridView） |
| **導覽控制** | 上一頁 / 下一頁 / 上一層 / 首頁，支援鍵盤 Alt+Left / Alt+Right |
| **路徑列直接輸入** | Enter 確認導覽；輸入時自動清空搜尋列 |
| **Focus-follows-mouse** | 滑鼠移入哪側哪側自動獲得焦點（預覽模式除外） |
| **首頁 NavPanel** | 磁碟機清單（固定碟 + 抽取式）+ 常用資料夾（桌面/下載/文件等） |
| **Windows .lnk 捷徑解析** | 雙擊 .lnk 自動跳至目標路徑（優先 win32com，fallback Qt） |
| **Windows Quick Access** | 啟動時讀取使用者釘選的 Quick Access 資料夾，預設填入右側分頁 |
| **磁碟空間顯示** | 狀態列即時顯示目前磁碟剩餘 / 總計（背景非同步取得） |

---

### 3.2 搜尋

| 功能 | 說明 |
|------|------|
| **欄內即時搜尋列** | 每欄右上角搜尋框，支援關鍵字與萬用字元（`*` / `?`）過濾 |
| **過濾抽屜** | 點擊漏斗按鈕展開；大小篩選（全部/>1MB/>10MB/>100MB）+ 日期篩選（全部/今日/本週/本月） |
| **SQL 輔助過濾** | Debounce 200ms 後查 SQLite；命中路徑回寫 Proxy Model，O(1) 過濾，無 I/O 阻塞 |
| **Trusted 模式** | 目前路徑在 monitored_paths 內時，SQLite 結果被信任為完整，直接拒絕非命中檔案，效能最高 |
| **平面掃描（Everything 模式）** | 有搜尋條件時切換為平面結果視圖，背景遞迴掃描，50 筆一批推送，可中途取消 |
| **進階搜尋對話框（Ctrl+F）** | 跨 DB 全文搜尋（master.db / personal.db / NAS index_A/B）；支援大小/時間/副檔名篩選；顯示掃描進度 |
| **K: 槽深度索引搜尋** | 掃描深度可設定（`network_scan_depth`，預設 7 層）；結果直接在進階搜尋對話框列出 |

---

### 3.3 檔案操作

| 功能 | 快捷鍵 | 說明 |
|------|--------|------|
| **複製** | F4 / C / Ctrl+C | 含進度條 + 取消 |
| **移動** | F3 / X / Ctrl+X | 含進度條 + 取消；支援 Undo |
| **貼上** | Ctrl+V | 支援系統剪貼簿（`Preferred DropEffect` 判斷剪下/複製） |
| **超級貼上** | Ctrl+V（在視圖區） | 剪貼簿含圖片 → 存為 `剪貼圖_YYYYMMDD.png`；含文字 → 存為 `文字筆記_YYYYMMDD.txt` |
| **重新命名** | F2 | 原位編輯 |
| **時間戳記命名** | Alt+F2 | 在檔名末加 `_YYYYMMDD`（批次支援） |
| **批次重命名** | 右鍵 → 批次重命名 | 樣式替換對話框 |
| **版本副本（F6）** | F6 / Ctrl+V（同資料夾） | 自動產生 `filename_20260510.txt`，資料夾則壓成 zip |
| **新增資料夾** | F7 | 命名自動遞增避免衝突 |
| **刪除到回收桶** | Del | 可設定是否彈確認視窗 |
| **永久刪除** | Shift+Del | 強制彈確認視窗 |
| **Undo** | Ctrl+Z | 復原上次 move / rename / trash（trash 透過 winshell.undelete） |
| **壓縮 zip** | 右鍵 → 壓縮 | 背景執行，產生日期命名 zip |
| **解壓縮** | 雙擊壓縮檔 / 右鍵 → 解壓縮 | 支援 .zip / .tar.gz / .tar.bz2 / .tar.xz |
| **拖放移動** | 左鍵拖放 | 跨欄或同欄皆可 |
| **拖放複製** | 右鍵拖放 | 跨欄拖放 = 複製 |
| **拖放至垃圾桶** | 拖放至狀態列垃圾桶 | 送回收筒 |
| **拖放釘選** | 拖放至工具列 Pin 按鈕 | 自動靜默釘選 |
| **同資料夾貼上** | Ctrl+V（目的等於來源） | 自動版本命名，資料夾壓縮 |
| **覆蓋衝突確認** | 目標已存在時 | 彈窗列出衝突清單，Yes 覆蓋 |
| **Windows 內容** | 右鍵 → 內容 | 呼叫 Shell ShellExecuteExW "properties" |
| **開啟方式** | 右鍵 → 開啟方式 | rundll32 OpenAs_RunDLL |
| **Notepad 開啟** | 右鍵 → 以記事本開啟 | — |

---

### 3.4 預覽

| 功能 | 說明 |
|------|------|
| **嵌入式預覽（Space）** | 按 Space 接管對側欄顯示預覽，導覽鍵 ↑↓ 即時切換 |
| **圖片** | 背景載入 QImage（不阻塞 UI），主執行緒 QPixmap.fromImage() |
| **文字/原始碼** | Highlight.js via WebEngineView，語法高亮 |
| **PDF / .ai** | PyMuPDF 渲染；SD / HD 畫質切換按鈕；頁數 +/- 控制 |
| **CSV / XLSX / SQLite** | HTML table 前 15 行 |
| **STL** | trimesh 解析，顯示邊界框 + 體積 |
| **STEP / STP** | Three.js + occt-import-js WASM 3D 互動視圖 |
| **SLDPRT / SLDASM** | olefile 讀取 OLE 屬性（SolidWorks 檔案不需安裝 SW） |
| **OneDrive 未下載檔案** | 偵測 cloud placeholder 屬性，顯示「尚未下載」提示 |
| **Quick Look 對話框** | 類 macOS 無邊框浮動預覽，含 🗑️刪除 / 📤移到對側 / 📋複製 操作 |
| **預覽中的幽靈預防** | 刪除前自動跳到下一筆，避免白屏 |

---

### 3.5 書籤與導覽捷徑

| 功能 | 說明 |
|------|------|
| **釘選項目（Ctrl+D）** | 永久書籤；可加備忘（5 秒自動確認）；⭐ 標為重要置頂 |
| **釘選彈出窗** | 工具列 Pin 按鈕 → 彈出清單；右鍵可編輯備忘 / 解除釘選 |
| **書籤（自訂路徑）** | 每欄路徑列旁的書籤按鈕，快速跳轉；右鍵移除 |
| **常用路徑（⭐ Favorites）** | 工具列下拉選單，按群組分類；「➕ 將目前路徑加入」+ 「✏️ 管理」 |
| **Favorites 管理對話框** | 左欄群組（新增/重命名/移除）+ 右欄路徑（瀏覽選資料夾/移除） |
| **情境快照（Snapshots）** | 儲存兩欄所有分頁+分割比例；隨時一鍵還原 |

---

### 3.6 外觀與主題

| 功能 | 說明 |
|------|------|
| **3 套內建主題** | 調光護眼（預設深色）、深色 Dracula、亮色清爽 |
| **QSS + theme.json** | `styles.qss` 使用 `{{key}}` 插值，主題色全部在 `theme.json` 管理 |
| **Python 禁止硬碼顏色** | 所有 Python 端樣式只設 objectName，在 QSS 統一定義 |
| **即時主題切換** | 設定對話框變更主題後即時套用（`QApplication.setStyleSheet`） |
| **縮圖視圖** | 背景 ThumbnailManager，圖片/文件縮圖懶加載，96×96 格子 |

---

### 3.7 索引 / K: 槽搜尋架構

| 組件 | 說明 |
|------|------|
| **personal.db** | 本機所有固定磁碟（depth 99），idle 時背景掃描 |
| **master.db** | master node 掃描 monitored_paths（K: 槽），depth = network_scan_depth（預設 7） |
| **index_A.db / index_B.db** | NAS 上的 A/B 雙 slot；`current_version.txt` 決定啟用哪個（原子切換） |
| **consumer 模式** | 搜尋時 ATTACH NAS 上的 active slot DB，讀取 K: 槽索引 |
| **master 掃描排程** | 夜間自動掃描（可設定時、分）；手動「🔄更新」按鈕 |
| **排除設定** | `exclude_exts`（.tmp/.bak/.log 等）+ `exclude_dirs`（Archive/Old/Temp 等） |

---

### 3.8 AI Context 匯出

| 功能 | 說明 |
|------|------|
| **資料夾樹狀圖輸出** | 產生 `├── ` 格式樹狀結構，存為 .txt 並以記事本開啟（右鍵 / 分頁右鍵） |
| **AI 上下文匯出** | 遞迴掃描，產生含 Markdown 格式的檔案樹 + 原始碼內容，適合貼入 Claude/GPT |
| **匯出設定** | 白名單副檔名、黑名單資料夾、單檔大小限制、總大小限制、掃描深度 |

---

### 3.9 系統整合

| 功能 | 說明 |
|------|------|
| **GitHub 自動更新** | 啟動 5 秒後非同步查詢 GitHub Releases；有新版時狀態列顯示綠色「立即更新」按鈕 |
| **自更新腳本** | 下載 zip，產生 .bat 腳本解壓後重啟，然後呼叫 QApplication.quit() |
| **可攜模式** | 執行目錄有 `config.json` → 攜帶式模式；否則使用 `AppData\Local\SHL\DualPaneFileManager` |
| **PyInstaller 打包** | `build_portable.bat` + `get_resource_path()` 支援打包後路徑 |
| **OneDrive 感知** | 偵測 FILE_ATTRIBUTE_OFFLINE / RECALL_ON_DATA_ACCESS 等旗標，避免意外觸發下載 |

---

### 3.10 鍵盤快捷鍵彙整

| 快捷鍵 | 功能 |
|--------|------|
| F2 | 重新命名 |
| Alt+F2 | 時間戳記命名 |
| F3 / X | 移動到對側 |
| F4 / C | 複製到對側 |
| F5 | 重整 |
| F6 | 版本副本 |
| F7 | 新資料夾 |
| Space | 切換嵌入式預覽 |
| Del | 送回收桶 |
| Shift+Del | 永久刪除 |
| Ctrl+C / X / V | 系統剪貼簿複製/剪下/貼上 |
| Ctrl+D | 釘選/解除釘選 |
| Ctrl+F | 開啟進階搜尋 |
| Ctrl+Z | 復原上次操作 |
| Tab | 在同側循環切換分頁 |
| `` ` `` | 切換左右欄焦點 |
| Alt+Left / Right | 導覽上一頁 / 下一頁 |

---

### 3.11 多語言與設定

| 功能 | 說明 |
|------|------|
| **繁體中文 / 英文** | `langs/zh_TW.json` + `langs/en_US.json`；`config_mgr.get_text(key, fallback)` |
| **設定對話框（3 分頁）** | 外觀（主題/字型）、一般（Session 還原/刪除確認/搜尋上限/語言）、索引（Master 設定/深度/排除清單/夜間排程） |
| **Toast 通知** | 右下角彈出，自動 3 秒消失，支援 info / success / warning / error 風格 |
| **Session 還原** | 關閉時儲存左右各分頁路徑 + 分割比例，下次啟動自動還原 |
| **兩側同路徑警告** | 兩欄顯示同一路徑時，中間顯示橘色警告條 |

---

## 四、技術棧

- **語言**：Python 3.10+  
- **UI**：PyQt6（QMainWindow + QWidget 自訂元件）  
- **搜尋索引**：SQLite 3（WAL 模式，多 DB ATTACH）  
- **預覽引擎**：PyMuPDF（PDF）、PyQt6-WebEngine（HTML/JS）、trimesh（STL）、olefile（SolidWorks）  
- **檔案操作**：send2trash（回收桶）、winshell（還原）、win32com（Quick Access / .lnk）  
- **打包**：PyInstaller + `build_portable.bat`  
