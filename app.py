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
auto_refresh = st.sidebar.checkbox("开启数据自动刷新", value=True)
if auto_refresh:
    refresh_rate = st.sidebar.slider("自动刷新频率 (秒)", min_value=3, max_value=30, value=5)

# ================= 核心 API 请求与发单/撤单函数 =================
def fetch_data(api_server, access_token, endpoint):
    headers = {"Authorization": f"Bearer {access_token}"}
    response = requests.get(f"{api_server}{endpoint}", headers=headers)
    return response.json()

def place_order(api_server, access_token, account_id, symbol_id, action, qty, price):
    url = f"{api_server}v1/accounts/{account_id}/orders"
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    payload = {"symbolId": symbol_id, "primaryRoute": "AUTO", "action": action, "orderType": "Limit", "limitPrice": float(price), "totalQuantity": int(qty), "timeInForce": "GTC"}
    return requests.post(url, headers=headers, json=payload).json()

def cancel_order(api_server, access_token, account_id, order_id):
    url = f"{api_server}v1/accounts/{account_id}/orders/{order_id}"
    headers = {"Authorization": f"Bearer {access_token}"}
    response = requests.delete(url, headers=headers)
    try:
        return response.json()
    except Exception:
        return {"raw_status": response.status_code, "text": response.text}

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
tab1, tab2, tab3 = st.tabs(["💰 资产与持仓", "📝 挂单监控 & 批量撤单", "🧮 网格交易实盘引擎"])

