import streamlit as st
import requests
import pandas as pd
import time
from datetime import datetime, timedelta, timezone

st.set_page_config(page_title="Questrade 实时量化看板", layout="wide")
st.title("📈 客户专属：Questrade 全视角交易终端")

# ================= 侧边栏：账户连接 =================
st.sidebar.header("🔑 账户连接")

if 'authenticated' not in st.session_state:
    st.session_state.authenticated = False
    st.session_state.access_token = ''
    st.session_state.api_server = ''

if not st.session_state.authenticated:
    refresh_token = st.sidebar.text_input("请输入您的 Refresh Token (钥匙):", type="password")
    if st.sidebar.button("🔌 验证并连接"):
        if refresh_token:
            url = f"https://login.questrade.com/oauth2/token?grant_type=refresh_token&refresh_token={refresh_token}"
            response = requests.get(url)
            if response.status_code == 200:
                auth_data = response.json()
                st.session_state.access_token = auth_data['access_token']
                st.session_state.api_server = auth_data['api_server']
                st.session_state.authenticated = True
                st.rerun()
            else:
                st.sidebar.error("❌ Token 无效或已被使用过，请重新生成。")
    st.info("👈 请在左侧输入您的 Refresh Token 并点击连接。")
    st.stop()
else:
    st.sidebar.success("✅ 账户已安全连接！")
    if st.sidebar.button("断开连接 / 更换账户"):
        st.session_state.authenticated = False
        st.rerun()

st.sidebar.markdown("---")
refresh_rate = st.sidebar.slider("自动刷新频率 (秒)", min_value=3, max_value=30, value=5)

# ================= 核心 API 请求函数 =================
def fetch_data(api_server, access_token, endpoint):
    headers = {"Authorization": f"Bearer {access_token}"}
    response = requests.get(f"{api_server}{endpoint}", headers=headers)
    return response.json()

access_token = st.session_state.access_token
api_server = st.session_state.api_server

accounts_data = fetch_data(api_server, access_token, "v1/accounts")
if not accounts_data.get('accounts'):
    st.error("未找到任何交易账户。")
    st.stop()

account_dict = {f"{acc['type']} - {acc['number']}": acc['number'] for acc in accounts_data['accounts']}
selected_account_name = st.sidebar.selectbox("🏦 请选择要查看的交易账户:", list(account_dict.keys()))
account_id = account_dict[selected_account_name]

# ================= 界面架构：三大标签页 =================
tab1, tab2, tab3 = st.tabs(["💰 资产与持仓 (Portfolio)", "📝 挂单监控 (Orders)", "🧮 购买力计算器 (Calculator)"])

# 提前设置占位符，以便在底层循环中动态刷新
with tab1:
    st.subheader("💳 账户综合资金概览")
    balance_placeholder = st.empty()
    st.subheader("💼 当前持仓明细")
    position_placeholder = st.empty()

with tab2:
    st.sidebar.header("🔍 订单过滤筛选")
    filter_symbol = st.sidebar.text_input("股票代码过滤 (留空看全部):", "").strip().upper()
    filter_side = st.sidebar.multiselect("交易方向:", ["Buy", "Sell"], default=["Buy", "Sell"])
    filter_status = st.sidebar.multiselect("订单状态:", ["未成交 (Active)", "已成交 (Executed)", "已取消 (Canceled)"], default=["未成交 (Active)", "已成交 (Executed)"])
    order_placeholder = st.empty()

with tab3:
    st.subheader("🎯 目标股票购买决策辅助")
    calc_symbol = st.text_input("请输入想要购买的股票代码 (例如: AAPL, BDMD):").strip().upper()
    calc_placeholder = st.empty()

