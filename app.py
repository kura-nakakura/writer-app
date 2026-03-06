import streamlit as st
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import pandas as pd
import google.generativeai as genai
import json
import re

# --- ページ設定（ここで横幅を広くし、アイコンを設定） ---
st.set_page_config(page_title="求人原稿 自動審査ツール", page_icon="🌿", layout="wide")

# --- 🌳 カスタムCSS（自然系デザインの魔法） ---
st.markdown("""
<style>
    /* 1. アプリ全体の背景を深緑に設定 */
    .stApp {
        background-color: #274029 !important; /* 深緑 */
    }

    /* 2. 基本的な文字をすべて白色に統一 */
    h1, h2, h3, h4, h5, h6, p, span, label, div {
        color: #F8F9FA !important; /* 真っ白より少し優しいオフホワイト */
    }

    /* 3. 区切り線（hr）を焦げ茶色に */
    hr {
        border-bottom: 2px solid #5C3A21 !important; /* 焦げ茶色 */
        border-top: none !important;
        margin-top: 20px;
        margin-bottom: 20px;
    }

    /* 4. 入力欄（テキストエリアやインプット）のデザイン */
    .stTextInput input, .stTextArea textarea {
        background-color: #1E2E1F !important; /* 背景よりさらに深い緑 */
        color: #FFFFFF !important;
        border: 2px solid #5C3A21 !important; /* 焦げ茶色の枠線 */
        border-radius: 8px !important;
    }
    .stTextInput input::placeholder, .stTextArea textarea::placeholder {
        color: #8fa38f !important; /* プレースホルダー（例：）の文字色を薄い緑に */
    }

    /* 5. セレクトボックス（担当者選択など） */
    .stSelectbox div[data-baseweb="select"] > div {
        background-color: #1E2E1F !important;
        border: 2px solid #5C3A21 !important;
        border-radius: 8px !important;
    }

    /* 6. ボタンのデザイン（木をイメージした焦げ茶ベース） */
    .stButton > button {
        background-color: #5C3A21 !important; /* 焦げ茶色 */
        color: #FFFFFF !important;
        border: 1px solid #8B5A2B !important;
        border-radius: 8px !important;
        font-weight: bold !important;
    }
    .stButton > button:hover {
        background-color: #3E2615 !important; /* マウスを乗せると少し暗くなる */
        border-color: #FFFFFF !important;
    }

    /* 7. タブのデザイン（下線を焦げ茶色に） */
    .stTabs [data-baseweb="tab-list"] {
        border-bottom: 3px solid #5C3A21 !important;
        background-color: transparent !important;
    }
    .stTabs [data-baseweb="tab"] {
        background-color: transparent !important;
    }
    .stTabs [data-baseweb="tab-list"] button [data-testid="stMarkdownContainer"] p {
        font-size: 18px !important;
        font-weight: bold !important;
    }

    /* 8. 数字パネル（Metric）のデザイン */
    [data-testid="stMetric"] {
        background-color: #1E2E1F !important;
        border: 2px solid #5C3A21 !important;
        padding: 15px !important;
        border-radius: 10px !important;
        box-shadow: 2px 2px 5px rgba(0,0,0,0.3) !important;
    }

    /* 9. アラート（情報パネルなど）の背景を馴染ませる */
    [data-testid="stAlert"] {
        background-color: rgba(92, 58, 33, 0.4) !important; /* 焦げ茶色の半透明 */
        border: 1px solid #5C3A21 !important;
    }
    
    /* 10. データフレーム（表）の背景調整 */
    [data-testid="stDataFrame"] {
        background-color: #1E2E1F !important;
        border: 1px solid #5C3A21 !important;
    }
</style>
""", unsafe_allow_html=True)

# --- 状態管理（カート機能） ---
if "pending_regs" not in st.session_state:
    st.session_state.pending_regs = {}

