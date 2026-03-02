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
MEMORY_FILE = "coach_memory.txt" 

# ==========================================
# ❤️ 你的自訂心率區間 (請根據你 Fenix 8 Pro 內的實際設定修改這些數字！)
# ==========================================
CUSTOM_HR_ZONES = {
    "Z1_恢復區 (Recovery)": "135-153 bpm",
    "Z2_有氧耐力區 (Endurance)": "154-166 bpm",
    "Z3_節奏區 (Tempo)": "167-172 bpm",
    "Z4_乳酸閾值區 (Threshold)": "173-183 bpm",
    "Z5_無氧極限區 (Maximum)": "184+ bpm"
}
# ==========================================

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

        past_memory = "無過去記憶（請根據當前數據建立基礎認知）。"
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
                "avg_cadence": summary.get('averageRunningCadenceInStepsPerMinute') or act.get('averageRunningCadenceInStepsPerMinute') or summary.get('avgCadence') or 0,
                "avg_stride_length": summary.get('averageStrideLength') or act.get('averageStrideLength') or summary.get('avgStrideLength') or 0,
                "avg_vertical_oscillation": summary.get('avgVerticalOscillation') or summary.get('averageVerticalOscillation') or act.get('avgVerticalOscillation') or 0,
                "avg_ground_contact_time": summary.get('avgGroundContactTime') or summary.get('averageGroundContactTime') or act.get('avgGroundContactTime') or 0,
                
                # 🏃‍♂️ 嘗試抓取停留在各心率區間的時間 (如果有資料的話)
                "time_in_hr_zones": summary.get('timeInHrZone') or summary.get('zoneDTOs') or "未提供區間停留時間",
                
                "laps": [{"distance_m": lap.get('distance', 0), 
                          "duration_s": lap.get('duration', 0), 
                          "avg_hr": lap.get('averageHR') or lap.get('averageHeartRateInBeatsPerMinute') or 0,
                          "avg_cadence": lap.get('averageRunningCadenceInStepsPerMinute') or lap.get('averageRunCadence') or lap.get('avgCadence') or 0,
                          "avg_vertical_oscillation": lap.get('avgVerticalOscillation') or lap.get('averageVerticalOscillation') or 0,
                          "avg_ground_contact_time": lap.get('avgGroundContactTime') or lap.get('averageGroundContactTime') or 0
                         } for lap in splits.get('lapDTOs', [])] if splits else []
            }
            payloads.append(slim_act)
            
        names_str = "、".join(act_names)
        print(f"🧠 3. 正在喚醒具備記憶的 AI 教練 [{names_str}]...")
        ai_client = genai.Client(api_key=GEMINI_API_KEY)
        
        tw_tz = timezone(timedelta(hours=8))
        today_str = datetime.now(tw_tz).strftime("%Y年%m月%d日")
        
        prompt = f"""
        今天是 {today_str}。你是一位專業的越野跑與馬拉松教練。這是我最新累積的 {len(new_records)} 筆 Garmin Fenix 8 Pro 運動數據：{names_str}。

        【跑者的自訂心率區間】
        {json.dumps(CUSTOM_HR_ZONES, ensure_ascii=False)}

        【上次的教練交接日誌（過去記憶）】
        {past_memory}

        任務指示：
        考量我 161 cm 的身高，請嚴格比對我的「平均心率 (avg_hr)」與「分段心率 (laps avg_hr)」是否符合【跑者的自訂心率區間】的預期訓練效益。
        綜合評估高階跑步動態（步頻、步距、垂直震幅、觸地時間），並結合「上次的教練交接日誌」判斷疲勞累積。
        請推算距離 4 月 12 日的 30km 越野賽（1721m 爬升）及 4 月 26 日的半馬剩餘天數，給予符合當前週期的強度與步態控制建議。
        補給需考量防脹氣好消化，賽後恢復請建議如何搭配鎂、鈣。

        ⚠️ 輸出格式極度重要，請嚴格遵守以下結構（必須包含 ===MEMORY_START=== 分隔線）：

        (這裡寫給跑者的 Discord 報告，多用條列式與 Emoji，總字數 2000 字內)
        ===MEMORY_START===
        (這裡寫給明天你自己的交接備忘錄：簡述目前的累積疲勞度、心率區間表現、以及下次需要特別關注的指標。限 300 字以內，不需對跑者說話，這是你的內部筆記)

        數據：{json.dumps(payloads, ensure_ascii=False)}
        """
        
        response = ai_client.models.generate_content(model='gemini-3.1-pro-preview', contents=prompt)
        full_text = response.text

        if "===MEMORY_START===" in full_text:
            report_part, new_memory = full_text.split("===MEMORY_START===")
            report_part = report_part.strip()
            new_memory = new_memory.strip()
        else:
            report_part = full_text.strip()
            new_memory = "⚠️ 教練太累了忘記寫日誌，請根據最新數據與賽事倒數重新評估。"

        print("📱 4. 正在發送報告並寫入教練記憶...")
        send_discord_notify(f"🏃‍♂️ **AI 教練早安報告 ({today_str})：{names_str}**\n\n{report_part}")
        
        with open(LAST_ID_FILE, "w") as f:
            f.write(str(new_records[0].get('activityId')))
            
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
