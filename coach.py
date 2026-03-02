import os
import json
import garth
import requests
from garminconnect import Garmin
from google import genai 

GARMIN_HASH = os.environ.get("GARMIN_HASH")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")

LAST_ID_FILE = "last_activity_id.txt"

def send_discord_notify(message):
    # Discord 單則訊息上限為 2000 字元，我們切成 1900 字元的區塊分批發送
    chunks = [message[i:i+1900] for i in range(0, len(message), 1900)]
    for chunk in chunks:
        response = requests.post(DISCORD_WEBHOOK_URL, json={"content": chunk})
        if response.status_code not in [200, 204]:
            raise Exception(f"Discord 傳送失敗，錯誤碼: {response.status_code}, 內容: {response.text}")

def main():
    try:
        print("🔄 1. 正在連線至 Garmin...")
        garth.client.loads(GARMIN_HASH)
        garmin_client = Garmin()
        garmin_client.garth = garth.client
        
        last_id = None
        if os.path.exists(LAST_ID_FILE):
            with open(LAST_ID_FILE, "r") as f:
                last_id = f.read().strip()

        print("🔍 2. 正在比對新紀錄...")
        activities = garmin_client.get_activities(0, 200)
        new_records = []
        
        for act in activities:
            if str(act.get('activityId')) == last_id:
                break 
            new_records.append(act)

        if not new_records:
            print("✅ 目前沒有新的運動紀錄。")
            return
        
        print(f"🎉 發現 {len(new_records)} 筆新紀錄！正在執行資料瘦身...")
        payloads = []
        act_names = []
        for act in new_records:
            act_id = act.get('activityId')
            act_names.append(act.get('activityName'))
            summary = garmin_client.get_activity(act_id)
            splits = garmin_client.get_activity_splits(act_id)
            
            slim_act = {
                "name": act.get('activityName'),
                "distance_m": act.get('distance', 0),
                "duration_s": act.get('duration', 0),
                "elevation_gain_m": act.get('elevationGain', 0),
                "avg_hr": act.get('averageHeartRateInBeatsPerMinute', 0),
                "laps": [{"distance_m": lap.get('distance', 0), "duration_s": lap.get('duration', 0), "avg_hr": lap.get('averageHeartRate', 0)} for lap in splits.get('lapDTOs', [])] if splits else []
            }
            payloads.append(slim_act)
            
        names_str = "、".join(act_names)
        print(f"🧠 3. 正在呼叫 Gemini API 綜合分析 [{names_str}]...")
        ai_client = genai.Client(api_key=GEMINI_API_KEY)
        
        prompt = f"""
        你是一位專業的越野跑與馬拉松教練。這是我最新累積的 {len(new_records)} 筆 Garmin 運動數據：{names_str}。
        請簡短分析心率與配速穩定度。針對 4 月 12 日 30km 越野賽（1721m 爬升）及 4 月 26 日半馬給予訓練調整建議。
        請建議好消化、不增加腸胃負擔的賽中補給，以及如何搭配鎂、鈣幫助賽後恢復。
        ⚠️ 限制：排版適合 Discord 閱讀（多用條列式與 Emoji），總字數盡量控制在 2000 字內。
        數據：{json.dumps(payloads, ensure_ascii=False)}
        """
        
        response = ai_client.models.generate_content(model='gemini-2.5-pro', contents=prompt)
        
        print("📱 4. 正在將報告發送至 Discord...")
        send_discord_notify(f"🏃‍♂️ **AI 教練綜合分析報告：{names_str}**\n\n{response.text}")
        
        with open(LAST_ID_FILE, "w") as f:
            f.write(str(new_records[0].get('activityId')))
        print("✅ 大功告成！書籤已更新。")

    except Exception as e:
        print(f"❌ AI 教練執行失敗：{e}")
        if "Discord 傳送失敗" not in str(e):
            try:
                send_discord_notify(f"❌ AI 教練執行失敗：{e}")
            except:
                pass

if __name__ == "__main__":
    main()
