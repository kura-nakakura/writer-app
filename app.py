import streamlit as st
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import pandas as pd
import google.generativeai as genai
import json

# --- ページ設定 ---
st.set_page_config(page_title="判定＆添削ツール", layout="wide")

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

# --- 🤖 Google AI (Gemini) 自動審査関数 ---
def evaluate_job_with_ai(job_data_dict):
    # SecretsからGoogleのAIキーを読み込んで設定
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    
    model = genai.GenerativeModel('gemini-2.5-flash')
    
    prompt = f"""
    あなたは厳格な求人原稿の審査プロフェッショナルです。
    以下の【求人データ】が、【審査規定】を満たしているかチェックしてください。

    【求人データ】
    {json.dumps(job_data_dict, ensure_ascii=False, indent=2)}

    【審査規定】
    1. 基本給・月給: 最低賃金割れの懸念がないか。金額や内訳(基本給と手当の割合)が不明瞭でないか。
    2. 固定残業代: 「金額」と「時間」の両方が明記されているか。原則45時間を超える記載(36協定の懸念)や範囲が不明確な記載がないか。
    3. 各種手当: 手当の名称や詳細が不明なまま金額だけ記載されていないか。
    4. 労働時間・休日: 年間休日日数の記載が抜けていないか(必須)。1日の労働時間が法定(8時間)を超えていないか。
    5. その他: 勤務地やタイトルなどに矛盾がないか。

    【出力形式】
    規定違反が1つでもある場合は「❌ 掲載不可」とし、どの規定にどう違反しているか具体的な理由を提示してください。
    すべての規定をクリアしている場合は「✅ 掲載可」と出力してください。
    """
    
    # AIにリクエストを送信（ルールを厳守させるため temperature=0.0 に設定）
    response = model.generate_content(
        prompt,
        generation_config=genai.types.GenerationConfig(temperature=0.0)
    )
    return response.text

# --- メイン設定 ---
# --- メイン設定 ---
st.title("🚀 業務効率化アプリ")

LIST_POSSIBLE_ID = '1dGJl6SfeuveynLJ8Q65JDZVymQLMGcyd5ZW5vBD02_8' 
LIST_PAST_ID = '1aftTvSvKS2yWxHNRNW6rDkrXTsXBw-mWqXViEfsLOMw' 

# ★モードを3種類に増やしました！
mode = st.sidebar.selectbox("モード選択", ["1件検索&AI判定", "複数一括判定(最大10件)", "文章比較FB"])

# ==========================================
# モード1：従来の1件ずつ丁寧に見るモード
# ==========================================
if mode == "1件検索&AI判定":
    st.subheader("🔍 求人ID 1件判定 ＆ AI自動審査")
    search_id = st.text_input("検索したい「求人ID」を入力", placeholder="例: 4445")
    
    if st.button("判定実行"):
        if search_id:
            try:
                with st.spinner('掲載可能リストを確認中...'):
                    ws1 = get_worksheet(LIST_POSSIBLE_ID)
                    all_data1 = ws1.get_all_values()
                    df1 = pd.DataFrame(all_data1[1:], columns=all_data1[0])
                    df1.columns = [str(col).strip() for col in df1.columns]
                    df1 = df1.loc[:, ~df1.columns.duplicated()]
                    df1 = df1.loc[:, df1.columns != '']
                    
                    res1 = df1[df1['求人ID'] == search_id]

                if res1.empty:
                    st.error(f"❌ 判定結果：掲載対象外（リストに存在しません）")
                else:
                    st.info(f"💡 掲載可能リストに存在します（企業名: {res1.iloc[0]['企業名']}）")
                    
                    with st.spinner('過去掲載リストと照合中...'):
                        ws2 = get_worksheet(LIST_PAST_ID, "転載確認シート")
                        all_data2 = ws2.get_all_values()
                        
                        if len(all_data2) < 2:
                            df2 = pd.DataFrame()
                        else:
                            df2 = pd.DataFrame(all_data2[1:], columns=all_data2[0])
                            df2.columns = [str(col).strip() for col in df2.columns]
                            df2 = df2.loc[:, ~df2.columns.duplicated()]
                            df2 = df2.loc[:, df2.columns != '']
                            
                            if '求人ID' not in df2.columns:
                                st.error("❌ マスタ2の1行目に「求人ID」という項目が見つかりません。")
                                st.stop()
                                
                        res2 = pd.DataFrame() if df2.empty else df2[df2['求人ID'] == search_id]

                    if not res2.empty:
                        st.error("❌ 判定結果：掲載不可（過去掲載リストと重複しています）")
                        st.dataframe(res1)
                    else:
                        st.success("✅ スプシ判定クリア！続けてAI審査を行います...")
                        
                        with st.spinner('🤖 AIが規定をチェックしています...'):
                            job_data_dict = res1.iloc[0].to_dict()
                            ai_result = evaluate_job_with_ai(job_data_dict)
                            
                            st.markdown("### 🤖 AI自動審査レポート")
                            if "❌" in ai_result:
                                st.error(ai_result)
                            else:
                                st.success(ai_result)
                            
                            st.write("▼ 審査に使用したデータ")
                            st.dataframe(res1)

            except Exception as e:
                st.error(f"エラーが発生しました: {e}")

