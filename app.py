import streamlit as st
import requests
import pandas as pd
import time

st.set_page_config(page_title="Questrade 实时看板", layout="wide")
st.title("📈 客户专属：Questrade 实时挂单监控")

# 侧边栏：让客户输入 Token
st.sidebar.header("🔑 账户连接")
refresh_token = st.sidebar.text_input("请输入您的 Refresh Token (钥匙):", type="password")
refresh_rate = st.sidebar.slider("刷新频率 (秒)", min_value=3, max_value=30, value=5)

if not refresh_token:
    st.info("👈 请在左侧输入您的 Refresh Token 以连接账户并获取实时数据。")
    st.stop()

def get_access_token(token):
    url = f"https://login.questrade.com/oauth2/token?grant_type=refresh_token&refresh_token={token}"
    response = requests.get(url)
    if response.status_code == 200:
        return response.json()
    else:
        st.error("Token 无效或已过期，请在 Questrade 重新生成一个新的 Refresh Token。")
        st.stop()

def fetch_data(api_server, access_token, endpoint):
    headers = {"Authorization": f"Bearer {access_token}"}
    response = requests.get(f"{api_server}{endpoint}", headers=headers)
    return response.json()

# 1. 获取 Token
auth_data = get_access_token(refresh_token)
access_token = auth_data['access_token']
api_server = auth_data['api_server']

# 2. 获取所有账户，并在侧边栏生成下拉菜单供客户选择
accounts_data = fetch_data(api_server, access_token, "v1/accounts")
if not accounts_data.get('accounts'):
    st.error("未找到任何交易账户。")
    st.stop()

# 提取账户信息并制作成字典 { 'Cash - 40133875': '40133875', ... }
account_dict = {f"{acc['type']} - {acc['number']}": acc['number'] for acc in accounts_data['accounts']}
selected_account_name = st.sidebar.selectbox("🏦 请选择要查看的交易账户:", list(account_dict.keys()))
account_id = account_dict[selected_account_name]

# 占位符
table_placeholder = st.empty()

# 3. 循环刷新
while True:
    try:
        # 获取所有挂单
        orders_data = fetch_data(api_server, access_token, f"v1/accounts/{account_id}/orders")
        
        # 修复核心：将 Accepted, Open, Suspended 等活跃状态都包含进来
        active_states = ['Open', 'Accepted', 'Suspended', 'Pending']
        orders = [o for o in orders_data.get('orders', []) if o['state'] in active_states]
        
        with table_placeholder.container():
            if not orders:
                st.success(f"当前账户 {selected_account_name} 没有正在等待成交的挂单。")
            else:
                # 整理订单数据
                df_orders = pd.DataFrame(orders)[['id', 'symbol', 'symbolId', 'side', 'totalQuantity', 'limitPrice', 'state']]
                df_orders.rename(columns={'id': '订单编号', 'symbol': '股票代码', 'side': '买/卖', 'totalQuantity': '数量', 'limitPrice': '挂单价格', 'state': '状态'}, inplace=True)
                
                # 获取实时行情
                symbol_ids = ",".join([str(sid) for sid in df_orders['symbolId'].tolist()])
                quotes_data = fetch_data(api_server, access_token, f"v1/markets/quotes?ids={symbol_ids}")
                
                # 整理行情数据
                df_quotes = pd.DataFrame(quotes_data.get('quotes', []))[['symbolId', 'lastTradePrice', 'bidPrice', 'askPrice']]
                df_quotes.rename(columns={'lastTradePrice': '当前最新价', 'bidPrice': '买一价', 'askPrice': '卖一价'}, inplace=True)
                
                # 合并数据
                df_final = pd.merge(df_orders, df_quotes, on='symbolId', how='left').drop(columns=['symbolId'])
                
                # 计算价差：如果是买单，价差 = 挂单价 - 最新价；卖单逻辑相反，但为了简单直观，这里统一用差值
                df_final['距离现价差额'] = df_final['挂单价格'] - df_final['当前最新价']
                
                def highlight_diff(val):
                    # 距离现价越近越有可能成交，这里简单做个颜色区分
                    color = '#ff4b4b' if val < 0 else '#09ab3b'
                    return f'color: {color}; font-weight: bold'
                
                # 格式化输出
                styled_df = df_final.style.map(highlight_diff, subset=['距离现价差额']).format("{:.2f}", subset=['挂单价格', '当前最新价', '买一价', '卖一价', '距离现价差额'])
                
                st.dataframe(styled_df, use_container_width=True, hide_index=True)
                
            st.caption(f"🔄 自动刷新中... | 最后更新时间: {time.strftime('%H:%M:%S')}")
            
    except Exception as e:
        st.error(f"网络请求或数据解析发生错误，正在重试... 错误信息: {e}")
        
    time.sleep(refresh_rate)