# --- Googleスプシ接続関数 ---
@st.cache_resource
def get_worksheet(sheet_id, sheet_name=None):
    scope = ['https://spreadsheets.google.com/feeds','https://www.googleapis.com/auth/drive']
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    sh = client.open_by_key(sheet_id)
    if sheet_name:
        return sh.worksheet(sheet_name)
    else:
        return sh.get_worksheet(0)

# --- スプシ読み込み関数 ---
@st.cache_data(ttl=3600)
def load_cached_dataframe(sheet_id, sheet_name=None):
    ws = get_worksheet(sheet_id, sheet_name)
    all_data = ws.get_all_values()
    if len(all_data) < 2:
        return pd.DataFrame()
    df = pd.DataFrame(all_data[1:], columns=all_data[0])
    df.columns = [str(col).strip() for col in df.columns]
    df = df.loc[:, ~df.columns.duplicated()]
    df = df.loc[:, df.columns != '']
    return df

def load_realtime_dataframe(sheet_id, sheet_name=None):
    ws = get_worksheet(sheet_id, sheet_name)
    all_data = ws.get_all_values()
    if len(all_data) < 2:
        return pd.DataFrame()
    df = pd.DataFrame(all_data[1:], columns=all_data[0])
    df.columns = [str(col).strip() for col in df.columns]
    df = df.loc[:, ~df.columns.duplicated()]
    df = df.loc[:, df.columns != '']
    return df

# --- 🤖 AI審査関数 ---
def evaluate_job_with_ai(job_data_dict):
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    model = genai.GenerativeModel('gemini-2.5-flash')
    prompt = f"""
    あなたは厳格な求人原稿の審査プロフェッショナルです。
    以下の【求人データ】が、【審査規定】を満たしているかチェックしてください。

    【求人データ】
    {json.dumps(job_data_dict, ensure_ascii=False, indent=2)}

    【審査規定】
    1. 基本給・月給: 最低賃金割れの懸念がないか。金額や内訳が不明瞭でないか。
    2. 固定残業代: 「金額」と「時間」の両方が明記されているか。原則45時間を超える記載や範囲が不明確な記載がないか。
    3. 各種手当: 手当の名称や詳細が不明なまま金額だけ記載されていないか。
    4. 労働時間・休日: 年間休日日数の記載が抜けていないか(必須)。1日の労働時間が法定(8時間)を超えていないか。
    5. その他: 勤務地やタイトルなどに矛盾がないか。

    【出力形式】
    規定違反が1つでもある場合は「❌ 掲載不可」とし、どの規定にどう違反しているか具体的な理由を提示してください。
    すべての規定をクリアしている場合は「✅ 掲載可」と出力してください。
    """
    response = model.generate_content(prompt, generation_config=genai.types.GenerationConfig(temperature=0.0))
    return response.text

# --- メイン設定 ---
# 画面上部のタイトルを少しスタイリッシュに（アイコンも葉っぱに変更🌿）
st.markdown("<h1>🌿 原稿審査＆添削アシスタント</h1>", unsafe_allow_html=True)
st.markdown("---")

LIST_POSSIBLE_ID = '1dGJl6SfeuveynLJ8Q65JDZVymQLMGcyd5ZW5vBD02_8' 
LIST_PAST_ID = '1aftTvSvKS2yWxHNRNW6rDkrXTsXBw-mWqXViEfsLOMw' 

# サイドバー
st.sidebar.markdown("### ⚙️ アプリ設定")
pic_name = st.sidebar.selectbox("👤 スプシ登録用の担当者名", ["小山", "松下", "木村", "福島", "仲本"])

# ★画面上部の3つのタブ
tab1, tab2, tab3 = st.tabs(["🔍 1件スピード審査", "🚀 複数一括審査 (最大10件)", "📝 文章比較 ＆ 文字数チェック"])

