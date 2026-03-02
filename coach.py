import os
import json
import garth
import requests
from garminconnect import Garmin
from google import genai 
from datetime import datetime, timezone, timedelta

GARMIN_HASH = os.environ.get("GARMIN_HASH")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")

LAST_ID_FILE = "last_activity_id.txt"
MEMORY_FILE = "coach_memory.txt"  # 🧠 新增：教練的記憶備忘錄

def send_discord_notify(message):
    chunks = [message[i:i+1900] for i in range(0, len(message), 1900)]
    for chunk in chunks:
        response = requests.post(DISCORD_WEBHOOK_URL, json={"content": chunk})
        if response.status_code not in [200, 204]:
            raise Exception(f"Discord 傳送失敗，錯誤碼: {response.status_code}")

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

        # 🧠 讀取昨天的教練記憶
        past_memory = "無過去記憶（這是教練上任的第一天，請根據當前數據建立基礎認知）。"
        if os.path.exists(MEMORY_FILE):
            with open(MEMORY_FILE, "r", encoding="utf-8") as f:
                past_memory = f.read().strip()

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
        
        print(f"🎉 發現 {len(new_records)} 筆新紀錄！正在整理數據...")
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
                "avg_hr": summary.get('averageHR') or act.get('averageHR') or summary.get('averageHeartRateInBeatsPerMinute') or 0,
                "max_hr": summary.get('maxHR') or act.get('maxHR') or summary.get('maxHeartRateInBeatsPerMinute') or 0,
                "avg_cadence": summary.get('averageRunningCadenceInStepsPerMinute') or act.get('averageRunningCadenceInStepsPerMinute') or 0,
                "avg_stride_length": summary.get('averageStrideLength') or act.get('averageStrideLength') or 0,
                "avg_vertical_oscillation": summary.get('averageVerticalOscillation') or act.get('averageVerticalOscillation') or 0,
                "avg_ground_contact_time": summary.get('averageGroundContactTime') or act.get('averageGroundContactTime') or 0,
                "laps": [{"distance_m": lap.get('distance', 0), 
                          "duration_s": lap.get('duration', 0), 
                          "avg_hr": lap.get('averageHR') or lap.get('averageHeartRateInBeatsPerMinute') or 0,
                          "avg_cadence": lap.get('averageRunningCadenceInStepsPerMinute') or lap.get('averageRunCadence') or 0,
                          "avg_vertical_oscillation": lap.get('averageVerticalOscillation') or 0,
                          "avg_ground_contact_time": lap.get('averageGroundContactTime') or 0
                         } for lap in splits.get('lapDTOs', [])] if splits else []
            }
            payloads.append(slim_act)
            
        names_str = "、".join(act_names)
        print(f"🧠 3. 正在喚醒具備記憶的 AI 教練 [{names_str}]...")
        ai_client = genai.Client(api_key=GEMINI_API_KEY)
        
        tw_tz = timezone(timedelta(hours=8))
        today_str = datetime.now(tw_tz).strftime("%Y年%m月%d日")
        
        # 🧠 終極 Prompt：強迫 AI 輸出兩種內容，並用分隔符號切開
        prompt = f"""
        今天是 {today_str}。你是一位專業的越野跑與馬拉松教練。這是我最新累積的 {len(new_records)} 筆 Garmin 運動數據：{names_str}。

        【上次的教練交接日誌（過去記憶）】
        {past_memory}

        任務指示：
        考量我 161 cm 的身高，請綜合評估我的高階跑步動態（步頻、步距、垂直震幅、觸地時間）。
        請結合「上次的教練交接日誌」，判斷我目前的疲勞累積狀態，並推算距離 4 月 12 日的 30km 越野賽（1721m 爬升）及 4 月 26 日的半馬剩餘天數，給予符合當前週期的訓練建議。賽中補給需考量防脹氣好消化，賽後恢復請建議如何搭配鎂、鈣。

        ⚠️ 輸出格式極度重要，請嚴格遵守以下結構（必須包含 ===MEMORY_START=== 分隔線）：

        (這裡寫給跑者的 Discord 報告，多用條列式與 Emoji，總字數 2000 字內)
        ===MEMORY_START===
        (這裡寫給明天你自己的交接備忘錄：簡述目前的累積疲勞度、訓練週期狀態、以及下次需要特別關注的指標。限 300 字以內，不需對跑者說話，這是你的內部筆記)

        數據：{json.dumps(payloads, ensure_ascii=False)}
        """
        
        response = ai_client.models.generate_content(model='gemini-3.1-pro-preview', contents=prompt)
        full_text = response.text

        # 🧠 解析 AI 的回覆，把報告和記憶切開
        if "===MEMORY_START===" in full_text:
            report_part, new_memory = full_text.split("===MEMORY_START===")
            report_part = report_part.strip()
            new_memory = new_memory.strip()
        else:
            report_part = full_text.strip()
            new_memory = "⚠️ 教練太累了忘記寫日誌，請根據最新數據與賽事倒數重新評估。"

        print("📱 4. 正在發送報告並寫入教練記憶...")
        send_discord_notify(f"🏃‍♂️ **AI 教練早安報告 ({today_str})：{names_str}**\n\n{report_part}")
        
        # 更新書籤
        with open(LAST_ID_FILE, "w") as f:
            f.write(str(new_records[0].get('activityId')))
            
        # 🧠 儲存新記憶
        with open(MEMORY_FILE, "w", encoding="utf-8") as f:
            f.write(new_memory)
            
        print("✅ 大功告成！Discord 已送出，教練記憶已存檔。")

    except Exception as e:
        print(f"❌ AI 教練執行失敗：{e}")
        try:
            send_discord_notify(f"❌ AI 教練執行失敗：{e}")
        except:
            pass

if __name__ == "__main__":
    main()
