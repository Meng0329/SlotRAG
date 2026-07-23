# LLM — Qwen3.6-27B

> Qwen3.6 通义千问系列小参数模型

| 状态 | 类型 | 模型名称 |
|------|------|----------|
| 运行中 | LLM | `qwen3.6-27b` |

## 基本信息

- **调用地址**: `http://10.200.37.71:8801/v1/chat/completions`
- **模型名称**: `qwen3.6-27b`
- **请求方式**: POST (Content-Type: application/json)

## cURL 快速测试

```bash
curl -X POST http://10.200.37.71:8801/v1/chat/completions \
  -H "Authorization: Bearer lgw-你的API密钥" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3.6-27b",
    "messages": [
      {"role": "system", "content": "You are a helpful assistant."},
      {"role": "user", "content": "你好"}
    ],
    "temperature": 0.7,
    "max_tokens": 2048,
    "stream": false
  }'
```

## Python 示例

```python
import openai

# 配置网关地址和密钥
client = openai.OpenAI(
    base_url="http://10.200.37.71:8801/v1/chat/completions",  # 网关地址
    api_key="lgw-你的API密钥",      # 网关平台分配的密钥
)

# 基础对话
response = client.chat.completions.create(
    model="qwen3.6-27b",
    messages=[
        {"role": "user", "content": "你好"}
    ],
    temperature=0.7,
)
print(response.choices[0].message.content)

# 流式输出
stream = client.chat.completions.create(
    model="qwen3.6-27b",
    messages=[{"role": "user", "content": "写一首诗"}],
    stream=True,
)
for chunk in stream:
    if chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="", flush=True)
print()

# JSON 模式
response = client.chat.completions.create(
    model="qwen3.6-27b",
    messages=[{"role": "user", "content": "列出3种水果，用JSON格式"}],
    response_format={"type": "json_object"},
)
print(response.choices[0].message.content)
```

## 请求参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| model | string | 是 | 模型名称，如文档中显示的模型ID |
| messages | array | 是 | 消息列表，每项含 role (system/user/assistant/tool) 和 content |
| temperature | number | 否 | 生成温度 0~2，越高越随机，默认 1.0 |
| top_p | number | 否 | 核采样概率 0~1，默认 1.0 |
| top_k | integer | 否 | Top-K 采样，限制候选 token 数量 |
| min_p | number | 否 | Min-P 采样，最小概率阈值 |
| max_tokens | integer | 否 | 最大生成 token 数 |
| stream | boolean | 否 | 是否流式输出 (SSE)，默认 false |
| stop | string/array | 否 | 停止生成的标记序列 |
| presence_penalty | number | 否 | 存在惩罚 -2~2，默认 0 |
| frequency_penalty | number | 否 | 频率惩罚 -2~2，默认 0 |
| repetition_penalty | number | 否 | 重复惩罚，默认 1.0，>1 惩罚重复 |
| n | integer | 否 | 生成候选数量，默认 1 |
| seed | integer | 否 | 随机种子，可复现输出 |
| response_format | object | 否 | 输出格式，如 {"type":"json_object"} 强制JSON |
| tools | array | 否 | 工具定义列表，用于 Function Calling |
| tool_choice | string/object | 否 | 工具选择策略: "auto" / "none" / 指定工具 |
| logprobs | boolean | 否 | 是否返回 token 的 log 概率 |
| top_logprobs | integer | 否 | 返回 top N 个 log 概率，0~5 |

## 响应参数

| 字段 | 类型 | 说明 |
|------|------|------|
| id | string | 请求唯一标识 |
| object | string | 固定为 "chat.completion" |
| created | integer | 创建时间戳 (Unix) |
| model | string | 实际使用的模型名称 |
| choices[].index | integer | 候选序号 |
| choices[].message.role | string | "assistant" |
| choices[].message.content | string | 模型回复内容 |
| choices[].message.reasoning_content | string/null | 思维链推理内容 (思考模型) |
| choices[].message.tool_calls | array/null | 工具调用列表 (Function Calling 时) |
| choices[].message.tool_calls[].id | string | 工具调用 ID |
| choices[].message.tool_calls[].function.name | string | 调用的函数名 |
| choices[].message.tool_calls[].function.arguments | string | 函数参数 (JSON字符串) |
| choices[].logprobs | object/null | Token log 概率 (请求时开启) |
| choices[].finish_reason | string | 结束原因: stop / length / tool_calls |
| usage.prompt_tokens | integer | 输入 token 数 |
| usage.completion_tokens | integer | 输出 token 数 |
| usage.total_tokens | integer | 总 token 数 |
| usage.reasoning_tokens | integer | 推理 token 数 (思考模型) |
| metadata.weight_version | string | 权重版本标识 |

## 非流式响应示例

```json
{
  "id": "fc29ae3651154edd869e7ab02303eadb",
  "object": "chat.completion",
  "created": 1775093268,
  "model": "/data/mzb/models/Qwen3.5-27B",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "你好！有什么可以帮你的吗？",
        "reasoning_content": null,
        "tool_calls": null
      },
      "logprobs": null,
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 15,
    "completion_tokens": 8,
    "total_tokens": 23,
    "prompt_tokens_details": null,
    "reasoning_tokens": 0
  },
  "metadata": {
    "weight_version": "default"
  }
}
```

