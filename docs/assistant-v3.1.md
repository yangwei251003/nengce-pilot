# V3.1 证据助手与自有模型：实际接口和边界

V3.1 的默认 `local` 模式是本机确定性证据解读，不调用语言模型。它支持自由输入、运行内追问、当前结果引用和参数草稿，但对未识别问题应说明证据不足。预测、调度与费用始终由本机计算模块完成。原 V3 助手验收失败与限流记录保留于 `docs/assistant-v3.md` 和 `qa/v3`；新模式的测试不改写旧轮次。

## 实际接口

全部路径以下列前缀为准：`/api/v3`。JSON 请求和响应，错误返回对应 HTTP 状态。

| 路径 | 用途 | 关键规则 |
|---|---|---|
| `GET /assistant/status` | 内置免费服务可用性、披露信息 | 状态不保证下一次调用成功 |
| `GET /assistant/providers` | 列出自有配置的非敏感字段 | 返回 `has_key`，绝不返回 `api_key` |
| `POST /assistant/providers` | 新建自有配置 | `name, kind, base_url, model, api_key?, billing_ack, max_tokens`；云端需要用户确认费用 |
| `PUT /assistant/providers/{id}` | 更新配置 | 省略 `api_key` 保持现有密钥；传入新密钥则替换 |
| `DELETE /assistant/providers/{id}` | 删除配置及其密钥 | 本机来源校验 |
| `POST /assistant/providers/{id}/test` | 发送不含业务数据的单次兼容性测试 | 只表明返回兼容格式，不证明业务正确 |
| `POST /assistant/chat` | 在指定运行上发起问题 | `run_id, question, session_id?, provider`；默认 `provider=local` |
| `GET /assistant/requests/{id}` | 轮询助手请求 | `queued/running/succeeded/failed/cancelled` |
| `POST /assistant/requests/{id}/cancel` | 取消请求 | 迟到的模型回复不发布 |

`provider` 可以是 `local`、内置 `zhipu`、手动免费备选 `openrouter` 或已保存的 `profile-…`。用户必须主动选择在线提供方；失败不自动换平台、型号或付费服务。会话绑定 `run_id` 和结果 SHA-256，换运行应开新会话；服务端忽略客户端伪造的旧对话内容，只读取本次会话保存的历史。

## 自有模型配置

配置存储在当前 Windows 用户的 `%LOCALAPPDATA%/NengcePilot/providers.dpapi`，由 DPAPI 用户范围加密。`NENGCE_PROFILE_STORE` 仅用于受控本机测试；项目与交付目录内的路径被拒绝。此目录不随项目交付或同步。配置最多十个。云端只接受 HTTPS 公网主机；本地模型只接受 `localhost` 或回环 IP。拒绝 URL 内用户名、密码、查询参数和重定向；网络请求不使用代理环境变量。云端调用需要 `billing_ack=true` 和密钥；费用、配额与提供方条款由用户自己的账户负责，软件不查询或承诺价格。

内置智谱密钥仍从项目外的 `NENGCE_CREDENTIAL_FILE` 读取。不要在聊天、文档、日志、前端构建物或项目配置里填写密钥。自有模型的连接测试只发送英文固定短句，不含电表数据。可选云端业务问答只对结果元数据 `public_data=true` 的已核验公开案例开放，发送去标识问题和必要派生事实；私人/客户运行会被拒绝，即使配置的是自有模型。自由文本去标识不是全面匿名保证，公开案例问题也不应夹带客户信息。

## 证据与回答

本机与在线模式均使用当前运行的只读事实工具。可查费用分项、策略比较、风险时段、选模理由、数据来源和限制；草稿仅能采用用户明确给出的容量、功率、需量单价或风险倍数，显示旧值、新值和单位，**不会应用或计算新费用**。在线模型的数字与日期必须由后端事实引用回填；无来源数字、错误策略归属、未经验证的收益或设备认证承诺会被拒绝。没有现场故障标签时仅称“异常线索”。

本机模式对已有证据作模板化回答，不能理解所有自然语言，也不是模型推理。内置免费云服务和用户自有模型的问答质量须分别实测；本机50题通过不能外推到云端。正式验收见 `qa/v31/assistant` 与 `qa/v31/acceptance-matrix.json`，其中区分格式通过、逐题业务审阅、真实浏览器和在线连通。
