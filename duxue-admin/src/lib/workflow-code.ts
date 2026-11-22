type CodeLogic = { title: string; summary: string };

const actions: Record<string, Record<string, CodeLogic>> = {
  'tutoring-blueprint': {
    'tutoring.finish-solution': {
      title: '汇总核验与置信度定级',
      summary:
        '按小问检查最终答案完整性，结合确定性引擎四态核验、核验强度（充分/必要条件）与双路三态比对结果定级置信度，返回 VerifiedSolution。',
    },
  },
  companion: {
    decide: {
      title: '决定对话去向',
      summary:
        '综合本轮意图、当前会话、是否有图片和切换审核结果，决定继续当前场景、切换场景或先向孩子确认。',
    },
  },
  planning: {
    prepare_review: {
      title: '准备计划草稿',
      summary:
        '读取属于当前孩子的已有草稿，或用本轮信息保存新草稿。字段有缺项时返回待补充内容，齐全时标记为可确认。',
    },
    route_after_prepare: {
      title: '判断能否确认',
      summary:
        '读取草稿是否已准备好的标记。信息齐全时进入确认环节，仍有缺项时结束本轮并等待补充。',
    },
    wait_for_confirmation: {
      title: '等待孩子确认',
      summary:
        '向孩子展示草稿并暂停流程。收到确认命令后恢复，恢复时沿用原草稿，避免重复写入。',
    },
    'planning.checkpointer_connect': {
      title: '连接会话检查点',
      summary: '建立计划流程所需的检查点存储连接，用于在确认前后恢复会话状态。',
    },
    'planning.checkpointer_setup': {
      title: '初始化会话检查点',
      summary: '准备流程所需的检查点存储结构，使后续执行可以保存和恢复状态。',
    },
    'planning.context_build': {
      title: '准备计划上下文',
      summary: '整理本轮排期请求及当前会话可读取的计划上下文，供计划流程处理。',
    },
    'planning.graph_compile': {
      title: '装配计划流程',
      summary: '将已登记的步骤、路由和检查点存储装配成可执行的计划状态图。',
    },
    'planning.graph_invoke': {
      title: '运行计划流程',
      summary:
        '将本轮输入或确认命令交给计划状态图，获取补充信息、等待确认或已确认的结果。',
    },
  },
  reflection: {
    'reflection.turn': {
      title: '处理今日复盘',
      summary:
        '缺少日期或首次总结内容时等待孩子补充。信息齐全时保存或更新自述，并告知孩子当天的客观观察报告是否已就绪。',
    },
  },
  tutoring: {
    'tutoring.intake': {
      title: '检查输入与会话状态',
      summary:
        '检查当前会话、已有题目和本轮输入，返回输入安全与孩子主动确认的结果。',
    },
    'tutoring.close': {
      title: '结束答疑',
      summary: '关闭当前答疑会话，记录结束事实并返回会话引用。',
    },
    'tutoring.blocked_input': {
      title: '处理受限输入',
      summary: '记录本轮提问，并向孩子展示预设安全提示。',
    },
    'tutoring.understood': {
      title: '记录孩子确认',
      summary: '保存孩子自己确认已理解的事实，并返回当前题目状态。',
    },
    'tutoring.media_access': {
      title: '检查图片归属',
      summary: '检查所有附件键是否属于当前孩子。',
    },
    'tutoring.reject_media': {
      title: '提示重新拍照',
      summary: '附件授权检查未通过时，请孩子重新上传。',
    },
    'tutoring.clarify_image': {
      title: '澄清图片指代',
      summary: '请孩子指出要检查哪张照片，或补传未读取成功的图片。',
    },
    'tutoring.self_review': {
      title: '读取近期自述',
      summary: '存在任务时，按孩子和任务读取近期自述，供本轮教学使用。',
    },
    'tutoring.answer': {
      title: '交付审核后的回复',
      summary: '按本轮教学结果记录消息与学习事实，投影已通过检查的配图。',
    },
    'tutoring.fallback': {
      title: '返回审核兜底',
      summary: '依据失败类型返回预设反馈，保留题目进度。',
    },
    'tutoring.blocked_output': {
      title: '替换受限输出',
      summary: '记录安全拦截，交付预设提示。',
    },
    'tutoring.pronounce': {
      title: '展示发音',
      summary: '投影发音课卡，并保留上下文来源。',
    },
    'tutoring.clarify': {
      title: '澄清问题',
      summary: '展示需要澄清的问题和候选项，等待孩子回复。',
    },

    'tutoring.turn': {
      title: '准备答疑上下文',
      summary: '加载孩子的上下文和当前会话，识别本轮是否要求结束答疑。',
    },
    'tutoring.model_loop': {
      title: '编排答疑生成与重试',
      summary:
        '组织模型生成、工具请求和质量审核。根据候选结果和预算决定结束、修复后重试，或启用已配置的备用模型。',
    },
    'tutoring.exit_gate': {
      title: '组织答疑候选审核',
      summary:
        '核对候选中的数学依据，并组织教学权限、文字答案保护及必要的配图审核。审核失败时将原因交回重试或兜底路径。',
    },
    'tutoring.apply_problem': {
      title: '更新题目进度',
      summary:
        '通过审核且属于解题辅导的回复，才会按当前教学权限记录作答证据或推进提示、题目状态。',
    },
    'tutoring.result': {
      title: '整理并返回答疑结果',
      summary: '返回已经准备好的答疑结果和下一步交互。',
    },
  },
  'tutoring-retry': {
    primary: {
      title: '主模型首次尝试',
      summary:
        '用本轮上下文调用主模型，校验候选并运行适用的审核。根据结果决定是否需要进一步修复。',
    },
    repair: {
      title: '按审核反馈修复',
      summary:
        '将候选未通过的原因转换成修复指令，再调用主模型生成并审核新版候选。',
    },
    backup: {
      title: '备用模型尝试',
      summary:
        '主模型修复后仍出现相同的答案保护问题时，使用已配置的备用模型生成修复候选，并重新审核。',
    },
    visual_decision: {
      title: '判断是否重绘配图',
      summary:
        '根据已审核的候选是否仅因配图泄露被移除，决定进入重绘还是继续检查是否需要补图。',
    },
    visual_redraw: {
      title: '重绘未通过审核的配图',
      summary:
        '请主模型重绘配图。新图通过审核且正文、教学动作和题目状态提议均保持一致时，才采用新图。',
    },
    missing_decision: {
      title: '判断是否需要补图',
      summary:
        '检查已通过审核的文本是否还缺少所需配图，或是否用文本排版代替图。符合补图条件时准备修复提示。',
    },
    missing_primary: {
      title: '主模型补画配图',
      summary:
        '加载配图规范后请主模型补图，只有得到通过审核且符合本轮要求的配图才替换已有候选。',
    },
    missing_backup: {
      title: '备用模型补画配图',
      summary:
        '主模型补图未成功且允许再试时，调用已配置的备用模型，并按同样的交付要求审核新图。',
    },
    finish: {
      title: '汇总本轮尝试结果',
      summary:
        '返回候选及审核结果，记录本轮是否重试。仍缺少本轮所需配图时标记失败，由上层流程兜底。',
    },
  },
  'tutoring-vet': {
    'tutoring.complete_vetting': {
      title: '汇总教学审核',
      summary:
        '合并权限、文字和配图检查结果。权限或文字未通过时返回失败原因，单独被拒的配图不随回复交付。',
    },
  },
};

