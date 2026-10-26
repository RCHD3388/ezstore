請在目前的 EZStore 專案建立第二個獨立的 Agent Application，名稱為 **Sales & Customer Insight Agent**，ADK app name 使用 `sales_insight_agent`。

**本次只能新增或修改新的 `agent2/` 內容；嚴禁修改既有的 `agent/`（包含已完成的 `quotation_agent`）、`frontend/`、`backend/`、`mcp_server/`、既有 Docker Compose、seed data 或其他已完成的第一個 Agent 相關檔案。**

## 0. 已經提供、不需要重新開發的部分

EZStore 已經提供 Backend REST API 與測試資料。第二個 Agent 只需要透過現有 REST API **唯讀取得資料**。

請以專案現有 Swagger `docs.go` 的 API 定義為準，主要使用：

- `GET /api/v1/customers?search=<keyword>`：搜尋客戶
- `GET /api/v1/customers/{id}`：取得客戶詳細資料
- `GET /api/v1/quotations?customer_id=<id>`：取得指定客戶的報價單
- `GET /api/v1/orders?customer_id=<id>`：取得指定客戶的訂單
- `GET /api/v1/quotations/{id}`：需要詳細資料時取得單一報價單
- `GET /api/v1/orders/{id}`：需要詳細資料時取得單一訂單

不要修改既有 MCP Server，也不要新增功能到既有 quotation MCP tools。

第二個 Agent 使用自己的唯讀 REST API client / internal tools 即可。

Frontend 不需要整合第二個 Agent。開發與驗收使用 `agents-cli playground`。

---

## 1. Agent 功能與情境需求

第二個 Agent 專門處理 **customer sales insight**，只能執行以下五個功能。

### 1.1 Customer Overview

例如：

`請幫我查看史塔克工業的客戶銷售概況`

回覆至少包含：

- 客戶名稱
- customer level
- credit score
- quotation 數量
- order 數量
- quotation total value
- order total value
- order status 的簡單摘要

所有數字必須由 Backend API 的實際資料計算，不可由 LLM 猜測。

### 1.2 Customer Quotation History

例如：

`請列出史塔克工業的報價歷史`

回覆該客戶的 quotation，包含至少：

- quotation number
- status
- total price
- created date

### 1.3 Customer Order History

例如：

`請列出史塔克工業的訂單歷史`

回覆該客戶的 order，包含至少：

- order number
- status
- total price
- created date
- linked quotation（如果存在）

若 `quotation_id` 為空，清楚表示這是一張沒有關聯報價單的 standalone order。

### 1.4 Quotation-to-Order Conversion Analysis

例如：

`分析史塔克工業有哪些報價已經轉成訂單`

取得該客戶的 quotations 與 orders 並進行比對。

判定規則：

- 若某個 order 的 `quotation_id` 等於 quotation 的 `id`，該 quotation 視為已轉成 order。
- `quotation_id = null` 的 standalone order 不算 quotation conversion。
- 回覆哪些 quotations 已有關聯 order，以及哪些尚未有關聯 order。
- 可回覆 `converted quotations / total quotations` 的比例，但必須使用上述規則計算。

### 1.5 Customer Comparison

例如：

`比較史塔克工業和膠囊公司的銷售活動`

比較兩個 customer，至少包含：

- customer level
- credit score
- quotation count
- quotation total value
- order count
- order total value
- quotation-to-order linked conversion count

只描述 Backend 資料能支持的差異，不要自行推測客戶未來行為或商業價值。

---

## 2. Guardrails 與資料規則

### 2.1 Read-only

這個 Agent **只能讀取資料**。

所有 Backend request 必須使用 HTTP `GET`。

禁止呼叫：

- POST
- PUT
- PATCH
- DELETE
- quotation duplicate
- quotation publish
- order creation
- customer/product/quotation/order 的任何新增、修改或刪除操作

即使使用者明確要求，也必須拒絕。

這個限制要由程式邏輯保證，不能只寫在 prompt 裡。

### 2.2 Off-topic

如果使用者詢問與五個 sales/customer insight 功能無關的內容，例如：

- 天氣
- 一般聊天
- 修改 customer
- 修改 product
- 修改 quotation
- 建立或修改 order
- 要求執行第一個 quotation agent 的操作

Agent 要禮貌拒絕並說明只能提供 Sales & Customer Insight 的五項唯讀功能。

### 2.3 Missing information

如果功能需要 customer name，但使用者沒有提供，Agent 必須追問。

例如：

`幫我查看客戶銷售概況`

→ 詢問使用者要查看哪一個 customer。

使用者下一句補上 customer name 後，要能繼續原本的操作。

Customer Comparison 缺少其中一個 customer 時也使用相同規則。

### 2.4 Customer matching

先使用：

