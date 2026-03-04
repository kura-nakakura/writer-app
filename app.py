import streamlit as st
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import pandas as pd

# --- ページ設定 ---
st.set_page_config(page_title="判定＆添削ツール", layout="wide")

# --- Googleスプシ接続関数（★クラウドのSecrets対応版★） ---
@st.cache_resource
def get_worksheet(sheet_id):
    scope = ['https://spreadsheets.google.com/feeds','https://www.googleapis.com/auth/drive']
    # 変更点：credentials.jsonファイルではなく、StreamlitのSecretsから直接鍵情報を読み込む
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    sh = client.open_by_key(sheet_id)
    return sh.get_worksheet(0)

# --- メイン設定 ---
st.title("🚀 業務効率化アプリ")

# 1. 掲載可能リスト（マスタ1）
LIST_POSSIBLE_ID = '1dGJl6SfeuveynLJ8Q65JDZVymQLMGcyd5ZW5vBD02_8' 
# 2. 過去掲載リスト（マスタ2）
LIST_PAST_ID = '1aftTvSvKS2yWxHNRNW6rDkrXTsXBw-mWqXViEfsLOMw' 

mode = st.sidebar.selectbox("モード選択", ["求人検索&掲載判定", "文章比較FB"])

if mode == "求人検索&掲載判定":
    st.subheader("🔍 求人ID 掲載判定")
    search_id = st.text_input("検索したい「求人ID」を入力", placeholder="例: 4445")
    
    if st.button("判定実行"):
        if search_id:
            try:
                # STEP 1: 掲載可能リストを確認
                ws1 = get_worksheet(LIST_POSSIBLE_ID)
                df1 = pd.DataFrame(ws1.get_all_values()[1:], columns=ws1.get_all_values()[0])
                res1 = df1[df1['求人ID'] == search_id]

                if res1.empty:
                    st.error(f"❌ 判定結果：掲載対象外")
                else:
                    st.info(f"💡 掲載可能リストに存在します（企業名: {res1.iloc[0]['企業名']}）")
                    
                    # STEP 2: 過去掲載リストを確認
                    ws2 = get_worksheet(LIST_PAST_ID)
                    df2 = pd.DataFrame(ws2.get_all_values()[1:], columns=ws2.get_all_values()[0])
                    res2 = df2[df2['求人ID'] == search_id]

                    if not res2.empty:
                        st.error("❌ 判定結果：掲載不可")
                        st.warning("この求人は【過去掲載リスト】に存在するため、重複掲載となります。")
                        st.dataframe(res2)
                    else:
                        st.success("✅ 判定結果：掲載可能！")
                        st.balloons()
                        st.dataframe(res1)
            except Exception as e:
                st.error(f"エラーが発生しました: {e}")
        else:
            st.error("IDを入力してください！")

elif mode == "文章比較FB":
    st.subheader("📝 文章比較・独自ルールチェック")
    st.write("判定機能が完成したら、ここを仕上げましょう。")