const gates: Record<string, string> = {
  'tutoring.select-route':
    '检查已授权题库命中与 T0 直答，判断是否需要按需复读（模糊/涂改图），并将 T1 普通题与 T2 并发双路彻底分轨。',
  'tutoring.reread-check':
    '仅比对初读与复读的关键数值、符号与设问（忽略图描述措辞差异）；确认分歧直接短路，一致则恢复路由或转备用求解。',
  'tutoring.verify-route':
    '调用确定性学科引擎（math_executor）输出四态核验（verified / contradicted / not_applicable / unknown）；仅 contradicted 时按需复读或切异构备用。',
  'tutoring.verify-backup':
    '调用确定性学科引擎复核异构备用求解结果的锚点四态，直接汇总交付，不再循环或升级。',
  'tutoring.verify-t2':
    '对 T2 并发双路逐路跑确定性引擎核验，自动淘汰被证伪的一路，并对最终答案输出三态比对（consistent / contradicted / incomparable）。',
  'planning.confirmation_gate':
    '检查孩子是否发出了有效的确认命令，并用命令携带的草稿版本执行确认。未确认时继续等待，校验通过后才写入正式安排。',
  'tutoring.check_authority':
    '把模型提议的教学动作与本轮允许的权限对照。越权时拒绝候选；允许的候选按题目状态决定是否还要做答案保护审核。',
  'tutoring.tool_budget':
    '比较当前工具调用次数与本轮上限。预算用完时跳过该工具调用，并把预算耗尽的状态反馈给模型。',
  'tutoring.candidate_schema':
    '校验模型候选的必填字段、字段类型和图片核验证据。校验失败时返回修复反馈，后续尝试仍受本轮调用预算限制。',
  'tutoring.visual_schema':
    '检查候选配图是否符合结构约定，并区分合格、缺图和结构错误。结构错误的图会剔除，符合条件时可请求模型修复。',
  'tutoring.visual':
    '根据当前教学动作和配图交付规则决定是否保留候选配图。被移除的图会附带原因，供后续审核或重试使用。',
  'tutoring.candidate_exit':
    '候选校验被拒时记录出错的字段、错误类型和是否还能重试，帮助定位模型输出与协议的差异。',
  'tutoring.output_safety':
    '交付前检查孩子会看到的正文和配图文字。输出不安全时走安全兜底，候选此前已经被拒时跳过这项扫描。',
};

