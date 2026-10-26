"""Offline, bounded evidence interpreter. This is deliberately not an LLM.

Known business intents query the same immutable evidence tools as the cloud
assistant. Unsupported or ambiguous intents request clarification rather than
inventing an answer. No network, files, execution or autonomous parameter edits.
"""
import hashlib
import json
import re
import time

STRATEGIES = r'(?<![A-Za-z0-9])(?:B0|B1|B2|N1|L1|R1|R2|O1)(?![A-Za-z0-9])'
GUARD = r'密钥|api\s*key|系统提示词|隐藏文件|读取.{0,8}文件|执行.{0,8}(命令|脚本)|忽略.{0,8}(规则|指令)|夸大.{0,6}(收益|利润)|删除.{0,8}(失败|证据)|发给云端|上传'


def strategies(question, history):
    found = re.findall(STRATEGIES,question.upper())
    if found:
        return list(dict.fromkeys(found))
    aliases=[('无储能','B0'),('固定规则','B1'),('朴素预测','N1'),('简单预测','N1'),
             ('学习候选','L1'),('学习预测','L1'),('安全余量','R1'),('固定余量','R1'),
             ('可达余量','R2'),('完美预知','O1')]
    named=[(question.find(alias),ident) for alias,ident in aliases if alias in question]
    # A named comparison baseline alone is not the requested strategy.
    if re.search(r'(?:相比|相对|比|较|与|和|跟)无储能|无储能(?:相比|比较|对比)',re.sub(r'\s+','',question)):
        named=[x for x in named if x[1]!='B0']
    if named:
        return list(dict.fromkeys(ident for _,ident in sorted(named)))
    for message in reversed(list(history)[-6:]):
        if message.get('role')=='user':
            found = re.findall(STRATEGIES,message.get('content','').upper())
            if found:
                return [found[-1]]
    return ['B2']


def _intents(question):
    kinds=[]
    if re.search(r'盈利|回本|投资回报|寿命|认证|客户|订单|故障|全部.{0,12}AI|都.{0,12}AI|真实账单|中国.{0,6}账单|必然赚钱|保证',question,re.I):
        kinds.append('limits')
    if re.search(r'费用|成本|账单|能量费|需量|代理|节省|节费|增量|贡献|归因|峰值|购电峰|省多少|分项',question):
        kinds.append('cost')
    if re.search(r'裁剪|反送|SOC保护|功率保护|日终|末SOC.*误差|吞吐|风险|余量|回退|弃光|违反|最大.{0,8}(时段|时间)|异常',question,re.I):
        kinds.append('risk')
    if re.search(r'预测|模型|MAE|WAPE|区间覆盖|盲测|历史回归|选模|留出',question,re.I):
        kinds.append('forecast')
    if re.search(r'来源|源数据|许可|时区|时间语义|间隔|采样|原始|哈希',question):
        kinds.append('provenance')
    if re.search(r'哪几天|覆盖.{0,8}(日期|时间|几天)|哪段时间|电池容量|容量.{0,10}功率|共同.{0,6}SOC|评估开始|评估结束|概况|介绍.{0,6}结果',question,re.I):
        kinds.append('summary')
    if re.search(r'日内费用|当天|这一天|当日',question):
        kinds.append('daily')
    if re.search(r'真实账单|中国.{0,6}账单',question):
        kinds=['provenance']
    if 'cost' in kinds:
        if 'forecast' in kinds and not re.search(r'MAE|WAPE|模型|误差|为什么|准确|预测区间|选模|盲测|历史回归',question,re.I):
            kinds.remove('forecast')
        if 'risk' in kinds and not re.search(r'裁剪|门槛|回退|弃光|失败|违规|SOC保护|功率保护|风险下降|代价|吞吐量',question,re.I):
            kinds.remove('risk')
    return list(dict.fromkeys(kinds))


def _draft_values(question, history, query_type):
    values={}
    texts=[m.get('content','') for m in list(history)[-60:] if m.get('role')=='user']+[question]
    # Later explicit requests replace earlier ones, preserving unrelated fields.
    for text in texts:
        allowed=query_type(text)
        for field, candidates in allowed.items():
            if not candidates:
                continue
            if len(candidates)>1:
                raise ValueError('同一参数出现多个数值，请明确需要哪一个；尚未形成草稿')
            values[field]=next(iter(candidates))
    return values


