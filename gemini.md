---
trigger: always_on
---

遵循架構：MVP (Model-View-Presenter)
Model: 負責純資料（Data）與業務邏輯（Business Logic）。

ConfigModel: 專門負責 config.json 的讀取與寫入，不准包含任何 UI 邏輯。

View: 負責顯示與接收輸入。

ConfigView: 專供使用者設定參數的 UI（如 Entry, Checkbox）。

Presenter: 核心中介者。

負責將 ConfigModel 的資料填入 ConfigView，並在儲存時驗證合法性。

程式設計原則 (Constraints)
Externalized Configuration: 所有可能變動的參數（如 API URL、存檔路徑、超時時間）嚴禁硬編碼 (Hard-coding)，必須存在 config.json 中。

介面隔離 (Interface First): 必須使用 abc.ABC 定義 View 的合約。

相依性注入: Presenter 在初始化時才接收特定的 Model 與 View。

輸出格式規範
邏輯拆解: 說明 JSON 結構如何與 UI 欄位對應。

程式區塊: 標註 MVP 各層，並展示 ConfigHandler 類別。

單元測試建議: 確保在沒有 UI 的情況下也能測試 JSON 讀寫邏輯。

禁止行為: 除非明確要求，否則禁止修改現有的 interface 或 abstract class 定義。

獨立性: 新功能應儘量透過繼承或新增檔案達成，而非直接改動原始核心邏輯。
