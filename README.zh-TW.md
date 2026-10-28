# TasteCompass

> 依你的**興趣口味**(Qloo)+ **學術方向、預算、IELTS**,推薦適合的**英國城市與碩士科系**,並從截止日倒推出**申請時程**。

這份是給組員看的專案介紹:看完就知道它在做什麼、怎麼跑、現在做到哪、接下來還缺什麼。

---

## 一分鐘看懂

一般留學推薦只看排名和學費。TasteCompass 多看一件事:**你會不會喜歡住在那個城市**。

1. 你輸入喜歡的東西(Radiohead、精品咖啡、健行、吉卜力…)。
2. Qloo 算出每個英國城市裡有多少你會喜歡的地方 → **城市口味分數**。
3. 再加上科系內容是否符合你想念的領域、學費是否在預算內、IELTS 夠不夠 → **每個科系的適配度**。
4. 對推薦的科系,從官網截止日倒推出「何時考 IELTS、何時找推薦人、何時交件」。
5. (選用)Claude 用白話解釋結果、回答「如果預算多 £3,000 呢?」這類問題 —— 但**數字一律來自資料檔**,假設性問題會重跑真的評分,Claude 不會自己編。

```
適配度 Fit = 0.35 × 口味(Qloo) + 0.35 × 學術 + 0.20 × 預算 + 0.10 × 語言
```

權重可以在網頁上用滑桿調。官網上查不到的資料一律給中性 0.5,並在畫面上標示 **unverified**,不會亂猜。

---

## 現在的狀態

| 部分 | 狀態 | 說明 |
| --- | --- | --- |
| 網頁介面(全英文) | ✅ 可用 | 表單、城市排名、科系卡片、時程、比較表、下載報告 |
| 學術 / 預算 / 語言評分 | ✅ 真實資料 | 來自 `data/programs.json`(官網整理) |
| 申請時程、截止日 | ✅ 真實資料 | 分輪次(如 Edinburgh)會自動挑下一個來得及的輪次 |
| **口味分數、推薦地點** | ⚠️ **Mock 假資料** | 還沒有 Qloo API key。畫面頂端會顯示 MOCK MODE |
| 顧問團(4 角色)、申請追蹤、行事曆匯出、分享連結 | ✅ 可用 | 評分與判斷全部來自資料,不需要任何 key |
| Taste DNA、A Week in Your City | ⚠️ 用 mock 資料 | 功能完成;要接上 Qloo 才是真的口味與地點 |
| 顧問團 AI 語氣(OpenAI) | ⚠️ 未實測 | 程式完成、用假回應測過;需要 `OPENAI_API_KEY` |
| Ask TasteCompass(Claude) | ⚠️ 未實測 | 程式完成、用假 Claude 測過流程;需要 Anthropic API key 才能真的用 |
| 部署 / git repo | ❌ 未做 | 目前只能在自己電腦跑 |

> **Mock 模式的口味分數不能當成 Qloo 的結果展示。** 它只認得少數預設興趣(Radiohead、Studio Ghibli、Specialty coffee、Hiking、Banksy、Harry Potter、Taylor Swift 等),輸入其他興趣幾乎沒有反應。

---

## 快速開始

只需要 Python 3.10 以上,**不用安裝任何套件**。

```bash
cd tastecompass
python web.py
```

打開 http://localhost:8000 → 按 **Find my programmes**。關掉:在終端機按 Ctrl-C。

只想要文字報告(不開網頁):

```bash
python run.py profiles/mode_b.json --mock --out out/report_mode_b.md   # 模式 B:只決定了國家
python run.py profiles/mode_d.json --mock --out out/report_mode_d.md   # 模式 D:已經選好科系
```

### 有 API key 之後