# ==========================================
# タブ1：1件審査モード
# ==========================================
with tab1:
    st.markdown("### 🔍 1件スピード審査")
    st.write("求人IDを入力して、AIによる規定チェックを瞬時に実行します。")
    
    col_input, col_btn = st.columns([4, 1])
    with col_input:
        search_id = st.text_input("求人IDを入力してください", placeholder="例: 4445", label_visibility="collapsed")
    with col_btn:
        btn_single = st.button("✨ 判定実行", use_container_width=True, type="primary")

    if btn_single and search_id:
        try:
            with st.spinner('スプレッドシートからデータを取得中...'):
                df1 = load_cached_dataframe(LIST_POSSIBLE_ID)
                df2 = load_realtime_dataframe(LIST_PAST_ID, "転載確認シート")
                
            res1 = df1[df1['求人ID'] == search_id]

            if res1.empty:
                st.error("❌ 判定結果：掲載対象外（マスタ1に存在しません）")
            else:
                res2 = pd.DataFrame() if df2.empty else df2[df2['求人ID'] == search_id]

                if not res2.empty:
                    st.error("❌ 判定結果：掲載不可（過去掲載リストと重複しています）")
                    st.dataframe(res1, use_container_width=True)
                else:
                    st.success(f"✅ スプシ判定クリア！続けてAI審査を行います...（企業名: {res1.iloc[0]['企業名']}）")
                    with st.spinner('🤖 AIが規定をチェックしています...'):
                        ai_result = evaluate_job_with_ai(res1.iloc[0].to_dict())
                        
                        st.markdown("#### 🤖 AI審査レポート")
                        if "❌" in ai_result:
                            st.error(ai_result)
                        else:
                            st.success(ai_result)
                            
                            company_name = res1.iloc[0].get('企業名', '')
                            job_name = res1.iloc[0].get('求人名', '')
                            st.session_state.pending_regs[search_id] = [search_id, company_name, job_name, "", "", "", pic_name]
                            st.info("💡 審査をクリアしました！画面最下部の「カート」にストックしました。")
                        
                        with st.expander("▼ 審査に使用した元データを確認する"):
                            st.dataframe(res1, use_container_width=True)

        except Exception as e:
            st.error(f"エラーが発生しました: {e}")

# ==========================================
# タブ2：複数一括審査モード
# ==========================================
with tab2:
    st.markdown("### 🚀 複数一括審査")
    st.write("複数の求人IDを一気に判定し、結果をまとめて表示します。")
    
    search_ids_input = st.text_area("求人IDを入力（改行で複数入力可）", placeholder="4445\n4446\n4447", height=120)
    btn_multi = st.button("🚀 一括判定スタート", type="primary")
    
    if btn_multi and search_ids_input:
        raw_ids = search_ids_input.replace(',', '\n').split('\n')
        search_ids = list(dict.fromkeys([sid.strip() for sid in raw_ids if sid.strip()]))[:10]
        
        if not search_ids:
            st.warning("有効な求人IDが入力されていません。")
        else:
            try:
                with st.spinner('スプレッドシートからデータを取得中...'):
                    df1 = load_cached_dataframe(LIST_POSSIBLE_ID)
                    df2 = load_realtime_dataframe(LIST_PAST_ID, "転載確認シート")

                for i, sid in enumerate(search_ids):
                    st.markdown(f"#### 🎯 {i+1}件目: ID `{sid}`")
                    
                    res1 = df1[df1['求人ID'] == sid]
                    if res1.empty:
                        st.error("❌ マスタ1に存在しません")
                    else:
                        res2 = pd.DataFrame() if df2.empty else df2[df2['求人ID'] == sid]
                        if not res2.empty:
                            st.error("❌ 過去掲載リストと重複しています")
                        else:
                            with st.spinner('🤖 AIチェック中...'):
                                ai_result = evaluate_job_with_ai(res1.iloc[0].to_dict())
                                if "❌" in ai_result:
                                    st.error(ai_result)
                                else:
                                    st.success(ai_result)
                                    company_name = res1.iloc[0].get('企業名', '')
                                    job_name = res1.iloc[0].get('求人名', '')
                                    st.session_state.pending_regs[sid] = [sid, company_name, job_name, "", "", "", pic_name]
                    st.markdown("---")
            except Exception as e:
                st.error(f"エラーが発生しました: {e}")

