# CLAUDE.md

## 1. 專案概述 (Project Overview)
本專案為一個具備 **網絡搜尋功能** 的 **雙欄檔案瀏覽器**。
- 技術棧: Python 3.10+, PyQt6 (UI), SQLite (Search Index)。
- 設計模式: 嚴格遵守 **MVP (Model-View-Presenter)** 架構。

## 2. 目錄架構規範 (Folder Structure)
所有程式碼異動必須遵循以下實體路徑：

- `/core`: 存放核心業務邏輯 (Business Logic)。
  - `config_manager.py`: 負責 `config.json` 與 `theme.json` 的讀取、儲存與預設值管理。
  - `interfaces.py`: 使用 `abc.ABC` 定義 View 的行為合約 (如 `IExplorerView`)。
  - `file_ops.py`: 封裝所有檔案系統操作 (I/O)。
  - `/models`: 存放各模組的資料結構與模型。

- `/ui`: 存放介面相關程式碼。
  - `/panes`: 組合 View 元件 (如 `ExplorerPane`)。
  - `/widgets`: 基礎 UI 元件 (如 `FileTreeView`, `FileListView`)。
  - `/presenters`: 存放所有 Presenter 類別，處理 View 與 Model 之間的邏輯。
  - `/windows`: 主視窗與對話框。

- `/network_search`: 專門存放網絡搜尋模組的邏輯與資料庫相關處理。

- `/tests`: 存放對應邏輯的 pytest 單元測試。

- **根目錄 (/)**: 存放 `main.py` 入口點、`.json` 設定檔、`.qss` 樣式檔及打包指令。

## 3. MVP 模式約束 (Architecture Constraints)

### Model (資料層)
- **職責**: 處理資料存取 (Disk/DB/JSON) 與純邏輯運算。
- **禁令**: 嚴禁引入 `PyQt`、`PySide` 或任何 UI 元件。
- **核心**: `ConfigManager` 即為 `ConfigModel` 的具體實作。

### View (顯示層)
- **職責**: 負責顯示與接收使用者輸入。
- **介面優先**: 必須繼承自 `core/interfaces.py` 中定義的 `abc.ABC` 介面。
- **樣式限制**: 嚴禁在 Python 代碼中 Hard-code 顏色/字體，統一由 `styles.qss` 或 `theme.json` 控制。

### Presenter (中介層)
- **職責**: 核心控制邏輯。負責從 Model 獲取資料並填入 View，處理使用者交互邏輯。
- **相依性注入**: 初始化時必須接收 Model 與 View 實例。

## 4. 開發準則 (Coding Standards)
- **組態管理**: API、路徑、逾時等參數必須存在 `config.json`，由 `ConfigManager` 管理。
- **路徑處理**: 使用相對路徑，並考慮打包後 (PyInstaller) 的路徑轉換。
- **強型別要求**: 函式定義必須包含 Type Hints (例: `data: dict[str, Any] -> bool`)。
- **錯誤處理**: 資源讀取失敗應自動建立預設值，並透過 View 介面告知使用者。

## 5. 檔案行數限制 (File Size Constraints)

### 硬性上限 (Hard Limit)
- **單一 `.py` 檔案** 不得超過 **600 行** (含註解與空行)。
- **單一 class** 不得超過 **300 行**。
- **單一 function/method** 不得超過 **80 行**。

### 警示閾值 (Warning Threshold)
- 檔案達到 **480 行** (80%) 時，應評估是否需要拆分。
- Presenter 達到 **250 行** 時，檢查是否有應下放至 Model 的邏輯。
- View (Widget/Pane) 達到 **300 行** 時，檢查是否應拆分為更小的子元件。

### 拆分指引
- **Model 過大**: 依領域拆分至 `/core/models/` 下的子模組。
- **Presenter 過大**: 拆分為多個 Presenter (如 `FilePresenter` + `SearchPresenter`)，或將輔助邏輯抽至 `/core` 的 helper 模組。
- **View 過大**: 將子區塊抽為 `/ui/widgets` 下的獨立 widget。

### 例外
- 純資料定義檔 (如 dataclass 集中定義、`interfaces.py`) 與自動產生的 `.qss`/`.json` 不受此限制，但仍建議 < 800 行。
- **`/tests` 目錄不受行數限制**，但仍鼓勵依被測模組拆分測試檔。

## 6. 常用指令 (Common Commands)
- 啟動程式: `python main.py`
- 執行測試: `pytest tests/`
- 編譯打包: 執行 `build_portable.bat` (Windows)

## 7. 行為約束 (Behavioral Constraints)
- **禁止行為**: 除非明確要求，否則禁止修改現有的 interface 或 abstract class 定義。
- **獨立性**: 新功能應儘量透過繼承或新增檔案達成，而非直接改動原始核心邏輯。
