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

def send_discord_notify(message):
    chunks = [message[i:i+1900] for i in range(0, len(message), 1900)]
    for chunk in chunks:
        response = requests.post(DISCORD_WEBHOOK_URL, json={"content": chunk})
        if response.status_code not in [200, 204]:
            raise Exception(f"Discord 傳送失敗，錯誤碼: {response.status_code}")

def main():
    try:
        print("🔄 1. 連線至 Garmin 並讀取資料...")
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

        # 🌟 新增：抓取「今天早上的睡眠與 HRV 恢復數據」
        tw_tz = timezone(timedelta(hours=8))
        today_date = datetime.now(tw_tz)
        today_str = today_date.strftime("%Y年%m月%d日")
        today_iso = today_date.strftime("%Y-%m-%d")

        print("🛏️ 2. 正在抓取昨晚的睡眠與 HRV 數據...")
        daily_health = {
            "sleep_score": "無資料",
            "sleep_hours": "無資料",
            "hrv_status": "無資料",
            "hrv_last_night_avg": "無資料",
            "hrv_7d_avg": "無資料"
        }
        
        try:
            sleep_info = garmin_client.get_sleep_data(today_iso)
            if sleep_info and 'dailySleepDTO' in sleep_info:
                score = sleep_info['dailySleepDTO'].get('sleepScores', {}).get('overall', {}).get('value')
                seconds = sleep_info['dailySleepDTO'].get('sleepTimeSeconds', 0)
                daily_health["sleep_score"] = score if score else "無資料"
                daily_health["sleep_hours"] = round(seconds / 3600, 1) if seconds else "無資料"
                
            hrv_info = garmin_client.get_hrv_data(today_iso)
            if hrv_info:
                # 攔截 Garmin 常見的 HRV 欄位結構
                daily_health["hrv_status"] = hrv_info.get("status") or hrv_info.get("hrvSummary", {}).get("status", "無資料")
                daily_health["hrv_last_night_avg"] = hrv_info.get("lastNightAvg") or hrv_info.get("hrvSummary", {}).get("lastNightAvg", "無資料")
                daily_health["hrv_7d_avg"] = hrv_info.get("weeklyAvg") or hrv_info.get("hrvSummary", {}).get("weeklyAvg", "無資料")
        except Exception as e:
            print(f"⚠️ 無法抓取睡眠/HRV資料 (可能手錶未同步): {e}")

        print("🔍 3. 檢查新運動紀錄...")
        activities = garmin_client.get_activities(0, 200)
        new_records = []
        for act in activities:
            if str(act.get('activityId')) == last_id:
                break 
            new_records.append(act)

        if not new_records:
            print("✅ 目前沒有新紀錄。")
            return
        
        payloads = []
        act_names = []
        for act in new_records:
            act_id = act.get('activityId')
            act_names.append(act.get('activityName'))
            
            slim_act = {
                "name": act.get('activityName'),
                "type": act.get('activityType', {}).get('typeKey', ''),
                "distance_m": round(act.get('distance', 0), 2),
                "duration_s": round(act.get('duration', 0), 2),
                "elevation_gain_m": round(act.get('elevationGain', 0), 2),
                "elevation_loss_m": round(act.get('elevationLoss', 0), 2),
                "avg_speed_m_s": round(act.get('averageSpeed', 0), 3),
                "avg_gap_m_s": round(act.get('avgGradeAdjustedSpeed', 0), 3), 
                "avg_hr": act.get('averageHR', 0),
                "max_hr": act.get('maxHR', 0),
                "hr_zones_s": {
                    "Z1": round(act.get('hrTimeInZone_1', 0), 1),
                    "Z2": round(act.get('hrTimeInZone_2', 0), 1),
                    "Z3": round(act.get('hrTimeInZone_3', 0), 1),
                    "Z4": round(act.get('hrTimeInZone_4', 0), 1),
                    "Z5": round(act.get('hrTimeInZone_5', 0), 1),
                },
                "avg_cadence": act.get('averageRunningCadenceInStepsPerMinute', 0),
                "avg_stride_length_cm": round(act.get('avgStrideLength', 0), 2),
                "avg_vertical_oscillation_cm": round(act.get('avgVerticalOscillation', 0), 2),
                "avg_ground_contact_time_ms": round(act.get('avgGroundContactTime', 0), 2),
                "avg_power_w": act.get('avgPower', 0),
                "training_load": round(act.get('activityTrainingLoad', 0), 2),
                "aerobic_TE": act.get('aerobicTrainingEffect', 0),
                "training_effect_label": act.get('trainingEffectLabel', "")
            }
            payloads.append(slim_act)
            
        names_str = "、".join(act_names)
        print("🧠 4. 呼叫具備記憶的 Gemini API...")
        ai_client = genai.Client(api_key=GEMINI_API_KEY)
        
        prompt = f"""
        今天是 {today_str}。你是一位專業的越野跑與馬拉松教練。
        跑者資料：身高 161cm, 體重 63kg。
        目標賽事：4/12 30km 越野賽(1721m 爬升)、4/26 半馬。

        【昨晚的恢復數據 (極度重要)】
        - 睡眠分數：{daily_health['sleep_score']} / 睡眠時間：{daily_health['sleep_hours']} 小時
        - HRV 狀態：{daily_health['hrv_status']} (昨晚平均: {daily_health['hrv_last_night_avg']} / 7天平均: {daily_health['hrv_7d_avg']})

        【上次的教練交接日誌（過去記憶）】
        {past_memory}

        任務：
        這是最新 Garmin 訓練數據：{names_str}。
        1. 恢復評估：首要根據「昨晚的恢復數據 (睡眠與HRV)」與「交接日誌」，判斷跑者的神經與肌肉是否恢復。如果 HRV 狀態不佳或睡眠不足，必須強烈建議調整今日訓練強度。
        2. 訓練成效：分析 GAP (等價平地配速)、心率區間 (hr_zones_s) 與 功率 (avg_power_w)，評估本次訓練是否達標。
        3. 跑步經濟性：綜合評估步頻、步距、垂直震幅與觸地時間。
        4. 給予賽前倒數的課表微調，並針對易脹氣體質提供好消化的賽中補給，以及賽後鈣/鎂的恢復策略。

        ⚠️ 輸出格式：
        (給跑者的 Discord 報告，2000字內，多用 Emoji，排版清晰易讀)
        ===MEMORY_START===
        (給明天你的內部筆記：簡述目前 HRV 趨勢、累積疲勞度與下次觀測重點，300字內)

        運動數據：{json.dumps(payloads, ensure_ascii=False)}
        """
        
        response = ai_client.models.generate_content(model='gemini-3-flash-preview', contents=prompt)
        full_text = response.text

        if "===MEMORY_START===" in full_text:
            report_part, new_memory = full_text.split("===MEMORY_START===")
            report_part, new_memory = report_part.strip(), new_memory.strip()
        else:
            report_part, new_memory = full_text.strip(), "無新紀錄，維持原訓練計畫。"

        print("📱 5. 發送 Discord 報告...")
        send_discord_notify(f"🏃‍♂️ **AI 教練專屬報告 ({today_str})**\n\n{report_part}")
        
        with open(LAST_ID_FILE, "w") as f:
            f.write(str(new_records[0].get('activityId')))
        with open(MEMORY_FILE, "w", encoding="utf-8") as f:
            f.write(new_memory)
            
        print("✅ 大功告成！")

    except Exception as e:
        print(f"❌ 執行失敗：{e}")
        send_discord_notify(f"❌ AI 教練執行錯誤：{e}")
        exit(1)

if __name__ == "__main__":
    main()
