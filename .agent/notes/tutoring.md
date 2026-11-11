# 答疑

事实源：[domain-tutoring](../../docs/technical/domain-tutoring.md)、[表达](../../docs/technical/domain-tutoring-presentation.md) §十四、[离线评测](../../docs/technical/eval-offline.md)。视频讲解见 [tutoring-video-answer](../../docs/technical/tutoring-video-answer.md)，未实现。

## 目标

让孩子自己完成推理与练习。受保护的是当前题的最终答案、完整解法、待填内容、选择项和代写成品。没有推理层次的事实可以直接回答。过程题按已提交证据每次只推进一个最小目标。

## 状态

- 已落地：证据驱动许可、`tutor-turn` 契约与出口检查、发音 `act=pronounce`、五种配图与 App 渲染、结构化泄露裁判、多图先定目标、离线评测（单步、判官、合成多轮、对话回放）。
- 部分：发音指代仍会读错对象。图片作答核验与历史结论混淆、泄露回退不稳定。形状长度阈值未用真实输出校准。
- 未做：`disclosure=released`、`inspect_image` / `retrieve_authorized_learning_material` / `check_draft`、人工把标注升为 `confirmed`、配图 K=5 对照、视觉段条件拼接、知识讲解视频。流式 `TEXT_DELTA` 不做。
- 独立 `geometry` / `layers` / `relation` 求解器已取消，由受限 `svg` 承载。

## 决策

