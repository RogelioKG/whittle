# PROMPT

幫我把一個 3D 遊戲場景拆成可個別生成的道具 (部件)，輸出 manifest JSON。

## 限制

每個部件各自經過：`subject` 填入固定模板生圖 (FLUX.2) → Hunyuan 3D 生模型 → Blender 依 `ref_axis`、`ref_size_m` 縮放，Remesh + Decimate 減面。所以：

- 一個部件是單一物件，不是場景、地形、水面或一組東西。
- 比 2 倍 `voxel_size` 細的結構 (細繩、漁網、旗面) 會消失，要嘛加粗成造型一部分，要嘛不拆。
- 重複的東西只拆一件，擺放交給引擎；外型不同才拆成不同部件。
- 大型結構拆成模組 (碼頭 → 一段棧板、一根支柱)。

## 欄位

最外層 `project` 必填，是專案名稱也是資料夾名稱，格式同 `id` (例如 `fishing_village`)，同一場景沿用同一個名稱。每個部件只能有這 5 個欄位：

| 欄位 | 規則 |
|---|---|
| `id` | 英數、`_`、`-`，建議小寫 snake_case，專案內不可重複 |
| `subject` | 英文名詞片語，以 `a`/`an` 開頭，只寫物件、材質、組成，用形狀詞描述比例。不寫數字尺寸、風格詞 (模板已含)、背景、視角 |
| `ref_axis` | `height` (直立物：桶、柱) 或 `longest` (扁長物：槳、木板) |
| `ref_size_m` | 該軸真實尺寸 (公尺) |
| `decimate.voxel_size` | 公尺，約 `ref_size_m` 的 1/80～1/100，且小於最細結構的一半 |
| `decimate.target_faces` | 小道具 300～800、中型 800～1500、大型 1500～3000 |

參考：0.9 m 木桶用 0.01 / 800 效果良好。

## 進行方式

1. 先用表格列出拆件草案 (6 個欄位值 + 一句拆法說明)，另列不拆的東西與原因。先不要輸出 JSON。
2. 我確認後，只輸出一個 `json` 程式碼區塊，不加註解：

```json
{
  "project": "dock",
  "parts": [
    {
      "id": "barrel",
      "subject": "a wooden barrel with iron bands",
      "ref_axis": "height",
      "ref_size_m": 0.9,
      "decimate": { "voxel_size": 0.01, "target_faces": 800 }
    }
  ]
}
```

追加部件時沿用同一個 `project`、用新的 `id`，重複的會被跳過。

## 場景

{場景描述}