| 要開啟的功能 | 需要 | 設定(PowerShell) | 設定(Git Bash / macOS) |
| --- | --- | --- | --- |
| 真的 Qloo 口味分數 | Qloo hackathon key | `$env:QLOO_API_KEY="你的key"` | `export QLOO_API_KEY=你的key` |
| Ask TasteCompass | `pip install anthropic` + Anthropic key | `$env:ANTHROPIC_API_KEY="你的key"` | `export ANTHROPIC_API_KEY=你的key` |
| 顧問團 AI 語氣 | OpenAI key(不用裝套件) | `$env:OPENAI_API_KEY="你的key"` | `export OPENAI_API_KEY=你的key` |

模型可用 `OPENAI_MODEL`(預設 `gpt-4o-mini`)、`TASTECOMPASS_MODEL`(預設 `claude-opus-5-5`)更換。**key 只放環境變數,不要寫進程式或 commit 進 repo。**

設好後**重開 `python web.py`** 就會自動切換,不用改程式。啟動時終端機會印出目前用的是 mock 還是 live。

---

## 網頁功能導覽

左邊填條件,右邊看結果。第一次按下按鈕後,**改任何條件都會自動重算**(興趣欄位是離開輸入框才重算,避免一直打 Qloo API)。

- **Scope(已經決定到哪一層)**:A 都沒決定 / B 決定英國 / C 決定城市 / D 決定科系。已決定的部分是硬性限制;模式 D 會另外列出「範圍外但更適合」的選項。
- **City taste fit**:城市口味排名,點城市可以展開看「你可能會喜歡的地點」和原因(because you like X + Y)。
- **Recommended programmes**:適配度拆成四項分數、官網學費 / IELTS / 入學條件 / 課程、倒推時程、官網來源與查詢日期。
- **Compare all programmes**:點欄位排序;▲▼ 是跟上一次計算相比的名次變化;勾 2–3 個並排比較。
- **Your Taste DNA**:把你的興趣整理成口味特質和「口味原型」(例如 Indie Explorer × Culture Seeker),並顯示每個城市涵蓋你多少口味。
- **A week in [city]**:用 Qloo 推薦的地點排出你在該城市的第一週(平日晚上 + 週末),可切換城市。
- **Advisory panel**:🎓 Admissions、💷 Finance、🎧 Lifestyle、💼 Career 四位顧問各自給 strong / mixed / concern / unverified 判斷和理由,Chair 彙整(例如「Split decision」)。判斷全部來自資料與規則;有 OpenAI key 時可按 **Let the advisors speak (AI)** 讓 AI 用各角色語氣改寫,但不會改變任何判斷或數字。
- **申請追蹤**:時程每一步和文件清單都能打勾,存在瀏覽器裡;**Add to calendar (.ics)** / **Export all deadlines** 可匯入 Google Calendar。
- **Copy share link**:把目前條件編進網址,打開就會重現同一組結果。
- **Ask TasteCompass**:Claude 解釋與追問(需要 key)。
- **Agent trace**:agent 每一步做了什麼;**Download Markdown report** 下載整份報告。

### 建議 demo 流程(約 3 分鐘)

1. 用預設的模式 B 範例按 **Find my programmes**,介紹城市口味排名和前三名科系(分數拆解、unverified 標示、倒推時程)。
2. 把預算改成 45000、Budget 權重拉到 0.8 → Glasgow 從第 2 升到第 1,比較表出現 ▲▼。展示「你更在乎錢時推薦怎麼變」。
3. 在比較表勾 2–3 個科系並排比較。
4. 點 **Mode D: programmes decided** → 展示 IELTS 差 0.5 的提醒、Edinburgh Round 2 截止日、範圍外的替代選項。
5. (有 key 時)按 **Explain these results**,再問「What if my budget were £3,000 higher?」。

> Demo 時只用兩個預設範例,不要讓人現場輸入任意興趣(mock 模式下會看起來沒反應)。

---

## 專案結構