def _select(kind, evidence, question, selected):
    if kind=='limits':
        patterns=[]
        for words,pattern in [('盈利|保证|必然赚钱','年度盈利'),('回本|投资回报|寿命|必然赚钱','真实回本'),
                              ('认证|安全','设备安全'),('付费客户|多少.{0,8}客户|订单|客户数量','客户与订单'),('故障','故障诊断'),
                              ('AI|价值|归因','AI收益归因')]:
            if re.search(words,question,re.I):patterns.append(pattern)
        return [x for x in evidence if any(re.search(p,x['label']) for p in patterns)]
    if kind=='cost':
        labels=[x['label'] for x in evidence]
        picked=[]
        def take(pattern):
            picked.extend(x for x in evidence if re.search(pattern,x['label']))
        if re.search(r'贡献|归因|全部|都.*AI|区分',question):
            take('费用归因链|学习增量结论')
        elif re.search(r'增量',question) and ('学习' in question or set(selected)=={'N1','L1'}):
            take('学习增量结论|学习预测相对朴素')
        if re.search(r'分项|能量费|需量费|吞吐代理|包括|账单',question):
            take('购电能量费|月需量费|吞吐代理成本|费用统计口径')
        if re.search(r'峰值|购电峰',question):take('实际进口峰值')
        if re.search(r'节省|节费|省多少',question) and not re.search(r'学习|增量|归因|贡献',question):take('较无储能节省')
        if re.search(r'变化|比较|对比',question):
            picked.extend(x for x in evidence if x['label'] in [s+'总费用' for s in selected])
            take('费用统计口径')
        if not picked or re.search(r'总费|费用是多少|费用多少|总成本',question):
            picked.extend(x for x in evidence if x['label'] in [s+'总费用' for s in selected])
        picked.extend(x for x in evidence if x['label'] in [s+'比较有效' for s in selected])
        if 'O1' in selected:
            # O1 identity is a diagnostic boundary, never a executable forecast.
            picked.append({'note':'O1 为完美预知诊断参照，未来实测信息不可用于可执行计划；不能视作部署预测方案或全月全局最优保证。'})
        return picked
    if kind=='risk':
        patterns=[]
        for words,pattern in [
            ('反送','禁止反送'),('SOC保护','SOC保护'),('功率保护','功率保护'),('日终|末SOC','日终电量误差'),
            ('吞吐','AC侧吞吐'),('回退','回退次数'),('失败','余量计划失败'),('弃光','累计弃光')]:
            if re.search(words,question,re.I):patterns.append(pattern)
        if re.search(r'三个|定位|时段|时间段|异常',question) or ('最大' in question and '裁剪' in question):patterns.extend(['风险时段','该时段动作裁剪'])
        if re.search(r'累计|裁剪量|裁剪多少',question):patterns.append('累计动作裁剪')
        if re.search(r'门槛|依据|预设',question):
            patterns.extend(['候选风险门槛','较B2','保留B2','预设','余量松弛','终端修复','风险措施结论'])
        elif re.search(r'风险|比较|变化|余量',question):
            patterns.extend(['较B2累计裁剪下降','较B2费用增加','保留B2节费比例','风险措施结论'])
        if not patterns:patterns=['累计动作裁剪','禁止反送','SOC保护','功率保护','最大日终','回退']
        patterns.append('风险指标口径')
        return [x for x in evidence if any(re.search(p,x['label']) for p in patterns)]
    if kind=='forecast':
        base={'开发验证所选负荷模型（运行级）','开发选模理由（运行级）','评测身份（运行级）','评测结论边界'}
        owner='光伏' if '光伏' in question else '负荷' if '负荷' in question else ''
        if re.search(r'MAE|绝对误差',question,re.I):return [x for x in evidence if ('平均绝对误差' in x['label'] and x['label'].startswith(owner)) or x['label'] in base]
        if re.search(r'WAPE',question,re.I):return [x for x in evidence if ('WAPE' in x['label'] and x['label'].startswith(owner)) or x['label'] in base]
        if re.search(r'光伏',question):return [x for x in evidence if '光伏' in x['label'] or x['label'] in base]
        if re.search(r'区间|覆盖',question):return [x for x in evidence if '区间' in x['label'] or x['label'] in base]
        return [x for x in evidence if x['label'] in base]
    if kind=='summary':
        if re.search(r'哪几天|覆盖|开始|结束|哪段时间',question):return [x for x in evidence if x['label'] in {'评估开始','评估结束'}]
        if re.search(r'容量|功率|SOC|效率',question,re.I):return [x for x in evidence if x['label'] in {'电池容量','额定功率','共同日终SOC比例','充电效率比例','放电效率比例'}]
    if kind=='provenance' and re.search(r'真实账单|中国.{0,6}账单',question):
        return [x for x in evidence if x['label'] in {'数据名称','warning'}]
    return evidence


