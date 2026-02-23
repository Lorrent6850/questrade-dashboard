import streamlit as st
import requests
import pandas as pd
import time
from datetime import datetime, timedelta, timezone

st.set_page_config(page_title="Questrade 实时看板", layout="wide")
st.title("📈 客户专属：Questrade 实时订单与行情监控")

# ================= 侧边栏：账户连接与过滤设置 =================
st.sidebar.header("🔑 账户连接")
refresh_token = st.sidebar.text_input("请输入您的 Refresh Token (钥匙):", type="password")
refresh_rate = st.sidebar.slider("刷新频率 (秒)", min_value=3, max_value=30, value=5)

if not refresh_token:
    st.info("👈 请在左侧输入您的 Refresh Token 以连接账户并获取实时数据。")
    st.stop()

st.sidebar.markdown("---")
st.sidebar.header("🔍 订单过滤筛选")
filter_side = st.sidebar.multiselect("交易方向:", ["Buy", "Sell"], default=["Buy", "Sell"])

filter_status = st.sidebar.multiselect(
    "订单状态:",
    ["未成交 (Active)", "已成交 (Executed)", "已取消 (Canceled)"],
    default=["未成交 (Active)", "已成交 (Executed)"] 
)

# ================= 核心 API 请求函数 =================
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

auth_data = get_access_token(refresh_token)
access_token = auth_data['access_token']
api_server = auth_data['api_server']

accounts_data = fetch_data(api_server, access_token, "v1/accounts")
if not accounts_data.get('accounts'):
    st.error("未找到任何交易账户。")
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
        orders = orders_data.get('orders', [])
        
        with table_placeholder.container():
            if not orders:
                st.success(f"当前账户 {selected_account_name} 在过去90天内没有任何订单记录。")
            else:
                # --- 核心修复 1：把 updateTime 一起抓下来 ---
                df_orders = pd.DataFrame(orders)[['id', 'symbol', 'symbolId', 'side', 'totalQuantity', 'limitPrice', 'state', 'updateTime']]
                
                # --- 核心修复 2：按时间排序，并只保留同一 ID 的“最后/最新”状态 ---
                # 将字符串时间转为 Pandas 的时间对象以便正确排序
                df_orders['updateTime'] = pd.to_datetime(df_orders['updateTime'])
                df_orders = df_orders.sort_values(by='updateTime', ascending=True)
                # keep='last' 确保我们留下的是 Executed 或 Canceled 这类最终状态
                df_orders = df_orders.drop_duplicates(subset=['id'], keep='last')
                
                # 过滤买卖方向
                df_orders = df_orders[df_orders['side'].isin(filter_side)]
                
                # 过滤订单状态
                allowed_states = []
                if "未成交 (Active)" in filter_status:
                    allowed_states.extend(['Open', 'Accepted', 'Suspended', 'Pending', 'Activated'])
                if "已成交 (Executed)" in filter_status:
                    allowed_states.extend(['Executed'])
                if "已取消 (Canceled)" in filter_status:
                    allowed_states.extend(['Canceled'])
                
                df_orders = df_orders[df_orders['state'].isin(allowed_states)]
                
                if df_orders.empty:
                    st.warning("根据您左侧的筛选条件，当前没有符合要求的订单。")
                else:
                    # 将时间格式化为更易读的本地字符串格式
                    df_orders['updateTime'] = df_orders['updateTime'].dt.tz_convert('America/New_York').dt.strftime('%m-%d %H:%M:%S')
                    
                    df_orders.rename(columns={
                        'id': '订单编号', 
                        'symbol': '股票代码', 
                        'side': '买/卖', 
                        'totalQuantity': '数量', 
                        'limitPrice': '挂单价格', 
                        'state': '状态',
                        'updateTime': '最后更新时间' # 新增展示列
                    }, inplace=True)
                    
                    # 批量获取报价
                    unique_symbol_ids = df_orders['symbolId'].unique()
                    symbol_ids_str = ",".join([str(sid) for sid in unique_symbol_ids])
                    
                    quotes_data = fetch_data(api_server, access_token, f"v1/markets/quotes?ids={symbol_ids_str}")
                    df_quotes = pd.DataFrame(quotes_data.get('quotes', []))[['symbolId', 'lastTradePrice', 'bidPrice', 'askPrice']]
                    df_quotes = df_quotes.drop_duplicates(subset=['symbolId'])
                    df_quotes.rename(columns={'lastTradePrice': '当前最新价', 'bidPrice': '买一价', 'askPrice': '卖一价'}, inplace=True)
                    
                    # 合并数据
                    df_final = pd.merge(df_orders, df_quotes, on='symbolId', how='left').drop(columns=['symbolId'])
                    df_final['距离现价差额'] = df_final['挂单价格'] - df_final['当前最新价']
                    
                    # 重新排列一下列的顺序，让时间靠前一点更好看
                    cols = ['最后更新时间', '订单编号', '股票代码', '买/卖', '数量', '挂单价格', '状态', '当前最新价', '买一价', '卖一价', '距离现价差额']
                    df_final = df_final[cols]
                    
                    # 样式渲染
                    def highlight_diff(val):
                        if pd.isna(val): return ''
                        color = '#ff4b4b' if val < 0 else '#09ab3b'
                        return f'color: {color}; font-weight: bold'
                    
                    def highlight_state(val):
                        if val == 'Executed':
                            return 'color: #09ab3b; font-weight: bold' 
                        elif val == 'Canceled':
                            return 'color: #888888' 
                        else:
                            return 'color: #0078ff' 
                    
                    styled_df = df_final.style.map(highlight_diff, subset=['距离现价差额']) \
                                              .map(highlight_state, subset=['状态']) \
                                              .format("{:.2f}", subset=['挂单价格', '当前最新价', '买一价', '卖一价', '距离现价差额'])
                    
                    st.dataframe(styled_df, use_container_width=True, hide_index=True)
                
            st.caption(f"🔄 自动刷新中... | 最后更新时间: {time.strftime('%H:%M:%S')}")
            
    except Exception as e:
        st.error(f"网络请求发生错误，请检查网络