`GET /api/v1/customers?search=<customer_name>`

搜尋 customer。

- 若只有一個合理結果，使用該 customer。
- 若沒有結果，清楚表示找不到。
- 若有多個可能結果，不要自行猜測，要求使用者確認。

### 2.5 Data grounding

所有：

- customer information
- counts
- totals
- statuses
- quotation/order relationships
- comparison results

都必須直接來自 Backend API 或由 Backend API 回傳資料做 deterministic calculation。

LLM 不得自行產生業務數字。

API 有 pagination 時必須正確處理，不要假設第一頁一定包含全部資料。

---

## 3. 技術需求

### 3.1 Project isolation

建立新的：

```text
agent2/
```

第二個 Agent 的所有 source code、environment example、tests、eval 與 README 都放在 `agent2/`。

不要修改現有 `agent/`。

### 3.2 ADK Agent

使用：

- Python 3.12
- Google ADK 2.10+
- google-agents-cli
- uv

Agent 使用 ADK Graph Workflow。

建議流程：

```text
START
  ↓
load_context
  ↓
classify_intent
  ↓
route
  ├── customer_overview
  ├── quotation_history
  ├── order_history
  ├── conversion_analysis
  ├── compare_customers
  ├── clarify
  ├── reject_write_request
  └── off_topic
  ↓
respond
```

只有 `classify_intent` 使用 LLM。

API selection、HTTP method、計算、拒絕 write operation 與 routing 都由程式邏輯決定。

ADK app name：

```text
sales_insight_agent
```

最終輸出節點名稱：

```text
respond
```

### 3.3 Scaffold

使用 google-agents-cli 建立新的 scaffold，結果放入 `agent2/`，不要覆蓋現有 `agent/`。

Agent directory / root agent name 使用：

```text
sales_insight_agent
```

使用 `uv` 管理 dependencies，並在 `agent2/` 產生自己的 `pyproject.toml` 與 `uv.lock`。

### 3.4 REST API Client

在 `agent2/` 建立自己的 read-only API client/internal tools。

Backend URL 由環境變數提供，例如：

```text
BACKEND_URL=http://localhost:8080/api/v1
```

不要把 Backend URL 分散 hard-code 在各功能中。

HTTP client 必須保證 Agent 的資料操作只能使用 GET。

### 3.5 Model configuration

Model name 使用環境變數：

```text
AGENT_MODEL
```

Credential 使用：

```text
GEMINI_API_KEY
```

不可把 API key 寫入程式碼或 Git。

---

## 4. 測試需求

至少建立以下測試。

### Core functions

1. `customer_overview`
2. `quotation_history`
3. `order_history`
4. `conversion_analysis`
5. `compare_customers`

### Guardrails

至少測試：

1. `off_topic_weather`
2. `reject_write_request`
3. `clarify_then_complete`

`reject_write_request` 要確認 Agent 沒有發出任何 POST、PUT、PATCH 或 DELETE request。

---

## 5. 實作順序與驗收方式

請依照以下順序執行，**每個 Stage 完成後停止，先告訴我完成了什麼、我要驗證什麼、預期看到什麼；等我確認後才進入下一個 Stage。**

### Stage 1 — Read-only Backend access

確認現有 EZStore Backend 正常。

使用 GET API 驗證：

- customer search
- quotations by customer
- orders by customer

不要修改任何資料。

驗收時顯示實際取得的 customer、quotation 與 order 基本資料。

### Stage 2 — Build the Second Agent

在 `agent2/` scaffold `sales_insight_agent`。

完成：

- REST API client
- intent model
- Graph Workflow
- 五個功能
- clarify
- reject_write_request
- off_topic
- respond

先執行 unit tests。

### Stage 3 — Local Playground Acceptance

使用：

```text
agents-cli playground
```

驗證以下情境：

1. Customer Overview
2. Customer Quotation History
3. Customer Order History
4. Quotation-to-Order Conversion Analysis
5. Customer Comparison
6. Off-topic request
7. Write/change-data request
8. Missing customer → ask → user supplies customer → continue

每個結果必須與 Backend 實際資料一致。

### Stage 4 — Eval and Safety Verification

執行 Second Agent 自己的 tests/eval。

確認：

- 五個功能都能正確完成
- off-topic 被拒絕
- write requests 被拒絕
- missing information 能追問並繼續
- Backend data 在測試前後沒有因第二個 Agent 被修改

### Stage 5 — Documentation

只更新：

```text
agent2/README.md
```

說明：

- Second Agent 的用途
- 五個功能
- Workflow
- environment variables
- local run
- tests/eval

最後列出本次新增的檔案，並用 Git diff/status 確認沒有修改：

```text
agent/
frontend/
backend/
mcp_server/
scripts/seed-test-data.sql
```