import streamlit as st
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import pandas as pd
import google.generativeai as genai
import json
import re
import contextlib 

# --- ページ設定 ---
st.set_page_config(page_title="求人原稿 自動審査ツール", page_icon="☁️", layout="wide")

# --- 🤍 カスタムCSS ---
st.markdown("""
<style>
    /* 全体の背景 */
    .stApp { background-color: #F5F7FA !important; }
    /* 文字色 */
    h1, h2, h3, h4, h5, h6, p, span, label, div { color: #4A4A4A !important; }
    /* 区切り線 */
    hr { border-bottom: 2px solid #E2E8F0 !important; border-top: none !important; margin: 20px 0; }
    /* 入力欄 */
    .stTextInput input, .stTextArea textarea {
        background-color: #FFFFFF !important; color: #4A4A4A !important;
        border: 1px solid #D0D7E1 !important; border-radius: 12px !important;
    }
    .stTextInput input::placeholder, .stTextArea textarea::placeholder { color: #A0AABF !important; }
    .stSelectbox div[data-baseweb="select"] > div {
        background-color: #FFFFFF !important; border: 1px solid #D0D7E1 !important; border-radius: 12px !important;
    }
    /* ボタン */
    .stButton > button {
        background-color: #7A9EBA !important; color: #FFFFFF !important;
        border: none !important; border-radius: 12px !important; font-weight: bold !important;
        box-shadow: 0 4px 10px rgba(122, 158, 186, 0.3) !important; transition: all 0.3s ease;
    }
    .stButton > button:hover {
        background-color: #6385A1 !important; transform: translateY(-2px) !important;
    }
    /* ★修正：タブの赤い下線をくすみブルーに強制上書き！ */
    div[data-baseweb="tab-highlight"] {
        background-color: #7A9EBA !important;
    }
    .stTabs [data-baseweb="tab-list"] {
        border-bottom: 2px solid #E2E8F0 !important; background-color: transparent !important;
    }
    .stTabs [data-baseweb="tab"] { background-color: transparent !important; }
    .stTabs [data-baseweb="tab-list"] button [data-testid="stMarkdownContainer"] p {
        font-size: 18px !important; font-weight: bold !important; color: #7A9EBA !important;
    }
    /* パネル */
    [data-testid="stMetric"], [data-testid="stAlert"] {
        background-color: #FFFFFF !important; border: 1px solid #E2E8F0 !important;
        padding: 15px !important; border-radius: 12px !important; box-shadow: 0 4px 12px rgba(0,0,0,0.03) !important;
    }
    [data-testid="stDataFrame"] { background-color: #FFFFFF !important; border: 1px solid #E2E8F0 !important; border-radius: 8px !important; }
</style>
""", unsafe_allow_html=True)

# --- ★カスタムローディング画面 ---
@contextlib.contextmanager
def custom_spinner(text="処理中..."):
    placeholder = st.empty()
    with placeholder.container():
        st.markdown(f"<h4 style='text-align: center; color: #7A9EBA; margin-top: 20px;'>{text}</h4>", unsafe_allow_html=True)
        st.image("6FCDDAA6-C15B-45A9-89D6-B6B27AE3E5BC.gif", use_container_width=True)
    try:
        yield 
    finally:
        placeholder.empty() 

# --- 状態管理 ---
if "pending_regs" not in st.session_state: st.session_state.pending_regs = {}
if "multi_id_input" not in st.session_state: st.session_state.multi_id_input = ""
if "text_a_input" not in st.session_state: st.session_state.text_a_input = ""
if "text_b_input" not in st.session_state: st.session_state.text_b_input = ""

# --- 入力欄クリア用関数 ---
def clear_multi(): st.session_state.multi_id_input = ""
def clear_text_a(): st.session_state.text_a_input = ""
def clear_text_b(): st.session_state.text_b_input = ""
def clear_both():
    st.session_state.text_a_input = ""
    st.session_state.text_b_input = ""

# --- Googleスプシ接続 ＆ 読み込み関数 ---
@st.cache_resource
def get_worksheet(sheet_id, sheet_name=None):
    scope = ['https://spreadsheets.google.com/feeds','https://www.googleapis.com/auth/drive']
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    sh = client.open_by_key(sheet_id)
    return sh.worksheet(sheet_name) if sheet_name else sh.get_worksheet(0)