# ==========================================
# モード2：新搭載の複数一括モード
# ==========================================
elif mode == "複数一括判定(最大10件)":
    st.subheader("🔍 求人ID 複数一括判定 ＆ AI自動審査 (最大10件)")
    search_ids_input = st.text_area(
        "検索したい「求人ID」を入力（改行して複数入力できます）", 
        placeholder="例:\n4445\n4446\n4447",
        height=150
    )
    
    if st.button("一括判定実行"):
        if search_ids_input:
            raw_ids = search_ids_input.replace(',', '\n').split('\n')
            search_ids = [sid.strip() for sid in raw_ids if sid.strip()]
            search_ids = list(dict.fromkeys(search_ids))[:10]
            
            if not search_ids:
                st.warning("有効な求人IDが入力されていません。")
                st.stop()
                
            st.info(f"💡 合計 {len(search_ids)} 件の判定を開始します...")

            try:
                # 3万件あっても、ここで「1回だけ」一気に読み込みます！
                with st.spinner('スプレッドシートの全体データを読み込み中...（通信は1回だけ！）'):
                    ws1 = get_worksheet(LIST_POSSIBLE_ID)
                    all_data1 = ws1.get_all_values()
                    df1 = pd.DataFrame(all_data1[1:], columns=all_data1[0])
                    df1.columns = [str(col).strip() for col in df1.columns]
                    df1 = df1.loc[:, ~df1.columns.duplicated()]
                    df1 = df1.loc[:, df1.columns != '']
                    
                    ws2 = get_worksheet(LIST_PAST_ID, "転載確認シート")
                    all_data2 = ws2.get_all_values()
                    if len(all_data2) < 2:
                        df2 = pd.DataFrame()
                    else:
                        df2 = pd.DataFrame(all_data2[1:], columns=all_data2[0])
                        df2.columns = [str(col).strip() for col in df2.columns]
                        df2 = df2.loc[:, ~df2.columns.duplicated()]
                        df2 = df2.loc[:, df2.columns != '']
                        
                        if '求人ID' not in df2.columns:
                            st.error("❌ マスタ2の1行目に「求人ID」という項目が見つかりません。")
                            st.stop()

                # 読み込んだデータの中から、10件分を一瞬で探し出します
                for i, search_id in enumerate(search_ids):
                    st.markdown("---") 
                    st.markdown(f"### 🎯 {i+1}件目: 求人ID `{search_id}`")
                    
                    res1 = df1[df1['求人ID'] == search_id]
                    
                    if res1.empty:
                        st.error("❌ 判定結果：掲載対象外（マスタ1に存在しません）")
                    else:
                        st.info(f"💡 掲載可能リストに存在します（企業名: {res1.iloc[0]['企業名']}）")
                        
                        res2 = pd.DataFrame() if df2.empty else df2[df2['求人ID'] == search_id]

                        if not res2.empty:
                            st.error("❌ 判定結果：掲載不可（過去掲載リストと重複しています）")
                            st.dataframe(res1)
                        else:
                            st.success("✅ スプシ判定クリア！続けてAI審査を行います...")
                            
                            with st.spinner(f'🤖 ID:{search_id} をAIがチェックしています...'):
                                job_data_dict = res1.iloc[0].to_dict()
                                ai_result = evaluate_job_with_ai(job_data_dict)
                                
                                if "❌" in ai_result:
                                    st.error(ai_result)
                                else:
                                    st.success(ai_result)
                                
                                with st.expander("▼ 審査に使用したデータ（クリックで開く）"):
                                    st.dataframe(res1)

            except Exception as e:
                st.error(f"エラーが発生しました: {e}")

