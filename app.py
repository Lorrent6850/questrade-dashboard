import streamlit as st
import requests
import pandas as pd
import time
from datetime import datetime, timedelta, timezone

st.set_page_config(page_title="Questrade 实时看板", layout="wide")
st.title("Questrade 实时订单与行情监控")

# ================= 侧边栏：账户连接与状态管理 =================
st.sidebar.header("🔑 账户连接")

# 1. 初始化会话记忆 (Session State)
if 'authenticated' not in st.session_state:
    st.session_state.authenticated = False
    st.session_state.access_token = ''
    st.session_state.api_server = ''

# 2. 如果还没登录，显示输入框和登录按钮
if not st.session_state.authenticated:
    refresh_token = st.sidebar.text_input("请输入您的 Refresh Token (钥匙):", type="password")
    if st.sidebar.button("🔌 验证并连接"):
        if refresh_token:
            url = f"https://login.questrade.com/oauth2/token?grant_type=refresh_token&refresh_token={refresh_token}"
            response = requests.get(url)
            if response.status_code == 200:
                # 登录成功，把凭证锁进 session_state
                auth_data = response.json()
                st.session_state.access_token = auth_data['access_token']
                st.session_state.api_server = auth_data['api_server']
                st.session_state.authenticated = True
                st.rerun() # 刷新网页，进入监控界面
            else:
                st.sidebar.error("❌ Token 无效或已被使用过，请重新生成。")
    
    st.info("👈 请在左侧输入您的 Refresh Token 并点击连接。")
    st.stop() # 停止运行后续代码，直到登录成功

# 3. 如果已经登录，显示成功状态和断开按钮
else:
    st.sidebar.success("✅ 账户已安全连接！")
    if st.sidebar.button("断开连接 / 更换账户"):
        st.session_state.authenticated = False
        st.rerun()

st.sidebar.markdown("---")
refresh_rate = st.sidebar.slider("自动刷新频率 (秒)", min_value=3, max_value=30, value=5)

# ================= 侧边栏：订单过滤筛选 =================
st.sidebar.header("🔍 订单过滤筛选")
filter_side = st.sidebar.multiselect("交易方向:", ["Buy", "Sell"], default=["Buy", "Sell"])

filter_status = st.sidebar.multiselect(
    "订单状态:",
    ["未成交 (Active)", "已成交 (Executed)", "已取消 (Canceled)"],
    default=["未成交 (Active)", "已成交 (Executed)"] 
)

# ================= 核心 API 请求函数 =================
def fetch_data(api_server, access_token, endpoint):
    headers = {"Authorization": f"Bearer {access_token}"}
    response = requests.get(f"{api_server}{endpoint}", headers=headers)
    return response.json()

# 从内存保险柜中取出凭证
access_token = st.session_state.access_token
api_server = st.session_state.api_server

# ================= 获取账户列表 =================
accounts_data = fetch_data(api_server, access_token, "v1/accounts")
if not accounts_data.get('accounts'):
    st.error("未找到任何交易账户，API Token 权限可能设置有误。")
    st.stop()

account_dict = {f"{acc['type']} - {acc['number']}": acc['number'] for acc in accounts_data['accounts']}
selected_account_name = st.sidebar.selectbox("🏦 请选择要查看的交易账户:", list(account_dict.keys()))
account_id = account_dict[selected_account_name]

table_placeholder = st.empty()

# ================= 主循环：抓取与数据处理 =================
while True:
    try:
        now = datetime.now(timezone.utc)
        start_time = now - timedelta(days=90)
        start_str = start_time.strftime("%Y-%m-%dT%H:%M:%SZ")
        end_str = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        
        endpoint = f"v1/accounts/{account_id}/orders?startTime={start_str}&endTime={end_str}"
        orders_data = fetch_data(api_server, access_token, endpoint)
        
        # 捕捉 Token 过期的情况 (Questrade 的 Access Token 生命周期一般为 30 分钟)
        if 'code' in orders_data and orders_data['code'] == 1015:
            st.warning("⚠️ 安全连接已超时 (30分钟)，请点击左侧'断开连接'并重新输入新的 Token。")
            st.stop()
            
        orders = orders_data.get('orders', [])
        
        with table_placeholder.container():
            if not orders:
                st.success(f"当前账户 {selected_account_name} 在过去90天内没有任何订单记录。")
            else:
                df_orders = pd.DataFrame(orders)[['id', 'symbol', 'symbolId', 'side', 'totalQuantity', 'limitPrice', 'state', 'updateTime']]
                
                # 排序与去重
                df_orders['updateTime'] = pd.to_datetime(df_orders['updateTime'])
                df_orders = df_orders.sort_values(by='
