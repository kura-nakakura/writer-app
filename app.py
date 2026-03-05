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
    
    # 高速で賢い「Gemini 1.5 Flash」モデルを使用
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
st.title("🚀 業務効率化アプリ")

LIST_POSSIBLE_ID = '1dGJl6SfeuveynLJ8Q65JDZVymQLMGcyd5ZW5vBD02_8' 
LIST_PAST_ID = '1aftTvSvKS2yWxHNRNW6rDkrXTsXBw-mWqXViEfsLOMw' 

mode = st.sidebar.selectbox("モード選択", ["求人検索&AI判定", "文章比較FB"])

if mode == "求人検索&AI判定":
    st.subheader("🔍 求人ID 掲載判定 ＆ AI自動審査")
    search_id = st.text_input("検索したい「求人ID」を入力", placeholder="例: 4445")
    
    if st.button("判定実行"):
        if search_id:
            try:
                # STEP 1: 掲載可能リスト
                with st.spinner('掲載可能リストを確認中...'):
                    ws1 = get_worksheet(LIST_POSSIBLE_ID)
                    df1 = pd.DataFrame(ws1.get_all_values()[1:], columns=ws1.get_all_values()[0])
                    df1.columns = [str(col).strip() for col in df1.columns]
                    res1 = df1[df1['求人ID'] == search_id]

                if res1.empty:
                    st.error(f"❌ 判定結果：掲載対象外（リストに存在しません）")
                else:
                    st.info(f"💡 掲載可能リストに存在します（企業名: {res1.iloc[0]['企業名']}）")
                    
                    # STEP 2: 過去掲載リスト（転載確認シート）
                    with st.spinner('過去掲載リストと照合中...'):
                        ws2 = get_worksheet(LIST_PAST_ID, "転載確認シート")
                        all_data2 = ws2.get_all_values()
                        
                        if len(all_data2) < 2:
                            res2 = pd.DataFrame()
                        else:
                            df2 = pd.DataFrame(all_data2[1:], columns=all_data2[0])
                            df2.columns = [str(col).strip() for col in df2.columns]
                            
                            if '求人ID' not in df2.columns:
                                st.error("❌ マスタ2（転載確認シート）の1行目に「求人ID」という項目が見つかりません。")
                                st.stop()
                                
                            res2 = df2[df2['求人ID'] == search_id]

                    if not res2.empty:
                        st.error("❌ 判定結果：掲載不可（過去掲載リストと重複しています）")
                        st.dataframe(res2)
                    else:
                        st.success("✅ スプシ判定クリア！続けてAI審査を行います...")
                        
                        # STEP 3: AI審査
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