try:
    balances_data = fetch_data(api_server, access_token, f"v1/accounts/{account_id}/balances")
    positions_data = fetch_data(api_server, access_token, f"v1/accounts/{account_id}/positions")
    
    if 'code' in balances_data and balances_data['code'] == 1015:
        st.session_state.authenticated = False
        st.warning("⚠️ 安全连接已超时 (30分钟)，请断开重新输入。")
        st.stop()

    # 提取全局资产信息 (供 Tab 1 和 Tab 3 计算使用)
    cad_cash = cad_equity = usd_cash = usd_equity = 0
    for b in balances_data.get('combinedBalances', []):
        if b['currency'] == 'CAD': cad_cash, cad_equity = b['cash'], b['totalEquity']
        elif b['currency'] == 'USD': usd_cash, usd_equity = b['cash'], b['totalEquity']

    # ================= 渲染 Tab 1 =================
    with tab1:
        st.subheader("💳 账户综合资金概览")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("总资产估值 (CAD)", f"${cad_equity:,.2f}")
        c2.metric("可支配现金 (CAD)", f"${cad_cash:,.2f}")
        c3.metric("总资产估值 (USD)", f"${usd_equity:,.2f}")
        c4.metric("可支配现金 (USD)", f"${usd_cash:,.2f}")

        st.subheader("💼 当前持仓明细")
        positions = positions_data.get('positions', [])
        if not positions:
            st.info("当前账户无持仓记录。")
        else:
            df_pos = pd.DataFrame(positions)[['symbol', 'openQuantity', 'currentPrice', 'totalCost', 'currentMarketValue', 'openPnl']]
            df_pos.rename(columns={'symbol': '股票代码', 'openQuantity': '持仓股数', 'currentPrice': '实时现价', 'totalCost': '已购入总价格(成本)', 'currentMarketValue': '当前总市值', 'openPnl': '净盈利(浮动盈亏)'}, inplace=True)
            def color_pnl(val): return f"color: {'#ff4b4b' if val < 0 else '#09ab3b'}; font-weight: bold"
            st.dataframe(df_pos.style.map(color_pnl, subset=['净盈利(浮动盈亏)']).format("{:.2f}", subset=['实时现价', '已购入总价格(成本)', '当前总市值', '净盈利(浮动盈亏)']), use_container_width=True, hide_index=True)

    # ================= 渲染 Tab 2: 挂单监控与撤单 =================
    with tab2:
        col_f1, col_f2, col_f3 = st.columns(3)
        with col_f1: filter_symbol = st.text_input("🔍 股票代码过滤 (留空看全部):", "").strip().upper()
        with col_f2: filter_side = st.multiselect("⚖️ 交易方向:", ["Buy", "Sell"], default=["Buy", "Sell"])
        with col_f3: filter_status = st.multiselect("📊 订单状态:", ["未成交 (Active)", "已成交 (Executed)", "已取消 (Canceled)"], default=["未成交 (Active)"])

        now = datetime.now(timezone.utc)
        start_str = (now - timedelta(days=90)).strftime("%Y-%m-%dT%H:%M:%SZ")
        end_str = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        orders_data = fetch_data(api_server, access_token, f"v1/accounts/{account_id}/orders?startTime={start_str}&endTime={end_str}")
        orders = orders_data.get('orders', [])
        
        if not orders:
            st.success("过去90天内没有任何订单记录。")
        else:
            df_orders = pd.DataFrame(orders)[['id', 'symbolId', 'symbol', 'side', 'totalQuantity', 'limitPrice', 'state', 'updateTime']]
            df_orders['updateTime'] = pd.to_datetime(df_orders['updateTime'])
            df_orders = df_orders.sort_values(by='updateTime', ascending=True)
            df_orders = df_orders.drop_duplicates(subset=['symbolId', 'side', 'totalQuantity', 'limitPrice'], keep='last')
            
            if filter_symbol:
                target_symbols = [s.strip() for s in filter_symbol.split(',') if s.strip()]
                df_orders = df_orders[df_orders['symbol'].str.upper().isin(target_symbols)]
            
            df_orders = df_orders[df_orders['side'].isin(filter_side)]
            
            active_states = ['Open', 'Accepted', 'Suspended', 'Pending', 'Activated']
            allowed_states = []
            if "未成交 (Active)" in filter_status: allowed_states.extend(active_states)
            if "已成交 (Executed)" in filter_status: allowed_states.extend(['Executed'])
            if "已取消 (Canceled)" in filter_status: allowed_states.extend(['Canceled'])
            
            df_orders = df_orders[df_orders['state'].isin(allowed_states)]
            
            if df_orders.empty:
                st.warning("无符合条件的挂单。")
            else:
                active_orders_to_cancel = df_orders[df_orders['state'].isin(active_states)]
                
                if not active_orders_to_cancel.empty:
                    with st.expander("🛑 危险操作区：批量撤销当前显示的挂单 (Kill Switch)", expanded=False):
                        st.warning(f"基于筛选条件，当前列表中共有 **{len(active_orders_to_cancel)}** 个尚未成交的订单。")
                        confirm_kill = st.checkbox("我已确认要批量撤销这些订单 (不可逆)")
                        if confirm_kill:
                            if st.button(f"🗑️ 立即向券商发送 {len(active_orders_to_cancel)} 条撤销指令", type="primary"):
                                cancel_bar = st.progress(0, text="正在逐条发送撤单请求...")
                                cancel_success = 0
                                error_msgs = [] 
                                
                                for i, (index, row) in enumerate(active_orders_to_cancel.iterrows()):
                                    real_order_id = int(row['id']) 
                                    res = cancel_order(api_server, access_token, account_id, real_order_id)
                                    
                                    if isinstance(res, dict) and ('orderId' in res or 'code' not in res):
                                        cancel_success += 1
                                    else:
                                        error_msgs.append(f"底层ID {real_order_id} 撤销遭拒，API回复: {res}")
                                        
                                    time.sleep(0.5) 
                                    cancel_bar.progress((i + 1) / len(active_orders_to_cancel), text="正在逐条发送撤单请求...")
                                
                                cancel_bar.empty()
                                if cancel_success == len(active_orders_to_cancel):
                                    st.success(f"✅ 完美执行！已成功发送 {cancel_success} 条撤单指令。")
                                else:
                                    st.warning(f"⚠️ 发送完毕。成功 {cancel_success} 条，失败 {len(active_orders_to_cancel) - cancel_success} 条。")
                                    if error_msgs:
                                        with st.expander("🔍 查看撤单失败的真实底层原因 (点击展开)", expanded=True):
                                            for msg in error_msgs: st.write(msg)
                                time.sleep(3)
                                st.rerun() 

                df_orders['updateTime'] = df_orders['updateTime'].dt.tz_convert('America/Toronto').dt.strftime('%m-%d %H:%M:%S')
                df_orders.rename(columns={'id':'底层ID', 'symbol': '股票代码', 'side': '买/卖', 'totalQuantity': '数量', 'limitPrice': '挂单价格', 'state': '状态', 'updateTime': '更新时间'}, inplace=True)
                
                unique_sym_ids = df_orders['symbolId'].unique()
                sym_ids_str = ",".join([str(sid) for sid in unique_sym_ids])
                quotes_data = fetch_data(api_server, access_token, f"v1/markets/quotes?ids={sym_ids_str}")
                df_quotes = pd.DataFrame(quotes_data.get('quotes', []))[['symbolId', 'lastTradePrice', 'bidPrice', 'askPrice']].drop_duplicates(subset=['symbolId']).rename(columns={'lastTradePrice': '最新价', 'bidPrice': '买一价', 'askPrice': '卖一价'})
                
                df_final = pd.merge(df_orders, df_quotes, on='symbolId', how='left').drop(columns=['symbolId'])
                df_final['距离现价差额'] = df_final['挂单价格'] - df_final['最新价']
                
                df_final = df_final[['更新时间', '股票代码', '买/卖', '数量', '挂单价格', '状态', '最新价', '买一价', '卖一价', '距离现价差额', '底层ID']]
                
                def highlight_diff(val): return '' if pd.isna(val) else (f'color: #ff4b4b; font-weight: bold' if val < 0 else f'color: #09ab3b; font-weight: bold')
                def highlight_state(val): return 'color: #09ab3b; font-weight: bold' if val == 'Executed' else ('color: #888888' if val == 'Canceled' else 'color: #0078ff')
                
                st.dataframe(df_final.style.map(highlight_diff, subset=['距离现价差额']).map(highlight_state, subset=['状态']).format("{:.2f}", subset=['挂单价格', '最新价', '买一价', '卖一价', '距离现价差额']), use_container_width=True, hide_index=True)

    # ================= 渲染 Tab 3: 网格交易实盘引擎 =================
    with tab3:
        st.subheader("🚀 一键批量网格实盘发单")
        st.warning("⚠️ **警告：本页面连接真实券商接口。真金白银的订单将被直接发送至交易所。请务必仔细核对表格！**")
        
        col_sym, col_mode = st.columns(2)
        with col_sym: calc_symbol = st.text_input("目标股票代码 (如 BDMD):", "BDMD").strip().upper()
        with col_mode: calc_mode = st.radio("交易方向:", ["买入 (Buy)", "卖出 (Sell)"], horizontal=True)
        
        st.write("🔧 **第一步：生成基础网格**")
        col1, col2, col3, col4, col5 = st.columns(5)
        with col1: start_price = st.number_input("起始挂单价 ($)", value=1.45, step=0.01)
        with col2: price_step = st.number_input("价格等差步长", value=-0.03, step=0.01)
        with col3: start_qty = st.number_input("起始股数", value=5000, step=100)
        with col4: qty_step = st.number_input("股数等差步长", value=500, step=100)
        with col5: num_orders = st.number_input("生成行数", min_value=1, max_value=50, value=15)
        
        grid_init = []
        for i in range(int(num_orders)): grid_init.append({"挂单价格": round(start_price + i * price_step, 4), "挂单股数": int(start_qty + i * qty_step)})
        df_grid_init = pd.DataFrame(grid_init)
        
        st.write("✍️ **第二步：手动微调表格 (直接双击修改)**")
        df_edited = st.data_editor(df_grid_init, num_rows="dynamic", use_container_width=True)
        
        # 抓取股票 ID 并确认币种，为运算模块做准备
        symbol_id_for_order = None
        currency = "CAD" # 默认显示加币
        if calc_symbol:
            search_res = fetch_data(api_server, access_token, f"v1/symbols/search?prefix={calc_symbol}")
            symbols = search_res.get('symbols', [])
            if symbols:
                matched_sym = next((s for s in symbols if s['symbol'].upper() == calc_symbol), symbols[0])
                symbol_id_for_order = matched_sym['symbolId']
                currency = matched_sym['currency']

        # ----------------- 核心修复：加回实时运算风控模块 -----------------
        st.write("📊 **实时运算结果与风控评估**")
        if not df_edited.empty and calc_symbol:
            df_edited['单笔总额'] = df_edited['挂单价格'] * df_edited['挂单股数']
            total_shares = df_edited['挂单股数'].sum()
            total_value = df_edited['单笔总额'].sum()
            avg_price = total_value / total_shares if total_shares > 0 else 0
            
            c_calc1, c_calc2, c_calc3 = st.columns(3)
            c_calc1.metric("网格合计总股数", f"{total_shares:,.0f} 股")
            c_calc2.metric("网格合计总金额", f"${total_value:,.2f} {currency}")
            c_calc3.metric("综合摊薄均价", f"${avg_price:,.3f}")
            
            if calc_mode == "买入 (Buy)":
                avail_cash = usd_cash if currency == 'USD' else cad_cash
                st.info(f"💡 **买入评估**: 当前账户可用现金为 **${avail_cash:,.2f} {currency}**。")
                if avail_cash >= total_value:
                    st.success(f"✅ 资金充足！批量买入后预计剩余现金: **${avail_cash - total_value:,.2f} {currency}**")
                else:
                    st.error(f"❌ 资金不足！您还需要充值或卖出其他股票来填补缺口: **${total_value - avail_cash:,.2f} {currency}**")
                    
            else: # 卖出模式
                pos = next((p for p in positions_data.get('positions', []) if p['symbol'].upper() == calc_symbol), None)
                if pos:
                    current_qty = pos['openQuantity']
                    current_avg_cost = pos['totalCost'] / current_qty if current_qty > 0 else 0
                    
                    st.info(f"💡 **卖出评估**: 账户当前持有 {calc_symbol} 共 **{current_qty} 股**，持仓均价约为 **${current_avg_cost:.3f}**。")
                    if current_qty >= total_shares:
                        rem_qty = current_qty - total_shares
                        est_profit = total_value - (total_shares * current_avg_cost)
                        st.success(f"✅ 持仓充足！本次卖出后将剩余 **{rem_qty} 股**。")
                        if est_profit > 0:
                            st.success(f"📈 喜报！预计产生净利润: **${est_profit:,.2f}**")
                        else:
                            st.warning(f"📉 提示：预计将产生亏损: **${est_profit:,.2f}**")
                    else:
                        st.error(f"❌ 持仓不足！您只持有 {current_qty} 股，无法按照当前网格卖出 {total_shares} 股。")
                else:
                    st.warning(f"⚠️ 账户中未查找到 {calc_symbol} 的持仓记录。如果您继续执行，可能导致失败或被视为做空。")
        st.markdown("---")
        # ------------------------------------------------------------------

        st.write("🔥 **第三步：实盘执行**")
        if not symbol_id_for_order:
            st.error("未能获取该股票的底层 ID，无法解锁交易。请检查代码拼写。")
        else:
            unlock_trade = st.checkbox("✅ 我已仔细查看【实时运算结果】，确认网格数据准确且知晓实盘风险，请求解锁执行引擎。")
            if unlock_trade:
                action_str = "Buy" if calc_mode == "买入 (Buy)" else "Sell"
                if st.button(f"🚀 立即向 Questrade 提交 {len(df_edited)} 笔 {action_str} 单", type="primary"):
                    my_bar = st.progress(0, text="正在发送订单至交易所...")
                    success_count = 0
                    
                    for index, row in df_edited.iterrows():
                        price = row['挂单价格']
                        qty = row['挂单股数']
                        if qty > 0 and price > 0:
                            res = place_order(api_server, access_token, account_id, symbol_id_for_order, action_str, qty, price)
                            if 'orders' in res: success_count += 1
                        time.sleep(0.5) 
                        my_bar.progress((index + 1) / len(df_edited), text="正在发送订单至交易所...")
                    
                    my_bar.empty()
                    st.success(f"🎉 执行完毕！成功推送 {success_count} 笔。")
                    time.sleep(2)
                    st.rerun()

    if auto_refresh:
        st.caption(f"🔄 终端数据自动刷新开启中... | 最后同步时间: {time.strftime('%H:%M:%S')}")
        time.sleep(refresh_rate)
        st.rerun()
    else:
        st.caption(f"⏸️ 自动刷新已暂停。您可以安全地进行选择或操作。")

except Exception as e:
    st.error(f"发生错误。这通常是由于网络波动或Token失效引起的: {e}")
    if auto_refresh:
        time.sleep(refresh_rate)
        st.rerun()