@st.cache_data(ttl=3600)
def load_cached_dataframe(sheet_id, sheet_name=None):
    ws = get_worksheet(sheet_id, sheet_name)
    all_data = ws.get_all_values()
    if len(all_data) < 2: return pd.DataFrame()
    df = pd.DataFrame(all_data[1:], columns=all_data[0])
    df.columns = [str(col).strip() for col in df.columns]
    df = df.loc[:, ~df.columns.duplicated()]
    return df.loc[:, df.columns != '']

def load_realtime_dataframe(sheet_id, sheet_name=None):
    ws = get_worksheet(sheet_id, sheet_name)
    all_data = ws.get_all_values()
    if len(all_data) < 2: return pd.DataFrame()
    df = pd.DataFrame(all_data[1:], columns=all_data[0])
    df.columns = [str(col).strip() for col in df.columns]
    df = df.loc[:, ~df.columns.duplicated()]
    return df.loc[:, df.columns != '']

@st.cache_data(ttl=3600)
def get_min_wage(sheet_id):
    try:
        ws = get_worksheet(sheet_id, "最低賃金")
        return ws.acell('A1').value
    except Exception:
        return "（最低賃金データが取得できませんでした）"

# --- 🤖 AI審査関数 ---
def evaluate_job_with_ai(job_data_dict, min_wage_text):
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    model = genai.GenerativeModel('gemini-2.5-flash')
    
    prompt = f"""
    あなたは厳格かつ「親切な」求人原稿の審査プロフェッショナルです。
    提供された【求人データ】が、【インディード判定事項まとめ（審査基準）】を満たしているか検証し、修正担当者が一目で分かるよう具体的なボーダーライン（数値）を添えてフィードバックしてください。

    【求人データ】\n{json.dumps(job_data_dict, ensure_ascii=False, indent=2)}\n
    
    【各都道府県の最新・最低賃金データ】\n{min_wage_text}\n
    
    ---
    【審査ステップと判定レベル】
    判定は「✅ 掲載可」「⚠️ 要確認（注意）」「❌ 掲載不可」の3段階で行います。
    明確な規定違反は「❌ 掲載不可」、情報不足により違反の可能性がある場合は「⚠️ 要確認（注意）」として、具体的な基準値を提示してください。

    ■ ステップ1：情報の構造化（抽出）
    求人データから「勤務地、最低賃金、基本給、固定残業代（金額/時間）、各種手当、年間休日日数、1日の労働時間、雇用形態」を抽出してください。

    ■ ステップ2：審査基準に基づく親切な検証

    1. 基本給・月給に関する事項
    - 【最低賃金割れ】：基本給（時給換算額）+一律手当(下記※①参考)が勤務地の最低賃金を満たしているか。試用期間中も同様に検証すること。
    - 【休日数不明による警告】：年間休日日数が不明な場合、いきなりNGにせず「⚠️ 要確認」とする。「現在の給与額の場合、年間休日が〇〇日未満だと最低賃金を下回ります（〇〇日以上ならクリア）」と、逆算した具体的なボーダーラインを提示すること。
    - 【内訳不明】：月給は固定手当を含めた表記とあるが、内訳（基本給と手当の割合）が不明な場合は「⚠️ 要確認」とする。

    2. 固定残業代に関する事項
    - 【明記の必須】：金額や時間の記載がない、または片方のみの場合は「❌ 掲載不可」とする。
    - 【割増賃金の警告】：適正な割増賃金を下回る可能性がある場合、「⚠️ 要確認：設定額が法定の割増賃金を下回っている可能性があります。正しい金額は〇〇円以上です」と提示すること。
    - 【36協定の警告】：固定残業時間が45時間を超える記載（例：60時間）がある場合、「❌ 掲載不可：原則45時間を超える場合、36協定の特別条項などの書類が必要のため掲載不可です」と明記すること。

    3. 各種手当に関する事項
    - 【詳細の明記】：一律手当(下記※①参考)の手当名や金額が不明な場合は「⚠️ 要確認：手当の名称（または金額）を追記してください」とする。
　　　　　　　　　　　※①## 最低賃金の計算に「含まれる」もの
　　　　　　　　　　　毎月固定で支払われる、労働そのものに対する対価は基本的にすべて含まれます。
　　　　　　　　　　　基本給/各種手当（毎月定額のもの）/役職手当（店長手当、マネージャー手当などで毎月定額のもの）/職能手当や職務手当（毎月定額のもの）/資格手当（毎月定額のもの）/地域手当（毎月定額のもの）/住宅手当（※毎月定額のもので条件に関わらず一律支給されるものなど）/歩合給（出来高払給）
           　　　　　　## 最低賃金の計算から「除外される」もの（要注意！）
　　　　　　　　　　　　計算する際に間違えやすいのがこちらです。以下の7つは、法律で**「最低賃金の計算に含めてはいけない」**と決められています。これらはお給料から差し引いて計算しなければなりません。
　　　　　　　　　　　　通勤手当（交通費）/家族手当（扶養手当など）/精皆勤手当（皆勤手当など）/時間外割増賃金（残業代）/休日割増賃金（休日出勤手当）/深夜割増賃金（深夜の割増分）/臨時に支払われる賃金やボーナス（結婚手当、賞与など1ヶ月を超える期間ごとに支払われるもの）

    4. 労働時間に関する事項
    - 【法定労働時間】：「労働時間が8.5時間」など法定の8時間を超えている記載がある場合は「⚠️ 要確認：法定労働時間の8時間を超えている点の確認が必要です」とする。

    5. その他の記載不備
    - 【矛盾検知】：タイトルと勤務地に矛盾がある場合は「⚠️ 要確認」とする。

    ■ ステップ3：出力フォーマット
    結果を以下の構成で、見やすくマークダウン形式で出力してください。JSON形式はアプリ上でコードとして表示されてしまうため絶対に使用しないでください。

    ### 総合判定ステータス: [✅ 掲載可 または ⚠️ 要確認 または ❌ 掲載不可]

    #### フィードバックリスト
    （※問題がない場合は「✅ 規定違反や確認が必要な項目はありません」と出力）
    - **[⚠️ 要確認 または ❌ 掲載不可] 該当項目名**
      具体的な理由とボーダーライン（例：年間休日日数が不明です。現在の月給20万円・1日8時間労働の場合、年間休日が【112日未満】だと愛知県の最低賃金を下回るためアウトになります。【112日以上】であればクリアです。日数を追記してください。）
    """
    response = model.generate_content(prompt, generation_config=genai.types.GenerationConfig(temperature=0.0))
    return response.text

