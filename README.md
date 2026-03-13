# 1ynticket - Discord 開單系統

## 功能

### 開單面板
- `/setup-product` - 設置商品購買開單面板（下拉式選單）
- `/setup-inquiry` - 設置意見單/洽群開單面板（按鈕）

### 超級管理員專用
- `/admin-setup-product` - 在任意頻道/類別建立商品面板
- `/admin-setup-inquiry` - 在任意頻道/類別建立意見單面板

### 商品管理
- `/add-product` - 新增商品
- `/remove-product` - 移除商品
- `/list-products` - 列出所有商品
- `/set-stock` - 設定庫存
- `/set-price` - 設定工單金額

### 系統管理
- `/sync` - 同步斜線命令
- `/restart` - 重啟機器人
- `/refresh` - 重整機器人狀態

## 部署

透過 Railway 連接此 GitHub 倉庫自動部署。

### 環境變數
- `DISCORD_TOKEN` - Discord Bot Token
