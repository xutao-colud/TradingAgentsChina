# 多模型运行时

## 支持的官方预设

| ID | 服务商 | 固定基础地址 | 默认模型 | 环境变量 |
| --- | --- | --- | --- | --- |
| `deepseek` | DeepSeek | `https://api.deepseek.com` | `deepseek-v4-pro` | `DEEPSEEK_API_KEY` |
| `glm` | GLM（智谱） | `https://open.bigmodel.cn/api/paas/v4` | `glm-5.1` | `ZAI_API_KEY` |
| `qwen` | 通义千问（百炼） | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-plus` | `DASHSCOPE_API_KEY` |

这些服务商都采用 OpenAI Chat Completions 兼容模式。基础地址固定为官方预设，不提供任意 URL 输入，避免把本地服务变成内网请求代理。

## 密钥生命周期

1. 网页输入的 API Key 仅保存在当前 Python 服务进程内存；刷新页面不显示密钥。
2. 服务重启后，页面输入的密钥自动失效。
3. 如需重启后可用，请通过系统环境变量配置对应密钥后再启动本地服务。
4. `trading-agents-memory.json` 和 `model_settings.json` 只保存服务商 ID 与模型名，绝不保存 API Key。

PowerShell 示例：

```powershell
$env:DEEPSEEK_API_KEY = "your-key"
python -m app.web.server --port 8002
```

请定期轮换密钥，不要把密钥提交到 Git、截图或导出的个人档案中。

## 分析边界

模型获得的是确定性报告、可迁移记忆摘要和带来源/时间的实时行情上下文。它只能解释证据、反例、风格适配和待核验项目，不能改写评分、风控否决条件或下单。
