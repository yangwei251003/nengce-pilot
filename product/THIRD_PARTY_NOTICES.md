# Third-party notices

本项目未复制第三方能源框架源码，也不宣称原创优化器或基础模型。组件提供的算法由本项目以数据隔离、可执行回放和审计方式集成。具体依赖版本见requirements.txt及每次结果的reproducibility。

| 组件 | 用途 | 上游许可证/来源 |
|---|---|---|
| NumPy | 数值数组 | BSD-3-Clause · https://numpy.org/ |
| pandas | 时序数据、能量守恒聚合 | BSD-3-Clause · https://pandas.pydata.org/ |
| SciPy | MILP接口 | BSD-3-Clause · https://scipy.org/ |
| HiGHS（SciPy所带） | MILP求解器 | MIT · https://highs.dev/ |
| scikit-learn | HistGradientBoosting CPU预测 | BSD-3-Clause · https://scikit-learn.org/ |
| FastAPI | 本地HTTP API | MIT · https://fastapi.tiangolo.com/ |
| Uvicorn | 本地ASGI服务器 | BSD-3-Clause · https://www.uvicorn.org/ |
| Pydantic | 输入校验 | MIT · https://docs.pydantic.dev/ |
| threadpoolctl | CPU线程控制 | BSD-3-Clause · https://github.com/joblib/threadpoolctl |
| HTTPX | API测试 | BSD-3-Clause · https://www.python-httpx.org/ |

数据：V E, S., Shin, C., & Cho, Y. (2021). Steel Industry Energy Consumption [Dataset]. UCI Machine Learning Repository. https://doi.org/10.24432/C52G8C 。CC BY4.0：https://creativecommons.org/licenses/by/4.0/ 。修改包括保留原字段的午夜规范化推断、15分钟能量转平均功率、小时聚合；原作者/原企业不为本产品背书。

没有将公开负荷数据许可证扩张为客户数据使用许可。上传者必须确认其授权，声明不会替代独立法律审查。组件完整许可文本随其已安装分发包提供；再次分发依赖时应保留其通知。
