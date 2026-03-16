import requests


# 每隔60天需要刷新令牌hotmail /outlool 令牌
# 將你的完整格式貼在這裡 (已去敏)
SELLER_DATA = "JefferyFerguson8298@hotmail.com----raoxg9331----9e5f94bc-e8a4-4e73-b8be-63364c29d753----M.C508_SN1.0.U.-CqQC0ALcqS2djvi8WUgm*8ItpuGnSvZ*s3zysVBhZcxnOrORVanS70BXG6WIH8F6l4PYv8w430dzmaG2dM*H6kIQipg**FpY3YY4cSESuqCDMxj7qBMEykrPnx4wmJeiB4PSQ90GOATPgZm9MlJXye87EKrvlVKusiaL3vdMMQmpM!UFcLTvScwpBdVwg1wC0ZjmX8JH7xvpK4hwaNrH*JAGnF407!5bJW46wBYE2IJ4wl6*BOCgD2VbblsU0OdMNKTYuCUy4H0yf1AP*4OPPsyROf0NsZtaeRShCWgf3Cl6R7xpY6zzu3kvo4EpRIeuEYm*C*JBB!9YpSn7Co9tg90r6pI0QKkyP4ubtrFu6ScI1FzmEncIRbSPhXvje2f5B*1VyO6omhZKKGjtA2DU7VkI8j4ZMDD70cwu9G*ILKTGzIVIG2GDlGkcYS58cug30UbCuOX6TeT!va2zjpXB0Rg$"
def refresh_microsoft_token(data_string):
    try:
        # 1. 解析格式
        parts = data_string.split("----")
        email = parts[0]
        client_id = parts[2]
        old_refresh_token = parts[3]
        
        print(f"[*] 正在為帳號 {email} 向微軟伺服器請求刷新令牌...")
        
        # 2. 微軟 OAuth 2.0 刷新端點
        url = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
        
        # 3. 構建 Payload (微軟要求使用 x-www-form-urlencoded)
        payload = {
            "client_id": client_id,
            "grant_type": "refresh_token",
            "refresh_token": old_refresh_token
        }
        
        # 4. 發送請求
        response = requests.post(url, data=payload, timeout=15)
        
        if response.status_code == 200:
            token_data = response.json()
            new_refresh_token = token_data.get("refresh_token")
            new_access_token = token_data.get("access_token")
            
            print("\n✅ 刷新成功！你獲得了新的 90 天效期。")
            print("-" * 60)
            print(f"🔴 [極度重要] 新的 Refresh Token (請務必保存替換舊的):\n{new_refresh_token}\n")
            print("-" * 60)
            
            # 將更新後的完整格式印出，方便你直接複製存檔
            updated_data = f"{parts[0]}----{parts[1]}----{parts[2]}----{new_refresh_token}"
            print(f"📦 更新後的完整發貨格式:\n{updated_data}")
            
        else:
            print(f"❌ 刷新失敗: HTTP {response.status_code}")
            print(response.json())
            
    except Exception as e:
        print(f"發生錯誤: {e}")

if __name__ == "__main__":
    refresh_microsoft_token(SELLER_DATA)