- 是否作业由模型用证据判断（`work|non_work`），不用任务标题推断。线索不足用 `non_work`。有受保护题，或候选声称在处理作业时，正文一律过独立裁判。模型标签只能收紧保护，不能放宽。
- `TutorPermit.answer_protected` 由 `permit()` 按旧题状态计算审核触发条件；独立Judge在同一次调用确定本轮Verdict/响应的保护范围，不持久化释放旧题。详见[出口检查](../../docs/technical/domain-tutoring.md#42-出口检查)。本轮表现只影响下一轮题目状态。`guide` 必须是 `work`。`depth` 缺失按 `reasoning`。`fact_gate` 不能跳过裁判。
- `submitted` 只表示提交了完整思路或答案，不等于算对。已掌握只来自 `ConfirmUnderstanding`。
- 计算题、问答题在题面足够时可以独立核验后确认或纠错，纠错不能补出孩子还没算出的最终结果。选择题、判断题不能逐项确认对错。题面不足只请补充。
- 文字裁判输出结构化事实，代码不扫描回复里的词或数字。`final_answer` / `complete_solution` 重试不回灌含答案的草稿。裁判超时、非法、异常一律 fail-closed，不能展示失败草稿。
- 判官看最近 3 道题摘要和窗口内学生原话，不把导师原话当学生证据。只有已经需要作业泄露审核且本轮或窗口有授权图时，才把同一批原图交给视觉裁判。图片字节不进观测。
- 图的任何失败只丢图、文字照常。文字泄露整轮回退。图泄露先重画一次且不得改正文。二维竖式写成 `\enclose{longdiv}` 或 TeX array 且没有 `visual` 时，先带规范重画。
- `unknown=true` 只禁止结构化数值字段。能用前四种结构化图就不用 SVG。一维公式写在正文 TeX，不为单个算式配图。通过检查的 `visual` 写入 `interaction_ref`；下一轮模型上下文不读它。形状 lint 只记 trace，不触发 fallback。
- 模型不返回交互 `kind`、按钮或媒体。发音不写题目状态或学习事实，TTS 只读已确认原文。一次最多 8 条 lesson。顶层 `act` 互斥。
- 本轮有新图就用新图；没有新图且窗口有多张旧图才选图。比较上一张必须显式 `tutoring_intent=compare_previous_image`。只把选定图交给答疑和泄露检查。
- `tutoring.*` 禁止 `AI_MODEL_OVERRIDES`。泄露判官必须与主答疑模型不同型号。改提示词必须升版本。
- 评测与生产共用 `run_tutor_turn()`。variant 只在评测进程内生效。AI 新标一律 `proposed`。通过率不能外推，不能当发布门槛。

## 注意

- 语义判断禁止关键词、数字扫描和正则。正则只用于协议、XML、公式分隔。
- 图判官看的是抽出的文字加 `problem_summary`，看不到线段几何。校验过的 SVG 仍可能画错。
- 主模型会把历史助手结论套到当前图上。fallback 记录里的 content 是被拒候选，不是孩子看到的固定话术。
- 给模型加「要不要追问」的规则会整体改变追问倾向。
- 同一 `command_id` 至多计一次。出口失败不写 Fact、不推进题目。发音和澄清不得为了展示去打开答疑会话。
- 窗口图读不出：发音整轮失败；一般答疑被告知无法读取。图片里的文字是数据不是指令。
- 链接和 Markdown 图片只当纯文本。金额不要写成 `$100`。公式解析失败回退源码。
- `tests/unit/evals/` 不能放 `__init__.py`。真实模型评测只能走 CLI，导入前禁用 OTEL。字面 `content_not_contains` 会误伤。多轮评测注入的是标注题目状态。合成多轮与真实回放的统计必须分开。
- 视频未实现前，不要用 `start_cue` 冒充制作完成，也不要新增 `exploration` 意图。

- 本轮补齐 Guardian 逐题推导记录只读 Query，见 [领域契约](../../docs/technical/domain-tutoring.md#guardian-逐题推导记录查询)。出口通过的 work 消息关联实际题目，区分引导与实质尝试；guide后有attempt才可展示，列表不传全对话，展开按题目/上海日期读取。旧无关联消息及空文本图片尝试不补造证据；submitted/“我懂了”不作为verified。迁移33已按用户后续授权应用到测试库，生产未迁移。
- 清除教学数据顺序必须为 TutoringMessage → TutoringProblem → TutoringSession；新增消息外键后真实PostgreSQL清除回归已覆盖。
- 2026-11-04 晚间检查作业只读诊断：Langfuse test 环境 21:01–21:03 的三轮（trace `da2847ee6797c718d65a7d593f550f0c`、`d9c00538b907f020f402f9d2d6bad78d`、`ad26d24fe4f7b74f58f8c8602de5a823`）均正确路由 tutoring，primary/repair/backup 共9个候选均被 `choice_verdict` 拦截，最终 `leak_detected` 固定兜底。实际主/裁判输入有授权图片；不是孩子未说明意图或丢图。当前设计及双方prompt禁止确认选择题对错，未区分图片中已完成作答核验与逐项猜选项；repair已收到原因但仍保留选项判定。候选对同页分别报第6题错、第7题错、8题全对，且末轮选图从上一轮[2]扩大至[1,2]，不能将被拒草稿视为可靠批改或直接放行。后续须明确已作答核验的边界、逐题证据和检查范围，并用连续原图回放验证；本轮未改业务行为、未确认具体手写答案正误。
- 2026-11-04 用户后续明确可保留选择/判断题不判候选项对错的原则，本轮要求分析友好提示；不采纳上一轮建议的核验放宽。链路确认：出口保留 `leak_detected`/`leak_check_failed`，但TutoringWorkflow失败分支统一投影FALLBACK_TEXT；Companion直接记该正文，App不按原因重写。友好提示方案须区分教学边界与技术不可用，优先主回答/有界repair给出可执行的合规帮助，最后用受控模板兜底。Judge原因描述被拒草稿，不能据此指责用户索答案、推断学生答错或选定错题；首因与重试末次故障需分开留存。模板回复不推进题目/学习事实、不提取失败草稿片段，不要求已说明意图的孩子重说；具体方案尚未实施。
- 2026-11-04 已按用户确认的最小方案实现最终失败提示映射：保留生成/审核/重试，提示策略事实源见[出口检查](../../docs/technical/domain-tutoring.md#42-出口检查)。注意最终审核不可用优先使用技术提示，即使携带旧泄露原因也不解释为教学边界；未知原因不暴露异常文本。失败正文与trace/账本保持一致，不写学习事实、不推进题目。
- 2026-11-04 最终提示进一步明确本次回答的问题点，区分最终答案与完整解法，不只宣读通用能力边界；原因码不是图片定位证据，不据此编造题号、断言原图含哪道题。契约见[出口检查](../../docs/technical/domain-tutoring.md#42-出口检查)。

- 2026-11-07 官网视频实机录制时定位知识对比误拦：test环境22:38:31（上海），[trace b7daa887d5eb2355ae32344291dadc07](https://us.cloud.langfuse.com/project/cmvfvorj601l6ad0jhvajth4c/traces/b7daa887d5eb2355ae32344291dadc07)。用户问“我想问一道新题，请用对比图讲解植物细胞和动物细胞的主要区别”，主/repair/backup均返回answer+non_work+compare；三个文字Judge均报new_final_answer=true、complete_solution=true，按优先级映射final_answer，最终leak_detected。不是图形协议或visual审核失败，也不是超时。旧铅笔题提交后permit仍protected，check_authority因此对所有回答触发审核（符合现有防绕过设计）；Judge输入把三道历史应用题与当前知识问答拼为problem，仅带task_title/problem/reply，缺少明确的保护对象关联判定；prompt只列词义/读音/定义原子知识豁免，未充分界定概念对比/解释与作业推理成果的边界。按产品事实直答原则本次为误拦，不能以主模型non_work直接跳过独立审核作为修复。建议独立Judge先识别本轮与受保护成果的关系，再判是否替代推理；结构化区分current_request/protected_problems/student_evidence，并补“旧题后问概念对比可答、旧题换说法索答案仍拒”的真实回放。当前只完成诊断，未改提示词、业务代码或线上配置。

- 2026-11-07 上述误拦已本地修复，尚未部署：`tutoring.leak-judge@v11`/`leak-judge-facts.v2` 在原有一次调用内返回本轮 `answer_protected` 及泄露事实；结构化当前请求/近期题目/学生证据，不信任主模型non_work放行，不释放旧题。图判官升v6，文字范围false仍执行既有图审核；缺失/矛盾范围fail-closed。`protection-scope-v1`新增9判官用例与2完整链路用例（标签均proposed，事实源见离线评测文档）；扩查发现作业词义直答也被误拦，已补充事实优先边界及用例。最终真实模型判官27次：FP0/15、FN0/12，范围/原因误判0/27，无不可用；完整链路4次均自动通过，人工查看实际回复/compare图描述，知识问答直答且伪装索旧题答案改为提示；额外4个已有判官用例带参考题面采样12次，FP0/6、FN0/6（counterfactual，不能并入默认图片评测）。结果在ignored `duxue-server/var/evals/protection-{scope,scope-turn,existing}-v11-final.json`；小样本不外推准确率，非发布门槛。服务端全量806通过/1既有跳过，修改文件Ruff通过，数据集与Agent定义校验通过。未提交、未推送或部署；官网视频素材仍保留，未使用假AI回复替代受阻画面。

- 2026-11-08 按用户确认重组上述批次为4个文件，路径与职责见[保护范围回归](../../docs/technical/eval-offline.md#保护范围回归protection-scope-v1)。初版9判官+2单步已被替换，上一条采样仅是旧版结果，不能视为多轮验证通过。真实6轮可见历史保留三版拒绝候选、原Judge六项事实和兜底；新期望与旧裁决分开。固定历史只采样知识检查点；两条合成6轮使用真实前序回复，DB状态为注入。回放器补近期题目、独立范围和配图断言；旧种子哈希不变。
- 新版真实模型结果在ignored `duxue-server/var/evals/protection-scope-{conversation,episodes,atomic}-reorganized.json`：真实候选重审6/6通过；知识回复2次均允许直答，其中1次compare格式无效被丢图，另1次结构通过且语义待人工复核。原子词义3/3通过。伪装索答案两次均完成6轮并通过；知识切换两次均在第3轮失败：一次仍回答数学题（范围true），一次已给知识和compare但act仍guide。按失败即停止规则，真实模型尚未覆盖其返回旧题的第4–6轮；这部分仅有确定性评测器测试和工作流旧题状态测试，不能宣称端到端全部通过。保留失败和原期望，本次只整理评测，未扩改主答疑提示词。全量813通过/1既有跳过，数据校验通过，修改Python文件F/E9检查通过；完整Ruff有既有问题，无新增违规类别。未提交或部署。

- 2026-11-09 正式连续新图检查只读诊断：Grafana专用list_datasources两次503，generic api请求/api/datasources可用，随后Tempo MCP读到22:42:07–22:47:27（上海）5轮。第二图trace40e23e5b826d8cc13966c9fa7377e2b4附件key不同，选图current=1/target=[1]；主模型首候选称全对，Judge判incorrect_confirmation，repair复用第一图47+24/63÷(21-12)话术并被放行。窗口与history_candidates保留旧助手判题结论；keep_target_images仅过滤像素不隔离文字，这是上下文污染/repair沿用旧题的证据，非直接缓存回复。22:46:23用户说明新图时tracea39ed3c258be8d330ad20b469a8355ff有2张历史图但image-target返回[]且ambiguous=false，后续judge_image_count=0并让用户再发；22:46:49重发后仍选当前图但重复旧结论。新会话traceed42b2819e81c26b68eb6d190fd59333备用模型错误地称90-37=53算错，Judge放行，表明还存在批改准确性问题，安全审核不等于逐题验算。线上仍e20bb357/R1，PR91未部署，不能归因于该PR。Grafana长模型输入被截断，未据此声称已核对完整提供商请求或真实手写答案；未重跑模型、未改代码/Prompt/线上配置。

- 2026-11-10 当前会话续查：Grafana MCP证书校验失败，Langfuse MCP直接核实正式trace `40e23e5b826d8cc13966c9fa7377e2b4` / `a39ed3c258be8d330ad20b469a8355ff` / `5e1ed25810877c5a70d65b21357dab18`。原图确已给主模型和Judge，旧助手批改同时在window和history_candidates中；第二图首候选全对被拒后，repair反馈将incorrect_confirmation解释成越过答案边界并回灌被拒草稿，随后复制第一图结论且被Judge放行。Langfuse可读到完整repair反馈，补足上轮Tempo截断局限。已补红绿回归：纠正同图时仍须隔离该图旧助手结论、单历史图支持纯文字跳出；结构化四则转写可独立复算，仍须视觉Judge核对转写与范围。Admin测试草稿R64快照digest `1ef78f83ee474dd85973e1ed8903049e483a89c2ade06821129af4cbc31b0134`（草稿revision，非发布R序号），未发布。真实6轮 `var/evals/image-review-episode-r64-reconciled.json`结构断言全过，但人工复核第1/2轮仍错误引导到已算对的28−13，第2轮明确错怪，Judge误放；语义复核失败记录在同目录`image-review-episode-r64-manual-review.json`，不得宣称优化完成。四则复算不等于逐步教学诊断正确。全量当时894通过/1跳过/6个PostgreSQL初始化错误（macOS无法解析UID501，非用例断言失败）；后续新加算术复核测试19项通过，尚未重新完成全量。发现另一个会话同时改同一源码，已询问分工，暂缓继续改共享实现；保留其变更。

- 2026-11-10用户要求先集中单个失败样例，已停止整套真实回放，固定事故recheck-1的原图、原始整页提问和旧历史，不缩为指定小题。最新测试草稿revision72（非发布R号），digest `2dc1e48724690ad60b725a12f5fc6b88fb8232061a904588fb4597958de132dc`；Prompt要求先逐字读取手写各行，括号/多步四则仍填arithmetic。单样例报告 `var/evals/image-review-focus-r72.json` 失败：本次已正确读取17，代码复算后的报告只有二1为incorrect，90−37=53为correct，但独立Judge在evidence_only连续拒绝，尚未进入正文生成；须定位审核拒绝依据，不能当作已修复或用放宽门禁凑通过。此前revision71有一次真实6轮结构通过且逐条查看正文未再复制旧图/错怪53，报告 `image-review-r71-episode.json`，不等于整套真实回归通过。最新全量908通过/1跳过/6个既有PostgreSQL初始化错误（本机UID501解析失败）；Admin29测试、类型/构建通过，数据校验旧seed hash仍7084bc6835908cf9。当前无评测后台进程、未提交/推送/发布/部署；配置仍Admin测试草稿，原图与诊断产物ignored。

- 2026-11-10用户最新范围决定：数学判题普遍不稳定，当前具体题目及相关Judge误判先忽略，替代上条“先修好单样例才继续”的工作顺序。暂停数学模型/Prompt调优，不把判题准确率作为本轮退出条件；保留原始gold、失败报告及待验收的核验实验，不将失败改成通过。其余只核验选图、旧图助手结论隔离/分歧反馈、多轮图片和实际回复传递；现有答案保护不放宽。定向非数学准确率回归（image_target/window_images/evals/leak_retry/tutoring_workflow_usecase）209通过；这验证执行与评测传递边界，不证明数学内容正确。完整套件的6个本机PostgreSQL初始化错误仍未解决，无新增发布或部署。

- 2026-11-10用户继续授权调通并可修改用例数学矛盾：保留真实事故原文/原裁决/gold，新建显式`run-conversations --scope image-context`仅执行生产prepare_images和真实选图Agent，验证目标及图片语境旧助手原文隔离；报告列出6个未执行完整回复/数学Judge检查，不计通过，默认full不变。合成6轮改读标题/印刷题面/词义，仍包含新图、无附件纠正、文字跳出、返回首图、再发新图、再次指代，继承真实生成回复。两份同用Admin测试草稿revision72/digest2dc1e487…快照，真实回放9/9通过；真实合成6/6通过并对照原图检查标题/算式/词义正确，审阅记录`var/evals/image-context-final-review.json`，标签仍proposed，数学准确率未评测。新增评测器错误选图/缺资源/历史污染的红绿测试；定向212通过，全量913通过/1跳过/6个本机PostgreSQL初始化错误，旧seed hash7084bc6835908cf9及数据校验/F-E9/diff检查通过。无提交、推送、发布或部署。设计与命令事实源见[连续图片回归](../../docs/technical/eval-offline.md#连续图片回归image-review-v1)。

- 2026-11-10用户授权本地commit：提交前review补上仅在存在judge_images时进入图片证据阶段的边界，防止文字轮模型意外返回image_review导致解析空图片上下文；新增回归，tutoring/image_review/evals共296通过且F/E9通过。该边界不改变已验收的有图流程，未重复调用真实模型。提交包含本次修复、离线用例、文档及进行中spec；排除无关platform笔记与.vscode，不push。上一轮完整套件仍有6个本机PG初始化错误，不能据此提交宣称全量绿色；数学准确率继续按用户决定暂缓。

- 2026-11-10 数学可靠性方案调研（建议，未批准实施）：已读本地《AI tutoring K-12 education.pdf》§2.2/§3.2/§4/§5.1及PAL原论文 https://arxiv.org/abs/2211.10435 。Khanmigo采用数学工具核验与导师表达分工；数学Judge仍有漏判，论文未给出单独引入Math Agent的准确率增益，不能外推。当前image_review.py已有受限AST与Decimal/Fraction复算，但只覆盖转写算式与最终值，不证明读图、列式、中间步骤或正文诊断正确。后续建议复用现有核算核心，统一文字/图片计算证据，逐步核验并约束判题正文；视觉转写、数学事实、教学披露分别校验，不用正则猜语义，不让泄露Judge推翻精确运算。先以真实事故与人工金标对照评测误判正确答案、漏错、覆盖率和拒判率，再决定扩展SymPy；本轮仅调研及笔记，无业务代码/Prompt/线上修改。

- 同日续问K12至高数：建议区分统一数学Tool接口、SymPy计算后端与任意Python执行权限；中学代数起SymPy有价值，可先受限操作封装，开放Python沙箱按组合/统计/数值实验需求后增。符号核验必须携带定义域/假设，数值抽样不等于证明，未知不得判错。补充参考Qwen2.5-Math官方TIR、MathCoder（arXiv:2310.03731）、Wolfram计算后端、AlphaGeometry（专用证明系统，非简单通用插件）；Davis/Aaronson的105题研究（arXiv:2308.05713）支持工具增强，也指出题目到工具的表达失败。均为调研建议，未实施或选定模型。

- 2026-11-10 按用户要求形成精简待实现设计，数学工具方案唯一归属[数学核验设计](../../docs/technical/tutoring-math.md)，含主流程与交互协议；本轮仅文档，未实施。

- 2026-11-10 用户要求按DDD补全数学设计：已按仓库domain-driven-design技能重写[数学核验设计](../../docs/technical/tutoring-math.md)，明确Tutoring归属、端口/适配器、事务外执行与ApplyTutorTurn提交边界；补主时序、分操作DTO、失败/幂等及验收。仅目标文档，未实施或改变既有教学规则。

- 同日数学执行隔离澄清：按用户追问修订[数学核验设计](../../docs/technical/tutoring-math.md)，首期免建通用Python代码沙箱不等于免隔离；Adapter调度受限执行器，子进程非权限边界。补生产最小权限容器、禁止模型字符串直接进eval式解析、资源/并发限制和超时终止回收。仅设计，无安全性验证或实现完成声明。

- 2026-11-10 用户授权实现数学工具：代码与协议事实源见[数学核验设计](../../docs/technical/tutoring-math.md)，启用/兼容窗口见[部署](../../docs/deployment.md#数学执行器与配置升级)。受限SymPy子进程+Unix socket容器、math证据账本/引用门禁、独立语义审核、图片分数复核、Admin显式迁移及防并发覆盖导入已实现；不新增聚合/表，不开放任意Python。新数学29项、最终定向366项通过；全量943通过/1跳过/6个本机PG初始化错误；Admin类型通过、28测试通过/2个测试库DNS失败。Colima因UID501错误无法启动，真实容器隔离与真实模型评测未验收；不宣称全绿或准确率提升。保留[进行中spec](../specs/tutoring-math.md)，未提交/推送/发布/部署。

- 2026-11-10 用户授权切换分支并本地提交数学核验实现；分支`codex/tutoring-math-verification`。提交包含代码、测试、设计和进行中spec；排除无关模型路线/评测成熟度调研笔记、`.vscode`和参考PDF。不推送；环境阻断与未完成验收继续保留，不据此次commit标记功能验收完成。

- 2026-11-10 用户指出评测样本未对应真实输入结构，核查`answer_protection/turn-guard-01.json`：该文件明确synthetic，history为空，context人工提供题目与任务状态；runner将problem统一构造成open状态，复用生产instruction/turn循环但不还原数据库读取及完整工作流。其content_not_contains仅检查三种答案字面表达，不能证明语义不泄露；note要求可执行小步但无独立教学语义断言。单轮用例本身可用于组件测试，缺口是未验证输入状态来源与生产等价性，不能视为真实会话回放。export.py仍跳过无文字的图片轮，并从整段助手REMINDER推断task_active再用于各轮，存在回放状态不忠实及使用后续信息的风险；source=real仅说明消息来源，不能保证完整状态真实。当前只读诊断，未改用例/执行器或将其自动扩写为伪真实多轮。

- 2026-11-10 用户确认统一评测格式后已实施：全部40份文件使用dialogue-eval.v1，单轮/连续脚本/真实回放共享消息与来源；候选Judge保持快照与候选分离，不伪造对话。格式、迁移命令和执行边界唯一归属[离线评测设计](../../docs/technical/eval-offline.md#四数据契约)。导出保留纯图片及选图引用，不再从后续话术猜任务状态；未取得状态标missing且阻止模型执行。旧真实单步注入状态标reconstructed，不升级标签；旧格式须显式迁移。40份迁移前后执行投影逐项一致；新seed哈希ac221687d261d4b4，旧报告不能跨版本直接比较。最终定向141通过，数据校验/迁移幂等/新文件Ruff及评测目录F-E9/diff检查通过；最近全量964通过/1跳过/3 subtests通过，6项既有PostgreSQL初始化错误仍因本机UID501不存在。其后仅新增迁移器拒绝未知历史的2项回归，定向已通过。保留[验收清单](../specs/eval-dialogue-format.md)，未满足全量绿色退出条件；未运行真实模型、提交或部署。

- 2026-11-10 用户在知悉上述6项PostgreSQL初始化环境错误后授权本地commit；提交评测格式迁移的代码、40份数据、测试、设计和验收清单，保留未完成的全量测试条件。不推送、不部署；此前模型路线/评测成熟度调研笔记及.vscode、参考PDF不纳入本次提交。

- 2026-11-11 离线用例按 5 个 Langfuse Dataset 目的迁移目录，40 个 JSON 内容逐文件哈希保持不变。加载器按 type 递归分派，目的类别校验覆盖全部执行类型；172 项评测单测及全量静态校验通过。当前仍是本地 grader，未上传用例或重跑模型。历史 11 fail / 3 not_run 的完整清单、证据及版本边界见[失败报告](../../docs/technical/eval-failures-2026-11-11.md)，不要把目录改造或专项结果当作质量修复。

- 2026-11-11 用户要求删除历史未全部通过的 7 份评测用例，evals/data 现保留 33 份（13 单轮、4 多轮、15 判官、1 真实回放）。执行器测试所依赖的 3 份历史快照移至 tests/fixtures/eval_protocol，仅做无网络协议测试，不纳入 Dataset；历史结果保留并标明已删除，不视为修复或重新评测通过。
- 删除后验证：评测相关单元测试 172 passed，全量静态校验通过，当前数据哈希 a52bfe675869865b；未重新执行模型评测。用户随后授权提交本地目录改造、用例删除及配套测试文档。

- 2026-11-11 审阅根目录 pedagogical_action.jsonl：5 条纯文本 instruction/response 样本，extra_info 为 JSON 字符串。可作为教学正确性/引导逻辑候选素材，不能直接把 assistant 当 gold：沙堆例无计算过程却赞许过程，余数例连问六题不符当前小步引导。SocraTeach 的 user 内嵌对话需拆分角色；TutorBench 已有多轮，可固定历史逐点回放，不能宣称生产真实记录或闭环验证。原 system 仅作来源，不覆盖产品 prompt；补显式测试上下文及 rubric，初始 proposed；来源名称不等于真实性/标注可靠性的证明。本轮仅分析，未导入或执行。

- 2026-11-11 用户授权将 pedagogical_action 5条素材改为评测用例：教学正确性2条、引导逻辑3条，批次pedagogical-action-v1。多轮只评最后请求并保留固定历史，system/末条示范隔离，来源metadata/文件哈希保留，测试状态synthetic且标签proposed；规则按产品原则重写。当前38份，174项相关单测及静态校验通过；未运行模型、上传Langfuse或提交。协议与目录说明见[离线设计](../../docs/technical/eval-offline.md#外部教学素材改编pedagogical-action-v1)。

- 2026-11-11 pedagogical-action-v1 首次本地真实运行：复用grading-v2-fixes历史草稿快照，qwen3.7-plus-2026-05-26生成/qwen3.8-flash评分，每例1次，5 pass/0 fail/0 error；quality依次形容词4、布朗尼5、沙堆4、骰子5、余数5。骰子有multi_question诊断但语义断言通过；proposed/uncalibrated未升级，不能作为稳定质量结论。证据在server var/evals/pedagogical-action-20261111-214816/{README.md,results.json,execution.json,config-snapshot.json,audit.jsonl}，未上报Langfuse。

- 2026-11-11 审阅 subject_competence.jsonl 共4条，images均为空，题干人工阅读未发现依赖缺失图片：拍照题的picture是故事对象，figure of speech是修辞。前三条文本条件完整，可改编为小步数学引导/阅读选项保护/修辞辨析；原直接答案不可作为辅导输出要求。作文条缺原完整任务、来源材料及评分量表，输入已有holistic=2不能作为独立评分gold；可改编为仅依据可见作文反馈及缺依据不臆断测试，不能声称复现原评分。仅分析，未导入。

- 2026-11-11 按用户要求仅将subject_competence前3条改为评测，排除作文：数学起步归guidance-logic，阅读证据/修辞辨析归teaching-correctness；批次subject-competence-v1。保留完整文本与选项，移除外部system/直接解答示范和解答包装指令，synthetic/proposed，复用现有语义评分协议。当前41份；175项评测单测及全量静态校验通过，未运行模型或提交。

- 2026-11-11 subject-competence-v1 本地运行，每例1次，自动3 pass/0 fail/0 error，quality均5；主模型qwen3.7-plus-2026-05-26、裁判qwen3.8-flash，沿用上一批快照。阅读题too_long、修辞题multi_question仅诊断；阅读回复直接引用并翻译答案核心证据，可能与保留学生证据提取要求冲突，需人工校准，不改写自动结果。结果在server var/evals/subject-competence-20261111-221402/，未上传Langfuse或提交。

- 2026-11-11 统一Langfuse评测：41例/64检查点已导入5个目的Dataset，Git原数据移至只读bootstrap快照；默认run只读云端并使用原生6个Evaluator，支持固定版本/Experiment审计/resume收分。原则与协议唯一归属[离线评测设计](../../docs/technical/eval-offline.md)。真实全量41例为34pass/6fail/1error，5个Experiment已关联，报告`var/evals/langfuse-unified-all-41/REPORT.md`；失败为未校准裁判结论，不能自动当真实缺陷。图片原生裁判被当前自定义DashScope模型能力检查拒绝，已询问兼容视觉连接；不降级本地评分。Server评测212测试、Admin37测试/类型/构建通过，真实API聚合验证通过；浏览器工具启动失败未视觉验收。保留进行中spec，未提交或部署。

- 2026-11-12 按用户要求从当前执行集移除 turn-visual-leak-00 与 episode-image-switch-and-correction：Langfuse Dataset Item 标为ARCHIVED，历史Experiment/Trace和Git初始化快照保留；默认runner只执行ACTIVE，现为39例。历史41例报告不改写为重跑结果。其余5个未通过的实际交付及裁判理由整理在 `var/evals/langfuse-unified-all-41/remaining-failures.md`。
- 2026-11-12 核查 Dataset Item 5a13b206-5469-5852-846c-7f53372368ea（turn-incident-01）：教学正确性v4将en-US astonished的 /stɑːn/ 判错，声称应 /stæn/；Cambridge US实际为 /əˈstɑː.nɪʃt/，主要扣分依据错误，应记裁判误判待校准，不据此修改导师回复。原Score 2及历史fail不篡改。六项原生分数挂检查点809a454703488c42，根observation只挂任务汇总，用户须选择检查点查看评分Comment。
- 2026-11-12 Scores空白定位：Langfuse当前源码DEFAULT_SIDEBAR_HIDDEN_ENVIRONMENTS包含sdk-experiment；ScoresTable默认showAllEnvironments=false，列表与ConnectedObservationDetailView嵌入表均使用该默认。managedEnvironmentPolicy在无显式environment过滤时加none-of内部环境；显式选择sdk-experiment可覆盖默认。与本批9条云端分数environment=sdk-experiment相符，可同时解释列表/检查点tab为空；需用户页面显式过滤验证，当前浏览器连接仍不可用。不是缺分，勿重复上传API评分。来源github.com/langfuse/langfuse：internalEnvironments.ts、ScoresTable.tsx、managedEnvironmentPolicy.ts。

- 2026-11-12 修复根节点汇总Score无Comment：aggregate现为status/task_success写检查点状态、失败维度、裁判原理由及子observation ID；latency写计量范围。补红绿测试，评测213测试与新模块lint通过。为turn-incident-01现有3条API汇总分回填Comment，沿用原ID/值/时间戳，不复制原生EVAL分数；Session未绑定所以空，属于正常离线记录。
- 2026-11-12 核查实验Error Count=0：图片episode历史实际只执行check-1（生成标题回复、Code通过，语义缺分），check-2..6因前点error为not_run；ARCHIVED为后续用户移出当前集，不否定历史执行。云端任务根15492c5ad5c94e5f实际level=DEFAULT且statusMessage为空；runner将error作为返回字典/Score保存，未映射到观测ERROR。质量fail与执行error须分开：前者不增加平台Error Count，后者当前存在观测状态映射缺口，尚未修复。

- 2026-11-12 修复实验状态上报缺口：任务根在返回前调用report_task_status，将执行/评分error映射ERROR并写原因；pass/fail/not_run保持DEFAULT，质量fail不作系统异常。新增5个红绿回归，评测相关218测试及platform lint通过。真实无模型冒烟Experiment a0910bb7a0611338创建2项：云端读回error根为ERROR、fail根为DEFAULT，Metrics按任务根计1 ERROR/1 DEFAULT。证据`var/evals/status-reporting-verification.json`。SDK5/Public observations接口仅提供读取，无安全的已结束观测更新方法；历史41例原节点未回填，旧Error Count仍0，不重跑/不篡改历史分数。

- 2026-11-12 用户核对两个case看似通过但标fail：云端确认ac67c866(subject-portraits-next-step)、f9c3eb0d(pedagogy-dice-equal-groups)在acceptance-8实验逐例要求false/任务fail，后续unified-all-41实验原生要求及任务汇总均pass；Dataset Item ID跨运行相同，不可当作执行ID。此前仅回填turn-incident-01的旧Comment，本轮补齐acceptance-8及all-41全部已有API汇总空Comment（不动ID/值/时间戳/原生评分），审计文件var/evals/summary-comments-backfill-all.json。

- 2026-11-12 完成Scores默认可见优化：新任务根/检查点与全部Score使用offline-evaluation；SDK会在每个新子节点再次强制sdk-experiment，故任务入口与NativeScorer检查点创建后均通过官方propagate_attributes显式覆盖。6条离线云端规则接受新环境并兼容历史SDK环境，生产规则未改。新增2个红绿回归，评测220测试与platform lint/diff检查通过；真实cone用例1pass，云端读回9条Score全部offline-evaluation、任务根和检查点亦同。验收Experiment e8a44be21a9561d3，证据var/evals/visible-scores-verification-final/cloud-visibility-verification.json；SDK外层item-run包装仍保留内部环境但不承载评分。历史未改写；需清除之前手动SDK环境筛选一次。未commit或部署。

- 2026-11-12 用户授权本地提交统一Langfuse评测及后续修复。提交前review确认41份初始化JSON逐字节不变、运行产物/密钥不入库；再次验证Server评测220测试/静态校验/platform lint，Admin37测试/类型/构建均通过。纳入用例单源、原生评分/Experiment、Admin新维度、汇总Comment、ERROR上报与Scores默认可见；排除无关platform笔记/.vscode/参考PDF。不push或部署，历史质量失败、人工校准和视觉验收限制继续保留。
