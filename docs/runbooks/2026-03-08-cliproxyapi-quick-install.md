# CLIProxyAPI 快速安裝與啟動（免檢測版）

適用主機：`34.101.230.107`  
適用用戶：`lianping1230`  
目標：安裝/啟動 CLIProxyAPI，並讓管理頁可從外網訪問。

## 1) 一鍵直連服務器（固定命令）

在本機 PowerShell 直接執行：

```powershell
ssh -i "D:\temp\aws\keygool_anpingli" -p 22 lianping1230@34.101.230.107
```

注意：如果登入後畫面看起來卡住、沒有提示符，直接按一次 Enter 繼續。

## 2) 安裝（已安裝可跳過）

```bash
cd ~
curl -fsSL https://raw.githubusercontent.com/brokechubb/cliproxyapi-installer/refs/heads/master/cliproxyapi-installer | bash
```

## 3) 開啟遠程管理

```bash
cd ~/cliproxyapi
sed -i 's/^  allow-remote:.*/  allow-remote: true/' config.yaml
```

## 4) 啟動並設為自啟

```bash
systemctl --user daemon-reload
systemctl --user enable --now cliproxyapi
```

## 5) 放行 8317 端口

```bash
sudo ufw allow 8317/tcp
```

## 6) 確保登出後仍保持運行

```bash
sudo loginctl enable-linger lianping1230
```

## 7) 最小驗證

在服務器內：

```bash
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8317/management.html
```

返回 `200` 即正常。

在本機瀏覽器打開：

`http://34.101.230.107:8317/management.html`