```
tastecompass/
├── web.py                 網頁伺服器(標準庫):GET / 、GET /api/meta、POST /api/run、POST /api/chat
├── static/index.html      整個網頁(單一檔案,不需要建置)
├── run.py                 CLI:輸出 Markdown 報告
├── probe.py               拿到 Qloo key 後第一個要跑的檢查腳本
├── data/
│   ├── programs.json      11 個科系(官網整理;null = 官網查不到)
│   └── cities.json        6 個城市;fallback_tags、cost_tier 是草稿
├── profiles/              兩組範例使用者(模式 B、模式 D)
├── mock/catalog.json      假的 Qloo 實體,有 key 後就不會用到
└── tastecompass/
    ├── agent.py           主流程:判斷模式 → 查興趣 → 各城市口味(平行查詢)→ 評分 → 時程
    ├── qloo.py            真實 Qloo client(重試、快取)與 mock client,介面相同
    ├── scoring.py         四項分數與適配度公式
    ├── planner.py         從截止日倒推時程、文件清單
    ├── report.py          Markdown 報告
    ├── panel.py           顧問團:四個角色的分數、判斷、理由與 Chair 彙整(不靠 LLM)
    ├── narrate.py         顧問團 AI 語氣(選用,OpenAI):只改寫文字,不改判斷
    ├── dna.py             Taste DNA:口味特質、口味原型、城市涵蓋率
    └── explain.py         Claude 解釋層(選用):what_if 工具會重跑真的評分
```

想改評分邏輯 → `scoring.py`;想改時程 → `planner.py`;想改畫面 → `static/index.html`。網頁和 CLI 共用同一套 Python 邏輯,改一處兩邊都會生效。

---

## 待辦清單

### 最優先
- [ ] **申請 / 確認 Qloo hackathon API key**(比賽核心,沒有它口味分數都是假的)
- [ ] 拿到 key 後跑 `python probe.py "Radiohead" "Hiking"`,確認三件事:
  1. `/search` 能把興趣文字轉成 entity_id。
  2. `/v2/insights` 加上城市條件後,不同城市的 affinity 有沒有明顯差異(差異很小就改用 `cities.json` 的 `fallback_tags` 比對)。
  3. 回應欄位和 `tastecompass/qloo.py` 開頭註解寫的一致。API 端點與參數是從其他參賽者的公開專案整理的,**拿到官方文件後請再對一次**。地點的地址、標籤欄位名稱是推測的,對不上的話改 `agent.py` 的 `place_evidence()`。

### 資料
- [ ] KCL、Imperial、LSE、Bristol FinTech MSc 只有連結:學費、截止日、語言門檻要去官網補。
- [ ] UCL、Manchester 是 2026 入學資料,Leeds 是 2025,要更新成 2027(畫面會顯示舊資料警告)。
- [ ] UCL「English Level 3」、Bristol「Profile C」要到各校語言要求頁換算成 IELTS,填進 `ielts_overall`。
- [ ] 檢查 `cities.json` 的 `fallback_tags` 和 `cost_tier`(目前是草稿)。
- [ ] 想加科系:照 `programs.json` 的格式新增一筆即可。

### 評分(評審可能會問)
- [ ] 資料缺很多的科系也能排很前面(缺的項目給 0.5),考慮加「資料完整度」扣分。
- [ ] 城市口味分數是 6 個城市互相比較後拉成 0–1,最後一名一定是 0.00,看起來像「完全不合」。
- [ ] 時程沒有依個人調整:IELTS 已達標還是會叫你去考。
- [ ] 模式 A 和 B 目前結果一樣(資料只有英國)。

### 繳交
- [ ] 英文版 README(給評審)
- [ ] 建 git repo、推上 GitHub
- [ ] 部署成公開網址(Vercel / Render)
- [ ] Demo 影片
- [ ] 評測:同一組問題問通用 LLM 和 TasteCompass,比較截止日與學費的正確率

### 工程
- [ ] `scoring.py`、`planner.py` 的單元測試
- [ ] Claude 對話紀錄目前存在記憶體、沒有上限,部署前要加限制