## 流式 (SSE) 响应示例

```
# 设置 "stream": true 后，响应以 SSE 格式逐块返回：

data: {"id":"e976ed47e8594ef59b7c5534ec9b7505","object":"chat.completion.chunk","created":1775093246,"model":"Qwen3.5-27B","choices":[{"index":0,"delta":{"role":"assistant","content":""},"logprobs":null,"finish_reason":null}],"usage":null}

data: {"id":"e976ed47e8594ef59b7c5534ec9b7505","object":"chat.completion.chunk","created":1775093246,"model":"Qwen3.5-27B","choices":[{"index":0,"delta":{"content":"你"},"logprobs":null,"finish_reason":null}],"usage":null}

data: {"id":"e976ed47e8594ef59b7c5534ec9b7505","object":"chat.completion.chunk","created":1775093246,"model":"Qwen3.5-27B","choices":[{"index":0,"delta":{"content":"好"},"logprobs":null,"finish_reason":null}],"usage":null}

data: {"id":"e976ed47e8594ef59b7c5534ec9b7505","object":"chat.completion.chunk","created":1775093246,"model":"Qwen3.5-27B","choices":[{"index":0,"delta":{"content":"！"},"logprobs":null,"finish_reason":null}],"usage":null}

data: {"id":"e976ed47e8594ef59b7c5534ec9b7505","object":"chat.completion.chunk","choices":[{"delta":{"content":null},"finish_reason":"stop"}],"usage":null}

data: [DONE]
```

## 工具调用 (Function Calling)

| 参数 | 类型 | 说明 |
|------|------|------|
| tools | array | 工具定义列表，每项含 type 和 function |
| tools[].type | string | 固定为 "function" |
| tools[].function.name | string | 函数名称 |
| tools[].function.description | string | 函数功能描述 (帮助模型决策) |
| tools[].function.parameters | object | JSON Schema 格式的参数定义 |
| tool_choice | string/object | "auto" 自动决定 | "none" 不调用 | {"type":"function","function":{"name":"xxx"}} 指定调用 |

**请求示例**

```bash
curl -X POST http://10.200.37.71:8801/v1/chat/completions \
  -H "Authorization: Bearer lgw-你的API密钥" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "模型名称",
    "messages": [{"role": "user", "content": "北京天气怎么样？"}],
    "tools": [{
      "type": "function",
      "function": {
        "name": "get_weather",
        "description": "获取指定城市的天气信息",
        "parameters": {
          "type": "object",
          "properties": {
            "city": {"type": "string", "description": "城市名称"}
          },
          "required": ["city"]
        }
      }
    }],
    "tool_choice": "auto"
  }'
```

**响应示例**

```json
{
  "id": "b7ffb84df533487e83540bffdc5426fc",
  "object": "chat.completion",
  "created": 1775093271,
  "model": "/data/mzb/models/Qwen3.5-27B",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": null,
        "tool_calls": [
          {
            "id": "call_f61f70daef4c4c5193d5cc82",
            "index": 0,
            "type": "function",
            "function": {
              "name": "get_weather",
              "arguments": "{\"city\": \"Beijing\"}"
            }
          }
        ]
      },
      "finish_reason": "tool_calls"
    }
  ],
  "usage": {
    "prompt_tokens": 279,
    "completion_tokens": 73,
    "total_tokens": 352,
    "reasoning_tokens": 0
  }
}
```

## JSON 模式

```bash
# 请求: 强制输出 JSON 格式
curl -X POST http://10.200.37.71:8801/v1/chat/completions \
  -H "Authorization: Bearer lgw-你的API密钥" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "模型名称",
    "messages": [{"role": "user", "content": "列出3种水果，包含名称和颜色"}],
    "response_format": {"type": "json_object"}
  }'

# 响应: 模型输出合法 JSON
{
  "choices": [{
    "message": {
      "content": "{\n  \"fruits\": [\n    {\"name\": \"苹果\", \"color\": \"红色\"},\n    {\"name\": \"香蕉\", \"color\": \"黄色\"},\n    {\"name\": \"葡萄\", \"color\": \"紫色\"}\n  ]\n}"
    },
    "finish_reason": "stop"
  }]
}
```

## 其他接口

| 方法 | URL | 说明 |
|------|-----|------|
| POST | `http://10.200.37.71:8801/v1/completions` | 文本补全 (Text Completions) |
| GET | `http://10.200.37.71:8801/v1/models` | 获取模型列表 |
| POST | `http://10.200.37.71:8801/v1/tokenize` | 分词 (文本 → token ID) |
| POST | `http://10.200.37.71:8801/v1/detokenize` | 反分词 (token ID → 文本) |

**分词示例**

```json
{
  "request": {
    "model": "模型名称",
    "prompt": "hello world"
  },
  "response": {
    "tokens": [
      14556,
      1814
    ],
    "count": 2,
    "max_model_len": 262144
  }
}
```

**反分词示例**

```json
{
  "request": {
    "model": "模型名称",
    "tokens": [
      14556,
      1814
    ]
  },
  "response": {
    "text": "hello world"
  }
}
```

