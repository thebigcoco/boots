# Yahoo Auctions Lucchese / Alden boots report

最新報告：`index.html`

內容包含 Lucchese、Alden 鞋靴商品，篩選尺寸為 7D、7E、7.5D，並提供品牌、產品型號、尺寸、特殊皮革、楦頭（Last）、價格（日幣／台幣）、結標時間等欄位。

- **New!**：與前一份報告比對，標示新出現的拍賣（紅色標籤）
- **379X**：Alden 商品會抓取完整拍賣描述，若提及木型 379X 會標示（藍色標籤）

每次執行 `scrape_yahoo_auctions_lucchese_alden.py` 會依日期產生 `yahoo_auction_lucchese_alden_YYYY-MM-DD.html/.json`，並同步更新 `index.html` 為最新版本。
