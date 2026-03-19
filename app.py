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
        st.image("D5E80210-94A2-4161-9741-AEF73B4129DA.gif", use_container_width=True)
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

# --- 🤖 AI審査関数（タブ1・タブ2用） ---
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
    - 【最低賃金割れ】：基本給+一律手当(下記※①参考)=合計給与（時給換算額）が勤務地の最低賃金を満たしているか。試用期間中も同様に検証すること。
    - 【休日数不明による警告】：年間休日日数が不明な場合、いきなりNGにせず「⚠️ 要確認」とする。「現在の給与額の場合、年間休日が〇〇日未満だと最低賃金を下回ります（〇〇日以上ならクリア）」と、逆算した具体的なボーダーラインを提示すること。
    - 【内訳不明】：年収ではなく月給に固定手当を含めた表記とあるが、内訳（基本給と手当の割合）が不明な場合は「⚠️ 要確認」とする。

    2. 固定残業代に関する事項
    - 【明記の必須】：金額や時間の記載がない、または片方のみの場合は「❌ 掲載不可」とする。
    - 【割増賃金の警告】：適正な割増賃金を下回る可能性がある場合、「⚠️ 要確認：設定額が法定の割増賃金を下回っている可能性があります。正しい金額は〇〇円以上です」と提示すること。
    - 【36協定違反の絶対NG（重要）】：固定残業時間が「45時間」を1時間でも超える記載（例：46時間、60時間など）がある場合は、他の条件がクリアしていても無条件で「❌ 掲載不可：原則45時間を超える場合、36協定の特別条項などの書類が必要のため掲載不可です」と明記すること。※45時間ちょうどの場合はOK。

    3. 各種手当に関する事項
    - 【詳細の明記】：一律手当(下記※①参考)の手当名や金額が不明な場合は「⚠️ 要確認：手当の名称（または金額）を追記してください」とする。
      ※① 一律手当「含まれる」もの：毎月固定で支払われる、労働そのものに対する対価（基本給/各種手当/役職手当/職能手当/資格手当/地域手当/条件に関わらず一律支給される住宅手当/歩合給など）
      ※除外されるもの（最低賃金計算に含めない）：通勤手当/家族手当/精皆勤手当/時間外割増賃金/休日割増賃金/深夜割増賃金/臨時に支払われる賃金やボーナス

    4. 労働時間に関する事項
    - 【法定労働時間】：「労働時間が8.5時間」など法定の8時間を超えている記載がある場合は「⚠️ 要確認：法定労働時間の8時間を超えている点の確認が必要です」とする。

    5. その他の記載不備
    - 【矛盾検知】：タイトルと勤務地に矛盾がある場合は「⚠️ 要確認」とする。

    ■ ステップ3：出力フォーマット
    結果を以下の構成で、見やすくマークダウン形式で出力してください。JSON形式は絶対に使用しないでください。

    ### 総合判定ステータス: [✅ 掲載可 または ⚠️ 要確認 または ❌ 掲載不可]

    #### フィードバックリスト
    （※問題がない場合は「✅ 規定違反や確認が必要な項目はありません」と出力）
    - **[⚠️ 要確認 または ❌ 掲載不可] 該当項目名**
      具体的な理由とボーダーライン（例：年間休日日数が不明です。現在の月給20万円・1日8時間労働の場合、年間休日が【112日未満】だと愛知県の最低賃金を下回るためアウトになります。【112日以上】であればクリアです。日数を追記してください。）
    
    ##### 【審査に使用した抽出情報】
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
                                import time
                                if i > 0:
                                    time.sleep(4) 
                                    
                                min_wage_data = get_min_wage(LIST_POSSIBLE_ID)
                                ai_result = evaluate_job_with_ai(res1.iloc[0].to_dict(), min_wage_data)
                                
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

   # ★アップデート：NGワードに加え、AIの「無視リスト（B4）」もスプシから読み込む
    try:
        ws_ng = get_worksheet(LIST_PAST_ID, "転載情報")
        # B2: タイトル用
        ng_raw_title = ws_ng.acell('B2').value
        default_title_ng = ng_raw_title.replace("\n", "").replace("NGワード：", "").replace("NGワード:", "").replace("・", ", ").strip() if ng_raw_title else ""
        
        # B3: 本文用
        ng_raw_body = ws_ng.acell('B3').value
        default_body_ng = ng_raw_body.replace("\n", "").replace("NGワード：", "").replace("NGワード:", "").replace("・", ", ").strip() if ng_raw_body else ""

        # B4: AIチェック無視リスト（新規追加）
        ignore_raw = ws_ng.acell('B4').value
        default_ignore_list = ignore_raw.replace("\n", "").strip() if ignore_raw else "従業員数, 事業内容, 募集背景, 募集期間, 組織構成, 選考フロー, 応募資格"
    except:
        default_title_ng = ""
        default_body_ng = ""
        default_ignore_list = "従業員数, 事業内容, 募集背景, 募集期間, 組織構成, 選考フロー, 応募資格"
    
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
            # ---------------------------------------------
            # ① 文字数チェック（Pythonコード）
            # ---------------------------------------------
            st.markdown("#### 📊 文字数制限チェック (システム自動判定)")
            
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

            # ---------------------------------------------
            # ② NGワード・チェック結果 (Pythonコードによる完全一致判定)
            # ---------------------------------------------
            st.markdown("#### 🚫 NGワード・チェック結果 (システム自動判定)")
            
            ng_title_list = [w.strip() for w in ng_title_input.split(',') if w.strip()]
            ng_body_list = [w.strip() for w in ng_body_input.split(',') if w.strip()]

            # ユーザー指定の法則で「タイトル部分」を抽出（保険として最初の10行も）
            title_match = re.search(r'職種名必須\s*\n(.*?)\n\d+/\d+文字', text_b)
            title_text = title_match.group(1) if title_match else "\n".join(text_b.split('\n')[:10])

            # ★アップデート：全角・半角スペースを裏側で除去した「判定用テキスト」を作成
            title_text_clean = title_text.replace(" ", "").replace("　", "")
            text_b_clean = text_b.replace(" ", "").replace("　", "")

            ng_errors = []
            
            # タイトルのNGワード判定
            for w in ng_title_list:
                w_clean = w.replace(" ", "").replace("　", "")
                if w_clean and w_clean in title_text_clean:
                    ng_errors.append(f"【タイトル】「**{w}**」が含まれています。削除してください。")
            
            # 本文のNGワード判定
            for w in ng_body_list:
                w_clean = w.replace(" ", "").replace("　", "")
                if w_clean and w_clean in text_b_clean:
                    if w_clean in ["祝金", "見舞金", "お見舞金"]:
                        ng_errors.append(f"【全体】「**{w}**」が含まれています。「手当」に記載を変更してください。")
                    else:
                        ng_errors.append(f"【全体】「**{w}**」が含まれています。削除してください。")

            if not ng_errors:
                st.success("✨ タイトル・本文ともにNGワードは一切含まれていません！")
            else:
                for err in ng_errors:
                    st.error(f"❌ {err}")

            # ---------------------------------------------
            # ③ 転記ミス・内容比較レポート（AI判定）
            # ---------------------------------------------
            st.markdown("#### 🤖 AI 転記ミス・内容比較レポート")
            with custom_spinner('🪄 AIが条件の転記ミスをくまなく探しています...'):
                genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
                model = genai.GenerativeModel('gemini-2.5-flash')
                
                # ★ステップ③：プロンプトの整理 ＆ 無視リストのB4セル連動
                prompt = f"""
                あなたはプロの校正者です。
                以下の「circus掲載内容（元データ）」と「Qmate掲載内容（作成原稿）」を比較し、給与や勤務地などの「重要な労働条件」に転記ミスや抜け漏れがないか厳格にチェックしてください。

                【circus掲載内容】\n{text_a}\n
                【Qmate掲載内容】\n{text_b}\n

                ---
                ### 審査基準とルール

                #### 1. 許容する違い（エラーとして指摘しないこと）
                - **表現の揺れ:** 「給与35万〜」と「想定月収35万〜」など、意味や条件が同じであればOK。
                - **自社名の記載:** Qmate側に「株式会社ライフアップ」の記載があっても、掲載企業名がcircus側と一致していればOK。
                - **勤務地の絞り込み:** circus側に複数勤務地があっても、Qmate側にそのうちの1つが記載されていればOK。
                - **給与の桁数・詳細化:** circus側の「33.3万円」に対し、Qmate側に「333,333円」とある場合、circus側のどこか（補足欄など）に詳細な記載があればOK。
                - **NGワードの意図的な修正:** circus側にある「祝金」「見舞金」「面接」等の言葉が、Qmate側で「手当」「選考」と言い換えられている、または削除されている場合は作成者の正しい対応のためOK。

                #### 2. 厳格にチェックする項目（エラーとして指摘すること）
                - **重要な条件の数値ミス:** 基本給、休日数、労働時間などの数字の間違いや明らかな抜け漏れ。
                - **固定残業代の入力箇所:** circus側に固定残業代の記載がある場合、Qmate側の『固定残業代必須』『固定残業時間必須』などの**専用入力欄**に正しく転記されていること。本文（勤務時間詳細など）に書かれていても、専用欄が空欄ならエラーとして指摘。

                #### 3. 審査対象外（絶対に指摘・エラー検知しないこと）🛑超重要
                以下の項目はシステム上の仕様や文字数制限の都合であるため、違いや抜け漏れ、矛盾を見つけても**完全に無視（指摘不要）**してください。勝手な粗探しは厳禁です。
                - Qmateの入力ルール違反（職種名の修飾語の有無など）や、年齢制限などの論理的矛盾
                - 「福利厚生・待遇」の細かすぎる内訳の抜け漏れ（※文字数制限で省略されることが多いため、社会保険など極めて重要なもの以外は無視）
                - 以下の項目（スプレッドシート指定の除外リスト）に関する抜け漏れや違い:
                  【 {default_ignore_list} 】

                ---
                ### 出力フォーマット
                上記「2. 厳格にチェックする項目」に該当するミスがあれば、「どこがどう間違っているか」を箇条書きで分かりやすく指摘してください。
                特にミスがなければ、以下の文言のみを出力してください。
                「✅ 転記ミスや条件の抜け漏れはありません」
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