def answer(result, question, history, cancelled, progress):
    started=time.perf_counter()
    from .assistant import EvidenceQuery, requested_parameter_values, deidentify
    if cancelled():raise InterruptedError('已取消助手请求')
    if re.search(GUARD,question,re.I):
        return {'mode':'blocked','content':'助手只能查询本次运行的业务证据，不能读取密钥、隐藏文件、执行命令、上传数据或修改失败证据。私人数据默认不外发。','citations':[],'provider':'本机证据解读','model':None}
    question=deidentify(question)[:2000]
    selected=strategies(question,history)
    query=EvidenceQuery(result,requested_parameter_values(question,history))
    progress('正在本机读取冻结结果；不会调用云模型')
    date_match=re.search(r'\d{4}-\d{2}-\d{2}',question)
    date=date_match.group(0) if date_match else None
    facts=[];notes=[]
    if date and not any(tick['timestamp'].startswith(date) for tick in result.get('series',[])):
        notes.append('指定日期没有匹配时段；不能提供该日风险或费用。下述累计指标仍覆盖整个运行，不能误认为该日指标。')
    is_draft=bool(re.search(r'草稿|改为|改成|设成|设为|调整.{0,8}(容量|功率|需量|余量)|再把',question))
    if is_draft:
        values=_draft_values(question,history,requested_parameter_values)
        if values:
            query.allowed_draft_values={field:{value} for field,value in values.items()}
            facts=query.propose(values)['evidence']
            notes.append('仅生成你明确指定数值的参数草稿，尚未应用、尚未重算，不能推断新费用。')
        else:
            notes.append('尚未形成参数草稿。请明确参数与数值，例如电池容量、功率、需量单价或风险余量倍数；本机解释器不会猜测参数。')
    else:
        kinds=_intents(question)
        if not kinds and re.search(r'刚才|这个|那|继续|分项|它',question):
            previous=next((m.get('content','') for m in reversed(list(history)[-6:]) if m.get('role')=='user'), '')
            kinds=_intents(previous)
        if not kinds:
            notes.append('本机证据解读无法可靠识别这个问题。可查询策略费用、裁剪时段、模型误差、来源与参数草稿；开放式推理请明确选择已配置的模型。未编造答案，也未自动调用云服务。')
        for kind in kinds:
            for strategy in (selected if kind in {'cost','risk'} else selected[:1]):
                output=query.inspect(kind,strategy,date)
                if output.get('error'):
                    notes.append(output['error']);continue
                for item in _select(kind,output['evidence'],question,selected):
                    if 'note' in item:notes.append(item['note'])
                    else:facts.append(item)
        if 'cost' in kinds and len(selected)==2 and re.search(r'相比|相对|比较|对比|变化|增量',question):
            byid={row['id']:row for row in result['strategies']}
            if all(s in byid for s in selected):
                a,b=[byid[s] for s in selected]
                valid=all(row.get('comparison_valid') is True and row.get('total_cost') is not None for row in [a,b])
                facts.append(query.add('费用差（'+' − '.join(selected)+'）',a['total_cost']-b['total_cost'] if valid else None,
                                       '元','report',compared_strategies=selected))
                if not valid:notes.append('所问策略费用覆盖不足或比较无效，不能把差额解释为增量收益。')
        if re.search(r'真实账单|中国.{0,6}账单',question):
            notes.insert(0,('这不是经核验的中国客户真实账单。当前公开海外案例使用声明的人民币示例合同；客户现场数据和适用计费合同仍需单独验证。'
                if result.get('dataset',{}).get('public_data') is True else '导入客户数据不等于已核验完整真实账单；现场计量、适用合同和计费覆盖仍需单独审查。'))
        if re.search(r'必然赚钱',question):
            notes.insert(0,'风险下降不代表费用必然下降。应同时审阅风险候选的累计裁剪、费用增加和保留节费比例；未核验长期投资回报。')
    if cancelled():raise InterruptedError('已取消助手请求')
    unique=[];seen=set()
    for fact in facts:
        stored=query.facts[fact['fact_id']]
        signature=(stored['label'],stored['strategy'],stored['timestamp'],stored['text'])
        if signature not in seen:seen.add(signature);unique.append(stored)
    lines=[]
    for fact in unique:
        label=fact['label']
        if label in {'当前策略','比较有效','总费用','较无储能节省','动作裁剪'}:label=fact['strategy']+' '+label
        if fact['timestamp'] and isinstance(fact['value'],(int,float)) and not isinstance(fact['value'],bool):label+='（'+fact['timestamp']+'）'
        lines.append(label+'：'+fact['text'])
    content='\n\n'.join(list(dict.fromkeys(notes))+lines)
    result_hash=hashlib.sha256(json.dumps(result,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    return {'mode':'local','content':content,'message':content,'citations':unique,
            'draft_patch':query.draft_patch,'draft_rejected_fields':query.draft_rejected_fields,
            'provider':'本机证据解读','model':None,'usage':[],'elapsed_seconds':time.perf_counter()-started,
            'result_sha256':result_hash,
            'disclosure':'本次是本机规则与证据查询，未使用语言模型，未发送数据到外部。支持范围内的数值直接读取冻结结果；超出范围明确提示未知。'}