# --- メイン設定 ---
st.markdown("<h1>☁️ 原稿審査＆添削アシスタント</h1>", unsafe_allow_html=True)
st.markdown("---")

LIST_POSSIBLE_ID = '1dGJl6SfeuveynLJ8Q65JDZVymQLMGcyd5ZW5vBD02_8' 
LIST_PAST_ID = '1aftTvSvKS2yWxHNRNW6rDkrXTsXBw-mWqXViEfsLOMw' 

st.sidebar.markdown("### ⚙️ アプリ設定")
pic_name = st.sidebar.selectbox("👤 スプシ登録用の担当者名", ["小山", "松下", "木村", "福島", "仲本"])

tab1, tab2, tab3 = st.tabs(["🤍 1件スピード審査", "☁️ 複数一括審査 (最大10件)", "🫧 文章比較 ＆ 文字数チェック"])

# ==========================================
# タブ1：1件審査モード
# ==========================================
with tab1:
    st.markdown("### 🤍 1件スピード審査")
    col_input, col_btn = st.columns([4, 1])
    with col_input:
        search_id = st.text_input("求人IDを入力してください", placeholder="例: 4445", label_visibility="collapsed")
    with col_btn:
        btn_single = st.button("✨ 判定実行", use_container_width=True, type="primary")

    if btn_single and search_id:
        try:
            with custom_spinner('☁️ スプレッドシートからデータを取得中...'):
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
                    
                    with custom_spinner('🪄 AIが規定をチェックしています...'):
                        min_wage_data = get_min_wage(LIST_POSSIBLE_ID)
                        ai_result = evaluate_job_with_ai(res1.iloc[0].to_dict(), min_wage_data)
                        
                        st.markdown("#### 🤖 AI審査レポート")
                        
                        # ★アップデート：「⚠️ 要確認」の場合でもカートにストックするように修正！
                        if "❌" in ai_result:
                            st.error(ai_result)
                        else:
                            if "⚠️" in ai_result:
                                st.warning(ai_result) 
                                st.info("💡 審査は「要確認」ですが、画面最下部の「カート」にストックしました。内容を確認後、スプシに登録してください。")
                            else:
                                st.success(ai_result) 
                                st.info("💡 審査を完全にクリアしました！画面最下部の「カート」にストックしました。")
                                
                            company_name = res1.iloc[0].get('企業名', '')
                            job_name = res1.iloc[0].get('求人名', '')
                            st.session_state.pending_regs[search_id] = [search_id, company_name, job_name, "", "", "", pic_name]
                        
                        with st.expander("▼ 審査に使用した元データを確認する"):
                            st.dataframe(res1, use_container_width=True)

        except Exception as e:
            st.error(f"エラーが発生しました: {e}")

