# 一人份的婚禮 — TouchDesigner 視覺端

三幕式互動裝置的 TouchDesigner 專案。體驗者的動作由 Unity 端以攝影機追蹤並判定，
透過 OSC 告訴 TD 現在走到哪一幕哪一句，TD 負責所有投影畫面與背景音樂。

- 第一幕：誓詞 — 教堂十字光、燭火、心電圖
- 第二幕：照顧 — 餵食累積暖度，「我真的受不了了！」整片轉紅並爬滿裂痕，最後一句化開
- 第三幕：和解 — 體驗者抽牌決定燭火顏色，自我擁抱觸發金繕

## 環境

- **TouchDesigner 2025.32460**（非商業版）
- MediaPipe 模型已包含在 `models/`（手部、姿勢、人像分割）
- 字型 `fonts/NotoSerifTC-VF.ttf` 已包含
- 路徑全部是相對路徑，clone 下來直接開 `Effect.toe` 即可

> **非商業版不能輸出 H.264。** 錄影請錄 MJPEG `.mov`，再用 TD 內建的 ffmpeg
> （`C:\Program Files\Derivative\TouchDesigner\bin\ffmpeg.exe`，用 `h264_qsv`，
> 沒有 libx264）轉成 MP4。

## 與 Unity 端的 OSC 介面

Unity 專案：<https://github.com/ciel0412/OneManShow_Project>

TD 在 **port 7000** 接收（`scene_director/oscInFromUnity1`）。Unity 送到 `outIP:7000`。

| 位址 | 內容 |
|---|---|
| `/SceneID` | **實際送的是「第幾句」** |
| `/ScriptLine` | **實際送的是「第幾幕」** |
| `/SceneBK` | 背景代碼，目前固定 1 |
| `/FeedCount` | 第二幕餵食的累積次數 |
| `/CardID` | 抽到的卡，0=還沒抽、1=A 缺角的圓、2=B 海邊的夕陽、3=C 暗處的一束光、4=D 夜空 |
| `/Alive` | 每幀 +1 的心跳，用來分辨「Unity 當掉」與「值沒變」 |

> **前兩個位址是對調的。** 這是 Unity 端既有的行為，雙方講好**由 TD 配合**，
> 所以 `oscSync1` 的 `Actchannel` 設成 `ScriptLine`、`Linechannel` 設成 `SceneID`。
> 看起來很怪，但是刻意的 —— 不要「修正」它，除非 Unity 端也同步改。

幕/句都是 1 起算。**Unity 不在劇目中時兩個都送 0**，TD 收到 act 0 就進待機畫面；
`000 → 111` 這個邊緣會讓 TD 的時間軸重頭開始，也就是「下一位體驗者」的循環。

`unity_live` 單獨使用並不可靠（沒收到 `/Alive` 時它會退化成「有沒有 cook」的猜測，
任何 cook 都會讓它變真）。判斷連線請一律同時看 `unity_connected`。

## 目錄

| | |
|---|---|
| `Effect.toe` | **本體，唯一的真實來源**，用 TouchDesigner 開這個 |
| `scripts/` | 由 `Effect.toe` 自動產生的可讀原始碼（46 個 Python、26 個 GLSL、5 個表格） |
| `Effect.toe.dir/` | `toeexpand` 的完整展開，含每一個參數值 |
| `tools/export_scripts.py` | 產生 `scripts/` 的工具 |
| `audio/` | 三幕的 BGM（MP3 原檔 + 無縫循環 WAV） |
| `fonts/` `models/` | 字型與 MediaPipe 模型 |
| `export/` | 專案摘要與簡報用文件 |
| `effect_shots/` | 過程截圖 |

`scripts/` 和 `Effect.toe.dir/` 都是**產生出來的**，改它們 TouchDesigner 不會知道。
改完 `.toe` 之後重新產生（TouchDesigner 要先關閉）：

```bash
rm -rf Effect.toe.dir scripts
"C:/Program Files/Derivative/TouchDesigner/bin/toeexpand.exe" Effect.toe
"C:/Program Files/Derivative/TouchDesigner/bin/python.exe" -I tools/export_scripts.py
```

## 不在這個 repo 裡的東西

- **`render/`（約 2 GB）** — 完整走一遍的錄影。備案影片是
  `full_run_master.mp4`（65 MB，含 BGM）。另外兩個 `.mov` 是中間產物，
  其中 `full_run_take1_oldburst.mov` 的第二幕是修正前的錯誤行為。**存在雲端。**
- **`package/`** — `audio/` 的重複複本加一個測試用 zip。
- **Unity 端的中文字型（262 MB）** — `Assets/Art Asset/fonts/NatoSansTC/`。
  她的場景有引用這些 GUID，但檔案**從來沒有被 commit 過**（單檔 136 MB，
  超過 GitHub 的 100 MB 上限）。**換機器時必須用隨身碟手動複製**，
  否則中文字幕會是空的。

## 已知問題

1. **第三幕的句長太短（`lineTrack1`）。** `Act3line2start` 10 秒、`Act3line3start` 20 秒，
   是沒調過的預設值；第一幕是 50/100、第二幕是 37.5/75/112.5。實測 Unity 的第三幕
   兩句各約 18 秒和 23 秒，所以 TD 會跑到 Unity 前面，接著被 follow-unity 往回 seek，
   **畫面上看得到字幕倒退再前進**（2026-10-15 實跑中發生兩次）。
   建議改成 **50 / 100** 與第一幕一致，讓 TD 穩定慢於任何體驗者、永遠只被往前拉。
2. **`Bgmmaster` 目前是 0.097。** 這是桌上工作時調小的，**進場館前必須調回去**。
3. 待機時除錯面板顯示 MISMATCH。因為 `/SceneBK` 在 Unity 端寫死 1 且沒有被
   `StartGamePlay` 擋掉，待機時 TD 收到的是 0/0/1。**純顯示問題**，
   待機判斷只看 act 是不是 0。
4. 五個節點（`pulseValue1`、`chestAlign1`、`kintsugiDraw1`、`pressState1`、
   `carryFlicker1`）帶著過期的 `last_error` 字串，而 `errors()` 全專案是乾淨的。
   `last_error` 是各節點 except 寫進去、**從來不會被清除**的，所以那些值可能來自
   任何一個過去的時刻 —— 當成證據之前一定要先清掉重測。

## 操作面板

`scene_director` 的 **ManualControl** 分頁可以不接 Unity 單獨排練：
手動選幕/選句、加餵食、強制裂開與釋放、鎖卡與選卡、觸發擁抱、BGM 靜音與總音量，
以及 `Resetall`。手動選幕和 `Resetall` 都會把該幕的時間規歸零。
