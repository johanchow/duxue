type CodeLogic = { title: string; summary: string };

const actions: Record<string, Record<string, CodeLogic>> = {
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
    'tutoring.turn': {
      title: '准备答疑上下文',
      summary:
        '读取本轮问题、授权图片和已有题目状态。需要判断指代图片时，先进入图片定位，再把选定题面交给答疑流程。',
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
      summary:
        '生成孩子看到的回复和下一步交互。正常辅导按规则保存本轮记录，发音和澄清可直接返回，审核失败时使用安全兜底。',
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

export function gateLogic(definition?: {
  implementation?: unknown;
  handler_id?: string;
}) {
  return definition?.implementation === 'code'
    ? gates[definition.handler_id ?? '']
    : undefined;
}