# ==========================================
# モード3：文章比較FB（ミスチェック）
# ==========================================
elif mode == "文章比較FB":
    st.subheader("📝 文章比較 ＆ ミス・NGワードチェック")
    st.write("元となる文章（A）と、チェックしたい文章（B）を貼り付けてください。")

    # 画面を左右に分割して入力しやすくする（見た目もスッキリ！）
    col1, col2 = st.columns(2)
    
    with col1:
        text_a = st.text_area("【A】元文章（正しいデータ）", height=200, placeholder="ここに元の文章を貼り付けます")
    
    with col2:
        text_b = st.text_area("【B】比較文章（チェック対象）", height=200, placeholder="ここに作成した文章を貼り付けます")

    # NGワードをユーザーが自由に入力・変更できるようにする
    ng_words_input = st.text_input("🚫 NGワード（カンマ区切りで入力）", value="絶対, 必ず, 日本一, 最高")

    if st.button("ミスチェック実行"):
        if not text_a or not text_b:
            st.warning("AとBの両方に文章を入力してください！")
            st.stop()

        # 1. まずはPythonによる「文字数カウント」（AIを使わないので一瞬で正確に出ます）
        st.markdown("### 📊 文字数カウント")
        st.info(f"【A】元文章: **{len(text_a)}文字** ／ 【B】比較文章: **{len(text_b)}文字**")
        
        # 差分（文字数の違い）を計算
        diff = len(text_b) - len(text_a)
        if diff > 0:
            st.write(f"👉 Bの文章の方が {abs(diff)} 文字 **多い** です。")
        elif diff < 0:
            st.write(f"👉 Bの文章の方が {abs(diff)} 文字 **少ない** です。")
        else:
            st.write("👉 文字数はピッタリ同じです！")

        # 2. Geminiによる「転記ミス＆NGワードチェック」
        with st.spinner('🤖 AIが違いとNGワードをくまなく探しています...'):
            try:
                # APIキーの設定（念のためここでも宣言）
                import google.generativeai as genai
                genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
                model = genai.GenerativeModel('gemini-2.5-flash')
                
                # AIへの指示書（プロンプト）
                prompt = f"""
                あなたはプロの校正者です。
                以下の「元文章（A）」と「比較文章（B）」を比較し、厳格にチェックを行ってください。

                【元文章（A）】
                {text_a}

                【比較文章（B）】
                {text_b}

                【NGワード】
                {ng_words_input}

                【チェック項目と出力形式】
                以下の2点について、見出しをつけて分かりやすくレポートしてください。

                1. 転記ミス・違いの指摘
                - AとBを比較し、意味が変わっている部分、抜け漏れ、誤字脱字、数字のズレ（例：金額や日数の間違い）があればすべて指摘してください。
                - 特に問題がない場合は「✅ 転記ミスや違いは見当たりません」と出力してください。

                2. NGワードチェック
                - 【比較文章（B）】の中に、【NGワード】に含まれる言葉が入っていないかチェックしてください。
                - もし含まれていた場合、どの部分で使われているかを指摘し、可能であれば言い換えの提案をしてください。
                - 含まれていない場合は「✅ NGワードは含まれていません」と出力してください。
                """

                # AIにリクエスト送信（ブレを防ぐために temperature=0.0）
                response = model.generate_content(
                    prompt,
                    generation_config=genai.types.GenerationConfig(temperature=0.0)
                )
                
                st.markdown("### 🤖 AI校正レポート")
                st.write(response.text)

            except Exception as e:
                st.error(f"AIチェック中にエラーが発生しました: {e}")