# ==========================================
# タブ2：複数一括審査モード
# ==========================================
with tab2:
    col_title, col_clear = st.columns([4, 1])
    with col_title:
        st.markdown("### ☁️ 複数一括審査")
    with col_clear:
        st.button("🗑️ 入力欄を空にする", on_click=clear_multi, use_container_width=True)
        
    search_ids_input = st.text_area("求人IDを入力（改行で複数入力可）", placeholder="4445\n4446\n4447", height=120, key="multi_id_input")
    btn_multi = st.button("✨ 一括判定スタート", type="primary")
    
    if btn_multi and search_ids_input:
        raw_ids = search_ids_input.replace(',', '\n').split('\n')
        search_ids = list(dict.fromkeys([sid.strip() for sid in raw_ids if sid.strip()]))[:10]
        
        if not search_ids:
            st.warning("有効な求人IDが入力されていません。")
        else:
            try:
                with custom_spinner('☁️ スプレッドシートからデータを取得中...'):
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
                            with custom_spinner(f'🪄 ID:{sid} をAIチェック中...'):
                                min_wage_data = get_min_wage(LIST_POSSIBLE_ID)
                                ai_result = evaluate_job_with_ai(res1.iloc[0].to_dict(), min_wage_data)
                                
                                # ★一括モードでも「⚠️ 要確認」をカートにストックするように修正！
                                if "❌" in ai_result:
                                    st.error(ai_result)
                                else:
                                    if "⚠️" in ai_result:
                                        st.warning(ai_result)
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
    st.markdown("### 🫧 文章比較 ＆ 文字数・NGワードチェック")
    
    col_btn_a, col_btn_b, col_btn_both = st.columns([1, 1, 1.5])
    with col_btn_a:
        st.button("🗑️ 【A】を空にする", on_click=clear_text_a, use_container_width=True)
    with col_btn_b:
        st.button("🗑️ 【B】を空にする", on_click=clear_text_b, use_container_width=True)
    with col_btn_both:
        st.button("🗑️ AとBを両方空にする", on_click=clear_both, use_container_width=True)
        
    col_a, col_b = st.columns(2)
    with col_a:
        text_a = st.text_area("📄 【A】circus掲載内容 (元データ)", height=250, key="text_a_input")
    with col_b:
        text_b = st.text_area("✍️ 【B】Qmate掲載内容 (チェック対象)", height=250, key="text_b_input")

    try:
        ws_ng = get_worksheet(LIST_PAST_ID, "転載情報")
        ng_raw = ws_ng.acell('B2').value
        default_title_ng = ng_raw.replace("\n", "").replace("NGワード：", "").replace("NGワード:", "").replace("・", ", ").strip() if ng_raw else ""
    except:
        default_title_ng = "です, ます, ませんか, がっつり, 年収, 収入, OK, 手当, 祝金, 歓迎, 月収, 見舞金, 🔶"
        
    default_body_ng = "祝金, 見舞金, ボーナス, 🔶"
    
    st.markdown("##### 🚫 NGワード設定")
    col_ng1, col_ng2 = st.columns(2)
    with col_ng1:
        ng_title_input = st.text_input("タイトル用 NGワード（タイトルのみ判定）", value=default_title_ng)
    with col_ng2:
        ng_body_input = st.text_input("求人全体用 NGワード（全体を判定）", value=default_body_ng)

    if st.button("✨ ミスチェック実行", type="primary"):
        if not text_a or not text_b:
            st.warning("AとBの両方に文章を入力してください！")
        else:
            st.markdown("#### 📊 文字数・表記チェック結果")
            
            lines = text_b.split('\n')
            matches_total = len(list(re.finditer(r'(\d+)\s*/\s*(\d+)', text_b)))
            
            col_m1, col_m2, col_m3 = st.columns(3)
            col_m1.metric("全体文字数 (A)", f"{len(text_a)} 文字")
            col_m2.metric("全体文字数 (B)", f"{len(text_b)} 文字")
            col_m3.metric("文字数制限のチェック数", f"{matches_total} 箇所")
            
            over_list = []
            clear_count = 0
            
            for i, line in enumerate(lines):
                matches = list(re.finditer(r'(\d+)\s*/\s*(\d+)', line))
                for match in matches:
                    curr, m_max = int(match.group(1)), int(match.group(2))
                    if curr > m_max:
                        prev_line = lines[i-1] if i > 0 else ""
                        next_line = lines[i+1] if i < len(lines)-1 else ""
                        context = f"{prev_line}\n**{line}**\n{next_line}".strip()
                        over_list.append((curr, m_max, context))
                    else:
                        clear_count += 1
            
            if matches_total > 0:
                if not over_list:
                    st.success(f"✨ すべての文字数制限（全{clear_count}箇所）をクリアしています！")
                else:
                    st.error(f"❌ {len(over_list)}箇所の文字数オーバーが見つかりました！")
                    for curr, m_max, context in over_list:
                        with st.expander(f"⚠️ {curr} / {m_max}文字 （{curr - m_max}文字オーバー） - 前後の文章を見る", expanded=True):
                            st.markdown(context)
            
            st.markdown("#### 🤖 AI 転記ミス・NGワードレポート")
            with custom_spinner('🪄 AIがくまなく探しています...'):
                genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
                model = genai.GenerativeModel('gemini-2.5-flash')
                prompt = f"""
                あなたはプロの校正者です。
                以下の「circus掲載内容（元データ）」と「Qmate掲載内容（作成原稿）」を比較し、厳格にチェックを行ってください。

                【circus掲載内容】\n{text_a}\n
                【Qmate掲載内容】\n{text_b}\n

                【チェック項目1：意味の比較・転記ミス】
                ⚠️重要：「株式会社ライフアップ」は我々の自社名（求人作成代理店名）です。Qmate掲載内容の中に「株式会社ライフアップ」という記載があっても、「AとBで企業名が違う」というエラーには絶対にしないでください。Qmate側の本当の企業名は「掲載企業名」などの項目に記載されているので、そこを見てcircus側の企業名と一致しているか確認してください。
                - AとBで文章の流れや項目名が違っても、「給与35万〜」と「想定月収35万〜」のように、言っている意味（条件）が同じならOKとしてください。
                - ただし、条件の数字の転記ミス、重要な条件の抜け漏れがあれば、「どこがどう間違っているか」を指摘してください。
                - 特にミスがなければ「✅ 転記ミスや条件の抜け漏れはありません」と出力してください。

                【チェック項目2：NGワード判定（※完全一致のみ！）】
                以下のルールに従い、Qmate掲載内容の中に「指定されたNGワードそのもの（完全一致）」が含まれていないかチェックしてください。
                ⚠️超重要：AIの独自の判断で「意味が似ている言葉（類語）」や「代替表現（例：手当→あり等）」をNGワードとして拡大解釈・誤検知することは絶対にやめてください。リストにある文字列と一言一句同じ場合のみ指摘してください。

                - タイトル判定用NGワード: {ng_title_input} （※Qmate掲載内容の中で「職種名」や「タイトル」と思われる部分のみをチェック）
                - 求人全体判定用NGワード: {ng_body_input} （※Qmate掲載内容のすべての文章をチェック）
                - 【完全一致】で見つかった場合は「〇〇という言葉がNGワードに該当します。〇〇と言い換えてください」と具体的な修正案を提示してください。
                - 見つからない場合は「✅ NGワードは含まれていません」と出力してください。
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
                        with custom_spinner("☁️ スプシに登録中..."):
                            ws2 = get_worksheet(LIST_PAST_ID, "転載確認シート")
                            ws2.append_row(row_data)
                        st.success(f"「{row_data[1]}」を登録しました！")
                        del st.session_state.pending_regs[sid]
                        st.rerun()
                    except Exception as e:
                        st.error(f"登録エラー: {e}")



