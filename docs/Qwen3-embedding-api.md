# 嵌入 — Qwen3-Embedding-0.6B

> 向量化嵌入模型 (SGLang, GPU 2)

| 状态 | 类型 | 模型名称 |
|------|------|----------|
| 运行中 | 嵌入 | `Qwen3-Embedding-0.6B` |

## 基本信息

- **调用地址**: `http://10.200.37.71:8801/v1/embeddings`
- **模型名称**: `Qwen3-Embedding-0.6B`
- **请求方式**: POST (Content-Type: application/json)

## cURL 快速测试

```bash
curl -X POST http://10.200.37.71:8801/v1/embeddings \
  -H "Authorization: Bearer lgw-你的API密钥" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "Qwen3-Embedding-0.6B",
    "input": "你好，世界",
    "encoding_format": "float"
  }'
```

## Python 示例

```python
import requests

resp = requests.post(
    "http://10.200.37.71:8801/v1/embeddings",
    headers={"Authorization": "Bearer lgw-你的API密钥"},
    json={
        "model": "Qwen3-Embedding-0.6B",
        "input": "你好，世界",
    }
)
data = resp.json()
print(f"维度: {len(data['data'][0]['embedding'])}")  # 1024
print(f"Tokens: {data['usage']['total_tokens']}")
```

## 请求参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| model | string | 是 | 模型名称，如 Qwen3-Embedding-0.6B |
| input | string | string[] | 是 | 输入文本，支持单字符串或字符串数组批量处理 |
| encoding_format | string | 否 | 返回格式: float (默认) 或 base64 |

## 响应参数

| 字段 | 类型 | 说明 |
|------|------|------|
| object | string | 固定为 "list" |
| data[] | array | 向量列表，按 input 顺序排列 |
| data[].object | string | 固定为 "embedding" |
| data[].embedding | number[] | 向量值数组，1024 维浮点数 |
| data[].index | integer | 序号，对应 input 数组索引 |
| model | string | 实际使用的模型名称 |
| usage.prompt_tokens | integer | 输入 token 数 |
| usage.total_tokens | integer | 总 token 数 |

## 响应示例

```json
{
  "object": "list",
  "data": [
    {
      "object": "embedding",
      "embedding": [
        -0.0147,
        0.0175,
        -0.0119,
        -0.0708,
        0.0027,
        "... (1024 values total)"
      ],
      "index": 0
    }
  ],
  "model": "Qwen3-Embedding-0.6B",
  "usage": {
    "prompt_tokens": 3,
    "total_tokens": 3,
    "completion_tokens": 0,
    "reasoning_tokens": 0
  }
}
```

## 批量文本向量化

```bash
# 批量文本向量化：input 传数组
curl -X POST http://10.200.37.71:8801/v1/embeddings \
  -H "Authorization: Bearer lgw-你的API密钥" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "Qwen3-Embedding-0.6B",
    "input": ["文本1", "文本2", "文本3"]
  }'

# 响应 data 数组按输入顺序包含 3 个向量
# data[0].embedding ← "文本1" 的向量
# data[1].embedding ← "文本2" 的向量
# data[2].embedding ← "文本3" 的向量
```