# ================= 主循环：数据并行抓取与渲染 =================
while True:
    try:
        # 抓取资产余额 (Balances)
        balances_data = fetch_data(api_server, access_token, f"v1/accounts/{account_id}/balances")
        # 抓取当前持仓 (Positions)
        positions_data = fetch_data(api_server, access_token, f"v1/accounts/{account_id}/positions")
        
        # 异常拦截处理
        if 'code' in balances_data and balances_data['code'] == 1015:
            st.warning("⚠️ 安全连接已超时 (30分钟)，请断开重新输入。")
            st.stop()

        # ================= 渲染 Tab 1：资产与持仓 =================
        with balance_placeholder.container():
            cad_cash = cad_equity = usd_cash = usd_equity = 0
            for b in balances_data.get('combinedBalances', []):
                if b['currency'] == 'CAD':
                    cad_cash = b['cash']
                    cad_equity = b['totalEquity']
                elif b['currency'] == 'USD':
                    usd_cash = b['cash']
                    usd_equity = b['totalEquity']
            
            # 使用四宫格美观展示资金
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("总资产估值 (CAD)", f"${cad_equity:,.2f}")
            col2.metric("可支配现金 (CAD)", f"${cad_cash:,.2f}")
            col3.metric("总资产估值 (USD)", f"${usd_equity:,.2f}")
            col4.metric("可支配现金 (USD)", f"${usd_cash:,.2f}")

        with position_placeholder.container():
            positions = positions_data.get('positions', [])
            if not positions:
                st.info("当前账户无持仓记录。")
            else:
                df_pos = pd.DataFrame(positions)[['symbol', 'openQuantity', 'currentPrice', 'totalCost', 'currentMarketValue', 'openPnl']]
                df_pos.rename(columns={
                    'symbol': '股票代码',
                    'openQuantity': '持仓股数',
                    'currentPrice': '实时现价',
                    'totalCost': '已购入总价格(成本)',
                    'currentMarketValue': '当前总市值',
                    'openPnl': '净盈利(浮动盈亏)'
                }, inplace=True)
                
                def color_pnl(val):
                    color = '#ff4b4b' if val < 0 else '#09ab3b'
                    return f'color: {color}; font-weight: bold'
                
                styled_pos = df_pos.style.map(color_pnl, subset=['净盈利(浮动盈亏)']).format("{:.2f}", subset=['实时现价', '已购入总价格(成本)', '当前总市值', '净盈利(浮动盈亏)'])
                st.dataframe(styled_pos, use_container_width=True, hide_index=True)

        # ================= 渲染 Tab 2：挂单监控 (复用 V9 逻辑) =================
        with order_placeholder.container():
            now = datetime.now(timezone.utc)
            start_str = (now - timedelta(days=90)).strftime("%Y-%m-%dT%H:%M:%SZ")
            end_str = now.strftime("%Y-%m-%dT%H:%M:%SZ")
            orders_data = fetch_data(api_server, access_token, f"v1/accounts/{account_id}/orders?startTime={start_str}&endTime={end_str}")
            orders = orders_data.get('orders', [])
            
            if not orders:
                st.success("过去90天内没有任何订单记录。")
            else:
                df_orders = pd.DataFrame(orders)[['symbolId', 'symbol', 'side', 'totalQuantity', 'limitPrice', 'state', 'updateTime']]
                df_orders['updateTime'] = pd.to_datetime(df_orders['updateTime'])
                df_orders = df_orders.sort_values(by='updateTime', ascending=True)
                df_orders = df_orders.drop_duplicates(subset=['symbolId', 'side', 'totalQuantity', 'limitPrice'], keep='last')
                
                if filter_symbol:
                    target_symbols = [s.strip() for s in filter_symbol.split(',') if s.strip()]
                    df_orders = df_orders[df_orders['symbol'].str.upper().isin(target_symbols)]
                
                df_orders = df_orders[df_orders['side'].isin(filter_side)]
                
                allowed_states = []
                if "未成交 (Active)" in filter_status: allowed_states.extend(['Open', 'Accepted', 'Suspended', 'Pending', 'Activated'])
                if "已成交 (Executed)" in filter_status: allowed_states.extend(['Executed'])
                if "已取消 (Canceled)" in filter_status: allowed_states.extend(['Canceled'])
                df_orders = df_orders[df_orders['state'].isin(allowed_states)]
                
                if df_orders.empty:
                    st.warning("无符合条件的挂单。")
                else:
                    df_orders['updateTime'] = df_orders['updateTime'].dt.tz_convert('America/Toronto').dt.strftime('%m-%d %H:%M:%S')
                    df_orders.rename(columns={'symbol': '股票代码', 'side': '买/卖', 'totalQuantity': '数量', 'limitPrice': '挂单价格', 'state': '状态', 'updateTime': '更新时间(多伦多)'}, inplace=True)
                    
                    # 获取批量报价
                    unique_sym_ids = df_orders['symbolId'].unique()
                    sym_ids_str = ",".join([str(sid) for sid in unique_sym_ids])
                    quotes_data = fetch_data(api_server, access_token, f"v1/markets/quotes?ids={sym_ids_str}")
                    df_quotes = pd.DataFrame(quotes_data.get('quotes', []))[['symbolId', 'lastTradePrice', 'bidPrice', 'askPrice']]
                    df_quotes = df_quotes.drop_duplicates(subset=['symbolId']).rename(columns={'lastTradePrice': '当前最新价', 'bidPrice': '买一价', 'askPrice': '卖一价'})
                    
                    df_final = pd.merge(df_orders, df_quotes, on='symbolId', how='left').drop(columns=['symbolId'])
                    df_final['距离现价差额'] = df_final['挂单价格'] - df_final['当前最新价']
                    
                    df_final = df_final[['更新时间(多伦多)', '股票代码', '买/卖', '数量', '挂单价格', '状态', '当前最新价', '买一价', '卖一价', '距离现价差额']]
                    
                    def highlight_diff(val): return '' if pd.isna(val) else (f'color: #ff4b4b; font-weight: bold' if val < 0 else f'color: #09ab3b; font-weight: bold')
                    def highlight_state(val): return 'color: #09ab3b; font-weight: bold' if val == 'Executed' else ('color: #888888' if val == 'Canceled' else 'color: #0078ff')
                    
                    styled_df = df_final.style.map(highlight_diff, subset=['距离现价差额']).map(highlight_state, subset=['状态']).format("{:.2f}", subset=['挂单价格', '当前最新价', '买一价', '卖一价', '距离现价差额'])
                    st.dataframe(styled_df, use_container_width=True, hide_index=True)

        # ================= 渲染 Tab 3：购买力计算器 =================
        with calc_placeholder.container():
            if calc_symbol:
                # 1. 搜索股票，获取内部 ID 和币种
                search_res = fetch_data(api_server, access_token, f"v1/symbols/search?prefix={calc_symbol}")
                symbols = search_res.get('symbols', [])
                if symbols:
                    # 精准匹配
                    matched_sym = next((s for s in symbols if s['symbol'].upper() == calc_symbol), symbols[0])
                    sym_id = matched_sym['symbolId']
                    currency = matched_sym['currency']
                    
                    # 2. 获取实时卖一价 (散户买入吃的是卖盘价格)
                    quote_res = fetch_data(api_server, access_token, f"v1/markets/quotes?ids={sym_id}")
                    if quote_res.get('quotes'):
                        ask_price = quote_res['quotes'][0]['askPrice']
                        last_price = quote_res['quotes'][0]['lastTradePrice']
                        # 如果卖盘为空，退而求其次用最新成交价计算
                        calc_price = ask_price if ask_price > 0 else last_price
                        
                        available_cash = usd_cash if currency == 'USD' else cad_cash
                        
                        st.markdown(f"**检索结果:** `{matched_sym['symbol']}` - {matched_sym['description']}")
                        st.markdown(f"**实时结算价:** `${calc_price} {currency}`")
                        st.markdown(f"**当前账户 {currency} 现金余量:** `${available_cash:,.2f}`")
                        
                        if calc_price > 0:
                            max_shares = int(available_cash // calc_price)
                            st.success(f"💡 根据实时价格，您当前的现金最多可购入 **{max_shares}** 股。")
                        else:
                            st.warning("该股票当前处于非交易状态，无法获取有效报价。")
                else:
                    st.error("Questrade 库中未查找到该股票代码，请核对。")
            else:
                st.info("⬆️ 请在上方输入框内键入股票代码开始计算。")

        st.caption(f"🔄 终端数据自动刷新中... | 最后同步时间: {time.strftime('%H:%M:%S')}")
            
    except Exception as e:
        st.error(f"网络请求发生错误。错误信息: {e}")
        
    time.sleep(refresh_rate)
