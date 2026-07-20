# 重排 — BGE-Reranker-v2-M3

> BGE交叉编码器重排模型 (FastAPI, GPU 2, 8019)

| 状态 | 类型 | 模型名称 |
|------|------|----------|
| 运行中 | 重排 | `bge-reranker-v2-m3` |

## 基本信息

- **调用地址**: `http://10.200.37.71:8801/v1/rerank`
- **模型名称**: `bge-reranker-v2-m3`
- **请求方式**: POST (Content-Type: application/json)

## cURL 快速测试

```bash
curl -X POST http://10.200.37.71:8801/v1/rerank \
  -H "Authorization: Bearer lgw-你的API密钥" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "bge-reranker-v2-m3",
    "query": "今天天气怎么样？",
    "documents": [
      "今天气温25度，晴转多云",
      "篮球比赛规则简介",
      "天气预报说今天会下雨"
    ]
  }'
```

## Python 示例

```python
import requests

resp = requests.post(
    "http://10.200.37.71:8801/v1/rerank",
    headers={"Authorization": "Bearer lgw-你的API密钥"},
    json={
        "model": "Qwen3-Embedding-0.6B",
        "query": "今天天气怎么样？",
        "documents": [
            "今天气温25度，晴转多云",
            "篮球比赛规则简介",
            "天气预报说今天会下雨"
        ]
    }
)
for item in resp.json():
    print(f"[{item['index']}] score={item['score']:.4f} doc={item['document']}")
```

## 请求参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| model | string | 是 | 模型名称，如 Qwen3-Embedding-0.6B |
| query | string | 是 | 查询文本，计算与各文档的相关性分数 |
| documents | string[] | 是 | 待排序的文档列表 |
| top_n | integer | 否 | 返回前 N 个最相关文档 (可选) |

## 响应参数

| 字段 | 类型 | 说明 |
|------|------|------|
| [].score | number | 相关性分数 (余弦相似度)，越高越相关 |
| [].document | string | 文档文本 (索引对应的原始文档) |
| [].index | integer | 原始 documents 数组中的索引位置 |
| [].meta_info | object | 元信息 (id, prompt_tokens, e2e_latency 等) |

## 响应示例

```json
[
  {
    "score": 0.856,
    "document": "天气预报说今天会下雨",
    "index": 2,
    "meta_info": {
      "prompt_tokens": 10,
      "e2e_latency": 0.05
    }
  },
  {
    "score": 0.634,
    "document": "今天气温25度，晴转多云",
    "index": 0,
    "meta_info": {
      "prompt_tokens": 10,
      "e2e_latency": 0.04
    }
  },
  {
    "score": -0.12,
    "document": "篮球比赛规则简介",
    "index": 1,
    "meta_info": {
      "prompt_tokens": 10,
      "e2e_latency": 0.04
    }
  }
]
```

