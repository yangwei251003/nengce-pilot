# 公开研究数据许可核对

核对日期：2026-10-26。独立 Release 数据附件仅由原工程明确 `public_data=true`、`privacy=public` 的公开研究数据及其来源/许可记录组成；没有纳入私人导入。

| 来源 | 版本/身份 | 许可及依据 |
| --- | --- | --- |
| UCI Steel Industry Energy Consumption | DOI 10.24432/C52G8C，同厂两个间隔视图 | [官方数据页](https://archive.ics.uci.edu/dataset/851/steel+industry+energy+consumption) 明确 CC BY 4.0；保留作者署名、原始 CSV/ZIP 与变换说明 |
| Building Data Genome 2 | 固定 Git tag v1.0；24 栋、6 site | [该固定版本 LICENSE](https://github.com/buds-lab/building-data-genome-project-2/blob/v1.0/LICENSE) 为 MIT，©2020 BUDS Group；不拿当前 master 的不同许可冒充历史版本 |
| NREL RSF Measured/Weather 2011 | DOI 10.25984/1845288 等对应公开记录 | [官方 measured 记录](https://data.openei.org/submissions/358)、[weather 记录](https://data.openei.org/submissions/357) 本轮公开 HTTP 均返回 200，记录中许可链接为 CC BY 4.0；原来源页也保存在数据档 |
| Open Power System Data Household Data | 固定 2020-04-15 | [官方版本页](https://data.open-power-system-data.org/household_data/2020-04-15/) 与所附 datapackage 记录 CC BY 4.0；保留 CoSSMic/ISC Konstanz、OPSD 署名，五通道只供审查 |

RSF 的 DataCite 元数据确认题名与托管方，但 `rightsList` 为空，不能单独当许可证明。本次以具体 OEDI 记录的许可字段为依据，没有将平台“公开可访问”自动等同于开放许可。

**PDF 文献单独处理**：`rsf-report-57785.pdf` 未纳入附件。数据集 CC BY 不自动覆盖该文献的再分发权。其官方链接与冻结 SHA256 在 `archive-manifest.json` 的 `excludedReferenceDocuments` 中；使用者可按根 README 自行取得并只在本地校验。原加载器仍要求完整原件校验，缺文件的 RSF 案例不会假装可运行。

UCI 署名：V E, S., Shin, C., & Cho, Y. (2021). *Steel Industry Energy Consumption*. UCI Machine Learning Repository. https://doi.org/10.24432/C52G8C 。规范化将 15 分钟能量转换为平均功率，并保留午夜时间推断与原始行映射；不暗示作者或原企业为本产品背书。

BDG2 署名：Miller et al. (2020), Building Data Genome Project 2, BUDS Lab；DOI 10.5281/zenodo.3887306。RSF 署名：Sheppy, Beach, Pless, NREL/DOE。OPSD 署名：Open Power System Data (2020), Household Data, version 2020-04-15, CoSSMic / ISC Konstanz。完整逐数据集来源、许可、原始/规范化哈希、单位和变换保留在附件元数据中。

数据包约 89 MB，解压约 304 MB；`archive-manifest.json` 锁定压缩包及每个文件。哈希锁定来源身份，不是对数据适用性、完整月覆盖、合同有效性或算法成功的证明。
