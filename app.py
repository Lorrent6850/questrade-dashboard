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

# 如果客户还没输入 Token，提示等待
if not refresh_token:
    st.info("👈 请在左侧输入您的 Refresh Token 以连接账户并获取实时数据。")
    st.stop()

# 定义 Questrade API 请求的基础函数
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

# 占位符，用于动态刷新表格
table_placeholder = st.empty()

# 1. 鉴权并获取临时 Access Token 和 API 服务器地址
auth_data = get_access_token(refresh_token)
access_token = auth_data['access_token']
api_server = auth_data['api_server']

# 2. 自动获取客户的第一个账户 ID (免去客户手动寻找的麻烦)
accounts_data = fetch_data(api_server, access_token, "v1/accounts")
if not accounts_data.get('accounts'):
    st.error("未找到任何交易账户。")
    st.stop()
account_id = accounts_data['accounts'][0]['number']
st.sidebar.success(f"已成功连接账户: {account_id}")

# 3. 开启循环，定时刷新表格
while True:
    try:
        # 获取活动挂单 (Open Orders)
        orders_data = fetch_data(api_server, access_token, f"v1/accounts/{account_id}/orders")
        orders = [o for o in orders_data.get('orders', []) if o['state'] == 'Open']
        
        with table_placeholder.container():
            if not orders:
                st.success(f"当前账户 {account_id} 没有正在等待成交的挂单。")
            else:
                # 整理订单数据
                df_orders = pd.DataFrame(orders)[['id', 'symbol', 'symbolId', 'side', 'totalQuantity', 'limitPrice']]
                df_orders.rename(columns={'id': '订单编号', 'symbol': '股票代码', 'side': '买/卖', 'totalQuantity': '数量', 'limitPrice': '挂单价格'}, inplace=True)
                
                # 提取 symbolId，批量请求实时行情
                symbol_ids = ",".join([str(sid) for sid in df_orders['symbolId'].tolist()])
                quotes_data = fetch_data(api_server, access_token, f"v1/markets/quotes?ids={symbol_ids}")
                
                # 整理行情数据
                df_quotes = pd.DataFrame(quotes_data.get('quotes', []))[['symbolId', 'lastTradePrice', 'bidPrice', 'askPrice']]
                df_quotes.rename(columns={'lastTradePrice': '当前最新价', 'bidPrice': '买一价', 'askPrice': '卖一价'}, inplace=True)
                
                # 数据合并
                df_final = pd.merge(df_orders, df_quotes, on='symbolId', how='left').drop(columns=['symbolId'])
                
                # 计算价差 (挂单价 - 最新价)
                df_final['价格差额'] = df_final['挂单价格'] - df_final['当前最新价']
                
                # 简单的高亮逻辑：价差为正显示绿色，为负显示红色
                def highlight_diff(val):
                    color = '#ff4b4b' if val < 0 else '#09ab3b' # Streamlit 风格红绿
                    return f'color: {color}; font-weight: bold'
                
                styled_df = df_final.style.map(highlight_diff, subset=['价格差额']).format("{:.2f}", subset=['挂单价格', '当前最新价', '买一价', '卖一价', '价格差额'])
                
                # 展示可视化表格
                st.dataframe(styled_df, use_container_width=True, hide_index=True)
                
            st.caption(f"🔄 自动刷新中... | 最后更新时间: {time.strftime('%H:%M:%S')}")
            
    except Exception as e:
        st.error(f"网络请求或数据解析发生错误，正在重试... 错误信息: {e}")
        
    time.sleep(refresh_rate)
