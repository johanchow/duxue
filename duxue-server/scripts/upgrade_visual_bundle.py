"""Create an unpublished visual-delivery draft from an explicit Admin export."""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

from app.agent_specs.admin_bundle import compile_bundle
from app.agent_specs.visual_delivery import VISUAL_NEED_SCHEMA

TUTOR = '''
[visual-delivery.v1]
本轮回答对象以instruction.student_said为准，recent_utterances/context是历史背景，不是当前提问。学生换题时必须切换到新题并relation=new；不能继续回答历史问题，不能把导师说过的推导当作学生已完成。先明确本轮题意再选择图。
主动视觉辅导（优先于旧的可选配图建议）：每轮先判断孩子卡在哪里。数量关系、空间排列、运动过程、点与间隔等用图更易理解时，主动输出真正的visual，不必等孩子会问；重复困惑时换表征，不重复文字。明确要求画图时本轮必须交付图，不能只教孩子自己画、承诺下轮画或问“要不要画”。简单事实/词义不强行配图。图展示题意、关系与当前最小一步，不代算尚未完成的最终答案或画完整解法；可用明确标注的局部小例子、未知量、省略号。数量和端点关系须正确。
线段/数轴能表达时用原生visual；二维空间/灯与间隔/点阵等需要实际位置时用svg（先调用widget_guidelines获取规范）。仅把文字步骤塞入steps不算几何示意图。SVG属性统一用单引号（如 <circle cx='100' cy='100' r='8'/>），外层JSON字符串用双引号；仅进行一次JSON编码，解码后的SVG属性引号前不得残留反斜杠。SVG标注用纯文本，不含LaTeX；正文简短指向图中一个可观察关系，只提出一个下一步。
作图前先确定对象清单与空间布局，完成后逐一核对：点阵的行数、列数、角点必须与实际绘制的对象一一对应；方阵保持正方形等距布局；路段的端点、灯和相邻间隔不能遗漏。不能用标题、alt、文字标注代替缺失的图形对象。局部图明确标注局部/小例子，不把未画出的对象算在图内。优先清晰的大号标注和简洁布局。
几何关系用细线和点表达，不用彼此分离的圆角文字框冒充相交边：共同角点必须同时落在两条相交线的端点上；道路两端的灯中心必须位于路段的真实端点，路段不得延伸到端灯之外。SVG优先直接使用画布绝对坐标，避免嵌套transform；所有图形及文字边界保留至少24单位内边距，绝不超出viewBox或彼此遮挡；图注置于图外留白区，标注字号至少18。优先只画当前需要观察的局部关系，明确标注“局部示意”，不用完整大点阵增加视觉负担。
图片是题意输入，不代替你的输出示意图。image_review只用于检查原图作答，不把自己新画的图放进image_review。非检查作答的请求可用not_checking且直接输出完整正文和visual。
'''
JUDGE = '''
[visual-delivery.v1]
除原有安全字段外，每次必须返回visual_need，取requested/helpful/not_needed/uncertain。独立依据problem.current_request及学生历史判断本轮教学需要，不信任导师是否自愿画图：学生明确要求图或继续修改图=requested；数量关系/空间排列/点与间隔等卡点明显能借图理解，或重复困惑需要换表征=helpful；简单事实/词义且图不增加理解=not_needed；题意缺失无法决定=uncertain。不要因为reply没有图、建议学生自己画或给了文字步骤而填not_needed。此字段只描述需求，无论回复是否已附图都填写；答案保护规则不变，不将需要图本身判为答案泄露。
先对照problem.current_request，候选正文和配图必须回答本轮题目；学生已从路灯换到方阵却继续画路灯时，即便路灯图本身正确也必须visual_adequate=false，visual_evidence指出答非所问。
另必须返回visual_adequate:boolean，独立检查problem.candidate_visual是否真的展示了本轮需要的关系：缺图=false；空间/点阵/点与间隔只返回文字步骤卡=false；图与题意/正文不符、端点重复/缺失、数量标注错误=false。真正准确展示关系的图=true。不靠图型名称直接判断，查看实际结构或SVG；不需要图时可false而不影响回复。
先返回visual_evidence:string，再返回visual_adequate。visual_evidence简述从真实图形对象获得的依据，不复述alt/title：SVG点阵须按circle/rect等对象的实际坐标核对行列数及角点；逐个确认实际对象数与标题/标注吻合（例如声明3行却只有2组纵坐标必须false）；线段图须核对端点、灯数和间隔数；只看文字宣称正确不能通过。无图填“无图”。不输出学生题目的最终答案。抽象关系图允许省略无关对象：若明确标注局部/示意且只解释角点共用或点与间隔关系，不要求画全题所有人/灯；只有声称完整行列或明确小例子的数量，才要求实际对象与声称一致。
校验几何与可见性：应用transform之后计算实际位置，图形/文字超出viewBox造成裁切、图注压在图形上、声称共用的角点没有同时落在横竖边上、声称两端装灯却让道路线延伸到首末灯之外，均visual_adequate=false，并在visual_evidence指出具体位置关系。不要因为内容有教育意义就忽略图形错误。
'''
REPAIR = '''独立教学审核确认本轮需要示意图，而当前没有可交付图。请保留当前题目与学生已知条件，输出完整候选JSON，必须含正确且不泄露答案的visual。选择能展示关系的原生图或SVG；不能只教孩子自己画或用文字步骤冒充示意图。SVG遵守已提供的widget_guidelines。若原文用了TeX竖式，改为真正的SVG竖式并移除该TeX标记。正文可改成简短读图提示，不替学生算最终结果。待修正草稿：{{draft}}'''


def upgrade(record):
    compile_bundle(record['bundle'])
    result = copy.deepcopy(record)
    files = result['bundle']['files']
    tutor, judge = files['agents/tutoring.turn.json'], files['gates/tutoring.leak-judge.json']
    for doc, addition in ((tutor, TUTOR), (judge, JUDGE)):
        if '[visual-delivery.v1]' not in doc['prompt']['template']:
            doc['prompt']['template'] = addition + '\n' + doc['prompt']['template']
    schema = judge['provider_output_schema']
    schema['properties']['visual_need'] = copy.deepcopy(VISUAL_NEED_SCHEMA)
    schema['properties']['visual_adequate'] = {'type': 'boolean'}
    schema['properties']['visual_evidence'] = {'type': 'string', 'maxLength': 500}
    if 'visual_need' not in schema['required']:
        schema['required'].append('visual_need')
    if 'visual_adequate' not in schema['required']:
        schema['required'].append('visual_adequate')
    if 'visual_evidence' not in schema['required']:
        schema['required'].append('visual_evidence')
    tutor['prompt']['fragments']['missing_visual']['template'] = REPAIR
    if 'tutoring.widget_guidelines' not in tutor['tools']:
        tutor['tools'].append('tutoring.widget_guidelines')
    result['migration_source'] = {key: record[key] for key in ('id', 'digest', 'kind', 'revision') if key in record}
    result['kind'] = 'draft'
    result['digest'] = compile_bundle(result['bundle']).digest
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    result = upgrade(json.loads(args.input.read_text()))
    with args.output.open('x') as output:
        output.write(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(result['digest'])
