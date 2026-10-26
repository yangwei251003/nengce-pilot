# 获取后、模型评测前的数据边界修订 01

日期2026-10-04；未运行新数据模型评测。保留初始冻结协议不改写，修订原因是实际源文件/原报告核查，不是留出成绩。

1. RSF原报告 NREL/TP-5500-57785 PDF第12页说明发布数据已经用线性插值、典型日小时及异常修正清洗，但没有逐点插补标签；`observed`只代表有效的发布测量记录，不代表可证明的原始未插补传感器样本，metadata必须明确这一语义。第14页说明Total Building含热水90%效率、冷水COP3折算。因此不得把Total Building当纯电负荷。仅将Mechanical+Lighting+Plug Loads+Data Center构成电气分项研究负荷，与同站PV并列；partial_meter_boundary=true。将PV假设接到这些子负荷上的自用/弃光与费用是研究连接情景，不是原站真实自用率/电费。原Total Building、Heating、Cooling仅保留审计列。原测量时间标签未明确区间始末，保留标签且声明按区间始使用的情景假设；天气HOUR-MST说明固定MST，无DST，不擅自改成America/Denver夏令时。
2. 固定BDG2 v1.0下载的LICENSE实际为MIT；当前master为BY-SA，首次只读研究看master造成对固定版本的错误推断。保存两版许可证及实际URL/哈希，以固定v1.0原许可为准，同时保存数据论文/署名，不暗示提供方背书。
3. BDG2发布轴是无偏移的本地小时轴，作者论文称local time，原文件每年为连续24小时/日，无法恢复DST fold。保留source-local轴和源timezone字段，不假造UTC。仅进行该发布轴的小时情景/预测；禁止15分钟需量与真实合同账单认定。
4. UCI source-local时区未知不阻止明确示例合同下的完整15分钟月度需量计算；billing_identity=illustrative，actual_tariff_applicability=unverified。不得由此称韩国真实账单。
