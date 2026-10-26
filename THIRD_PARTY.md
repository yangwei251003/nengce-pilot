# 源码、数据和素材许可

自有源码与本次整理文档按根 MIT 提供。标准数值库、服务框架、React、公开数据及第三方文献各自保留原权利，不因根 MIT 而改换许可。

- `licenses/python/` 保存锁定的 27 个 Python 运行依赖中提供的完整版权/许可文本和版本清单，包含数值库捆绑组件的声明。
- `licenses/javascript/` 保存 React、React DOM、Scheduler 三个生产依赖的完整声明；前端分发 ZIP 同时附带声明。
- Node/TypeScript/Vite、可选 Python Playwright 等开发工具由各自发行包提供原许可，不随源码复制其安装缓存。
- 公开数据按 [数据许可记录](data/DATA_LICENSES.md) 和压缩包内原始来源/变换记录提供。数据原件及规范化版本没有被根 MIT 替换许可。
- `docs/images/` 是本次真实本地运行/只读案例的浏览器截图，仅显示公开研究负荷与示例电价，不含私人账单、客户数据或账号。
- `distribution/frontend-3.1.1-open.zip` 是与本次 React 源码对应的正式分发界面，不是依赖缓存或开发临时文件；清单保存构建命令和 SHA256。
- RSF 文献 PDF、影片/音乐、比赛规则截图、商业/财务材料和其他未核实再分发权的材料未随公开源码或数据附件分发。

`tools/archive_dependency_licenses.py` 可在安装锁定依赖后重新收集声明，缺失声明时会报错；没有把未知许可自动当作 MIT。
