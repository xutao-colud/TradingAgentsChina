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
5. 网页密钥只能从 `127.0.0.1`/`::1` 配置；局域网客户端可使用已配置模型，但不能向服务端提交密钥。需要局域网共享时，请在服务主机通过环境变量注入密钥。

PowerShell 示例：

```powershell
$env:DEEPSEEK_API_KEY = "your-key"
python -m app.web.server --port 8002
```

请定期轮换密钥，不要把密钥提交到 Git、截图或导出的个人档案中。

## 模型切换一致性

- 选择服务商或修改模型名后，必须先点击“配置当前模型”；未保存的界面选择不会触发请求。
- 每次研判请求都会携带期望的服务商和模型，后端与当前生效配置不一致时直接拒绝，不回退到旧模型。
- 切换服务商会清除其他服务商的进程内会话密钥；研判过程中发生切换时，旧模型返回结果会被丢弃。
- 报告和本地分析事件记录实际执行的服务商、模型、官方基础地址及起止时间。HTTP 错误使用实际服务商名称，不再统一标记为 DeepSeek。

## 分析边界

模型获得的是确定性报告、可迁移记忆摘要和带来源/时间的实时行情上下文。它只能解释证据、反例、风格适配和待核验项目，不能改写评分、风控否决条件或下单。