# ==========================================
# タブ3：文章比較FBモード
# ==========================================
with tab3:
    st.markdown("### 📝 文章比較 ＆ 文字数・NGワードチェック")
    
    col_a, col_b = st.columns(2)
    with col_a:
        text_a = st.text_area("📄 【A】circus掲載内容 (元データ)", height=250)
    with col_b:
        text_b = st.text_area("✍️ 【B】Qmate掲載内容 (チェック対象)", height=250)

    try:
        ws_ng = get_worksheet(LIST_PAST_ID, "転載情報")
        ng_raw = ws_ng.acell('B2').value
        default_ng = ng_raw.replace("NGワード：", "").replace("NGワード:", "").replace("・", ", ").strip() if ng_raw else ""
    except:
        default_ng = "絶対, 必ず, 日本一, 最高"
        
    ng_words_input = st.text_input("🚫 今日のNGワード", value=default_ng)

    if st.button("✨ ミスチェック実行", type="primary"):
        if not text_a or not text_b:
            st.warning("AとBの両方に文章を入力してください！")
        else:
            st.markdown("#### 📊 文字数・表記チェック結果")
            matches = list(re.finditer(r'(\d+)\s*/\s*(\d+)', text_b))
            
            col_m1, col_m2, col_m3 = st.columns(3)
            col_m1.metric("全体文字数 (A)", f"{len(text_a)} 文字")
            col_m2.metric("全体文字数 (B)", f"{len(text_b)} 文字")
            col_m3.metric("文字数制限のチェック数", f"{len(matches)} 箇所")
            
            if matches:
                over_list = []
                for match in matches:
                    curr, m_max = int(match.group(1)), int(match.group(2))
                    if curr > m_max:
                        over_list.append((curr, m_max))
                
                if not over_list:
                    st.success(f"✨ すべての文字数制限（全{len(matches)}箇所）をクリアしています！")
                else:
                    st.error(f"❌ {len(over_list)}箇所の文字数オーバーが見つかりました！")
                    for curr, m_max in over_list:
                        st.write(f"・ ⚠️ **{curr} / {m_max}文字** （{curr - m_max}文字オーバー）")
            
            st.markdown("#### 🤖 AI 転記ミス・NGワードレポート")
            with st.spinner('AIがくまなく探しています...'):
                genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
                model = genai.GenerativeModel('gemini-2.5-flash')
                prompt = f"""
                あなたはプロの校正者です。
                以下の「circus掲載内容」と「Qmate掲載内容」を比較し、厳格にチェックを行ってください。
                【circus掲載内容】\n{text_a}\n
                【Qmate掲載内容】\n{text_b}\n
                【NGワード】\n{ng_words_input}\n
                1. 転記ミス・違いの指摘 (意味の変更、抜け漏れ、数字のズレ)
                2. NGワードチェック
                """
                response = model.generate_content(prompt, generation_config=genai.types.GenerationConfig(temperature=0.0))
                st.write(response.text)

# ==========================================
# ★共通：カート機能（登録待ちリスト）
# ==========================================
if st.session_state.pending_regs:
    st.markdown("<br><br>", unsafe_allow_html=True)
    st.markdown("---")
    st.markdown("## 🛒 スプシ登録待ちリスト")
    st.caption("審査をクリアした求人がここにストックされています。確認後、登録ボタンを押してください。")
    
    for sid, row_data in list(st.session_state.pending_regs.items()):
        with st.container():
            col1, col2 = st.columns([4, 1])
            with col1:
                st.info(f"🏢 **{row_data[1]}** (ID: `{sid}`) ／ 👤 担当: {row_data[6]}")
            with col2:
                if st.button("📝 スプシに登録", key=f"reg_{sid}", type="primary"):
                    try:
                        with st.spinner("登録中..."):
                            ws2 = get_worksheet(LIST_PAST_ID, "転載確認シート")
                            ws2.append_row(row_data)
                        st.success(f"「{row_data[1]}」を登録しました！")
                        del st.session_state.pending_regs[sid]
                        st.rerun()
                    except Exception as e:
                        st.error(f"登録エラー: {e}")