export function actionLogic(
  workflowId: string,
  node: { kind?: unknown; handler_id?: string },
) {
  return node.kind === 'action'
    ? actions[workflowId]?.[node.handler_id ?? '']
    : undefined;
}

const edgeConditions: Record<
  string,
  Record<string, { label: string; summary: string }>
> = {
  tutoring: {
    closing: {
      label: '结束答疑',
      summary: '孩子本轮明确表示结束提问或关闭当前答疑会话。',
    },
    open: {
      label: '会话进行中',
      summary: '当前答疑会话保持打开，继续检查本轮输入与状态。',
    },
    unsafe_input: {
      label: '输入安全拦截',
      summary: '本轮输入命中安全规则，不调用模型，直接返回安全提示。',
    },
    confirmed: {
      label: '孩子确认理解',
      summary: '孩子主动确认已理解当前题目，直接记录理解确认事实。',
    },
    question: {
      label: '正常提问',
      summary: '输入安全且非纯确认，进入图片鉴权与正常答疑流程。',
    },
    foreign_media: {
      label: '图片归属异常',
      summary: '附件中存在不属于当前孩子的图片 key，拒绝读取并请重拍。',
    },
    authorized: {
      label: '图片已授权/无图',
      summary: '全部附件归属校验通过，或本轮不涉及图片。',
    },
    ambiguous: {
      label: '图片指代不明',
      summary: '历史窗口中存在多张候选图片且无法确定本轮指向，先请孩子澄清。',
    },
    resolved: {
      label: '图片目标已确定',
      summary: '已唯一确定本轮目标图片（或纯文字提问），进入答疑生成。',
    },
    work: {
      label: '通过 · 解题辅导',
      summary: '输出安全与教学审核通过且属于解题推进，先更新题目进度（TutoringProblem）再交付。',
    },
    conversation: {
      label: '通过 · 普通对话',
      summary: '输出通过审核但属于寒暄/元对话，不改动题目进度，直接交付回复。',
    },
    failed: {
      label: '审核未通过/耗尽',
      summary: '候选未通过审核或重试预算耗尽，保留原题目进度并走预设兜底。',
    },
    unsafe_output: {
      label: '输出安全拦截',
      summary: '交付前输出安全扫描未通过，替换为预设安全提示且不改动题目进度。',
    },
    pronounce: {
      label: '发音辅导',
      summary: '本轮教学动作为纯发音示范，直接交付发音课卡。',
    },
    clarify: {
      label: '需要澄清',
      summary: '题面模糊或缺少必要条件，直接向孩子发出澄清问题。',
    },
  },
  'tutoring-retry': {
    no_candidate: {
      label: '无可用候选',
      summary: '首轮尝试未产出可审核候选，直接结束并交上层兜底。',
    },
    retry_leak: {
      label: '审核拦截，修复重试',
      summary: '候选未通过答案保护或教学审核，带反馈让主模型修复重试。',
    },
    candidate_without_retry: {
      label: '首轮通过/无需文本修复',
      summary: '首轮文本候选已过审，进入配图重绘与补图判断。',
    },
    same_leak_with_backup: {
      label: '重复拦截，切备用模型',
      summary: '主模型修复后仍触发同类拦截且已配置备用模型，切换备用模型重试。',
    },
    no_backup_needed: {
      label: '无需切备用模型',
      summary: '修复已通过或无备用模型可切，进入配图判断阶段。',
    },
    needs_visual_redraw: {
      label: '配图被拒，重绘',
      summary: '仅配图未通过答案保护被移除，要求主模型按反馈重绘配图。',
    },
    no_visual_redraw: {
      label: '无需重绘配图',
      summary: '不存在被移除的配图，继续检查是否缺少必要配图。',
    },
    needs_missing_visual: {
      label: '缺少所需配图，补画',
      summary: '文本过审但仍缺少教学所需配图（或用文字排版代图），由主模型补画。',
    },
    no_missing_visual: {
      label: '配图完整/无需配图',
      summary: '当前候选已满足交付要求，汇总返回。',
    },
    retry_missing_with_backup: {
      label: '主模型补图失败，切备用',
      summary: '主模型补图未达标且允许再试，改由备用模型补画配图。',
    },
    missing_attempt_done: {
      label: '补图尝试结束',
      summary: '主模型补图成功或无备用重试机会，汇总返回结果。',
    },
  },
};

export function edgeConditionDetail(
  workflowId: string,
  conditionId?: string,
) {
  if (!conditionId) return undefined;
  return edgeConditions[workflowId]?.[conditionId];
}

export function gateLogic(definition?: {
  implementation?: unknown;
  handler_id?: string;
}) {
  return definition?.implementation === 'code'
    ? gates[definition.handler_id ?? '']
    : undefined;
}
