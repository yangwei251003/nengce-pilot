# V3 前端验证记录

2026-10-04，Windows x64，Node v24.15.0。开发目录限 product/frontend；V2只读。

## 当前回归

- PASS：npm ci --no-audit --no-fund，锁定的现有依赖安装成功，没有新增运行依赖。
- PASS：npm test，28项，4.05秒。完整用例与运行环境见 ui-test-v3.log。
- PASS：npm run build，TypeScript检查与45模块生产构建；Vite构建1.66秒，完整日志见 build-v3.log。
- PASS（限定范围）：contrast-review.json 中14个设计色对，辅助文字>=4.5:1，图形>=3:1。不是全页WCAG认证。
- 真实API/Edge：由项目主验收执行，根目录 qa/v3/browser-e2e-* 为权威逐项记录。本目录DOM测试使用mock网络，不能代替真实E2E。

## 开发中失败与修复

新增模态焦点单元测试首次运行发生 V8 OOM。后续缩小错误输出确认，焦点断言失败时直接比较DOM对象触发了大规模结构打印；同机当时仍有约3GB可用内存。该次执行为FAIL，未视为通过。

定位发现测试环境组合选择器的结果按选择器组排列，未保持预期文档顺序。焦点实现现显式按文档位置排序；测试比较布尔身份并限制失败输出。显式Tab/Shift+Tab首尾环绕过滤disabled、hidden和闭合details中的控件，Escape关闭后恢复触发按钮。修复后27项完整回归PASS；随后新增历史brief索引null回归，最终28项PASS。真实浏览器30次Tab环绕仍以根验收记录为准。

## fixture

fixtures/result.json 复制自真实本地V3单日15分钟结果，来源与SHA256见 fixtures/manifest.json。它是开发期行为回归夹具，不是最终模型泛化或收益证据。用例中的跨站点日期差异和异步迟到回复为明确构造的测试输入。
