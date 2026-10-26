# V3.1 实际接口

实现依据：`product/backend/v3/api.py`、`config.py`、`data.py`、`assistant.py`、`provider_profiles.py`。本文件描述已实现接口，不是提案。运行后可查看 `http://127.0.0.1:8003/docs` 与 `/openapi.json` 的实际Pydantic字段约束。

所有地址前缀 `/api/v3`。默认只监听127.0.0.1，不提供公网鉴权、多用户隔离或设备控制。

| 方法与路径 | 实际行为 |
|---|---|
| GET /health | 版本、本机模式、1个计算worker和20个未终结任务上限 |
| GET /defaults | 当前RunConfig默认配置；不是运行结果 |
| GET /datasets | 返回`datasets`目录，含来源、原始/标准化哈希、隐私、原生间隔、质量、适用范围和默认评估日期 |
| POST /datasets/import | 严格CSV校验；合法数据本机保存，`public_data:false`；非法数据返回`valid:false`和问题行 |
| GET /datasets/{dataset_id}/quality | 数量、缺测、异常线索阈值、示例原行与处理边界；不删除数据、不宣称故障诊断 |
| GET /protocols | 冻结协议正文与SHA256 |
| GET /scenarios | 压力情景、人民币示例合同身份与需量定义 |
| POST /runs | 提交真实计算，202返回运行记录 |
| GET /runs?limit=30&cursor=run-… | 按创建时间/编号稳定分页；limit为1—100；返回runs与next_cursor，不返回巨大的逐时结果 |
| GET /runs/{run_id} | 记录、进度和终态；成功时校验并返回不可变result |
| POST /runs/{run_id}/cancel | 排队或运行任务立即标取消；实际计算在安全检查点退出，迟到产物不发布为成功 |
| GET /runs/{run_id}/export/{json,csv,html} | 同一结果导出；先核对文件哈希，缺失或损坏返回409 |
| POST /batches | 原子提交1—20个独立RunConfig；逐站运行，非协同优化 |
| GET /batches/{batch_id} | 返回各子任务真实状态与派生批次状态 |
| GET /assistant/status | 外部凭据是否配置、固定模型和手动备选；不等于模型实时在线 |
| GET /assistant/providers | 自有模型非敏感配置；仅返回has_key，不返回密钥 |
| POST /assistant/providers | 新建自有兼容模型，Windows用户DPAPI加密存于项目外；保存不会调用模型 |
| PUT /assistant/providers/{profile_id} | 更新配置；省略api_key保留密钥，空字符串清除 |
| DELETE /assistant/providers/{profile_id} | 删除模型配置及对应密钥 |
| POST /assistant/providers/{profile_id}/test | 用户明确触发一次不含业务数据的连接测试；成功不证明问答质量 |
| POST /assistant/chat | 提交自由问题；绑定运行和结果SHA256；202返回request_id和session_id |
| GET /assistant/requests/{request_id} | 对话任务状态、实际回答、引用和参数草稿 |
| POST /assistant/requests/{request_id}/cancel | 立即取消对话，丢弃迟到回答 |
| GET /assistant/sessions?run_id=… | 当前运行保存的会话列表 |
| GET /assistant/sessions/{session_id} | 会话实际历史；不能把另一运行的会话当当前上下文 |

## 请求示例

先获取`/defaults`，修改所需字段后提交`/runs`，避免依赖过时的手写契约。主要字段如下：

```json
{
  "dataset_id": "uci-steel-15min",
  "battery": {
    "capacity_kwh": 100, "power_kw": 40,
    "min_soc": 0.1, "max_soc": 0.9, "initial_soc": 0.5,
    "charge_efficiency": 0.95, "discharge_efficiency": 0.95,
    "degradation_per_kwh": 0.03
  },
  "evaluation": {"start": "2018-12-01", "end": "2018-12-31"},
  "stress": "none",
  "risk_margin_scale": 1,
  "idempotency_key": "caller-generated-unique-key"
}
```

电价对象可使用谷/平/峰单价及小时集合，或显式24/96点`prices`。96点只用于15分钟数据。`currency`仅CNY；`demand_per_kw`为完整月15分钟最大需量单价。配置解析和核心数据资格检查分别执行。

CSV请求为`{csv_text,name,timezone,unit,authorized,interval_minutes,pv_column}`。时间列timestamp，kW对应load_kw，kWh对应load_kwh；光伏列同单位。申报15或60分钟，最少90天连续完整源日，最多100000行/20MB，不排序、不静默插补。未知时区需明确写source-local-unknown；IANA时区支持明确偏移，DST歧义会拒绝。`authorized:true`只是用户声明，不代表独立验证产权。

批量请求为`{configs:[...],idempotency_key}`。若剩余容量不足，整批429，不提交半批。相同幂等键与相同请求复用原记录；相同键不同请求409。运行取消后重新计算必须用新键。

助手请求为`{run_id,question,session_id?,provider?}`。默认`provider=local`为本机规则与证据解读，不是语言模型；可明确选择zhipu、openrouter或已保存的profile-…。内置型号不自动换平台或收费回退，自有云接口调用需已保存密钥与费用确认。服务使用保存于本机的会话历史，客户端messages兼容字段不能伪造系统上下文。详见`assistant-v3.1.md`；当前仅已核验公开案例可进入模型上下文，含自有本地接口也未扩大私人数据用途。

## 状态与完整性

- 任务状态：queued、running、succeeded、failed、cancelled。阶段文字来自实际后端；进度值按已完成阶段/日期更新，不是时间估计。
- 服务重启将未终结运行/对话标为failed、stage=interrupted；保留原始记录，不自动声称续算成功。
- SQLite仅存索引、配置和会话；结果目录含result/config/metrics/solver_audit JSON、timeseries CSV、HTML和manifest。写入使用独占标记，已冻结文件拒绝覆盖。
- 列表brief为索引中的B2费用/比较状态，详情与导出仍以校验后的不可变文件为准。历史迁移只回填索引，不更改旧结果。
- succeeded只表示程序结束并保存结果；`summary.comparison_valid`、逐策略`comparison_valid`、`cost_complete`与候选门槛必须另读。无效策略费用不得混进公平收益结论。
- 每步功率为kW；电量/裁剪/吞吐为kWh；SOC同时给kWh和百分比。`cumulative_cost`和日内费用只含购电能量费与吞吐代理，月需量集中在monthly_bills一次结算。
- 私人数据不能进入模型提供方；助手工具仅查询证据和形成草稿，无文件系统、命令、网络搜索、设备或自动重算权限。密钥不进入模型上下文或导出。

V2兼容接口仍位于旧`/api`路径，用于只读冻结结果兼容和回归。V3前端优先`/api/v3`；V2原目录未被修改。
