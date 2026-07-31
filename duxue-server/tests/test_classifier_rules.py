"""分类层规则的回归测试。

用例描述模拟 VLM 在**真实机位**（侧后方 45° 俯拍、看不到正脸）下
会输出的 structured_fields 拼接结果，字段顺序与 scripts/0_quicktest.py
的 STRUCTURED_PROMPT 一致：

    hand_action / desk_objects / head_orientation /
    body_pos / seat_status / motion_state

改动 classifier/rules.yaml 后务必跑一遍：

    pytest duxue-server/tests/ -v
"""

import sys
from importlib import import_module
from pathlib import Path

import pytest

SERVER_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(SERVER_ROOT / "scripts"))


@pytest.fixture(scope="module")
def clf():
    return import_module("5_classify").RuleClassifier()


# (场景, 描述, 期望标签)
CASES = [
    ("书写", "右手握笔在练习本上书写 摊开的课本和铅笔 低头朝向桌面 端坐 在座位上 静止", "学习"),
    ("翻书", "手指翻页 摊开的书本 低头朝向桌面 上身前倾 在座位上 小幅活动", "学习"),
    ("持手机", "手持手机 桌面有手机和合拢的课本 低头朝向手机 后靠椅背 在座位上 静止", "走神/玩耍"),
    ("玩玩具", "双手摆弄一个玩具 课本被推到一边 低头 端坐 在座位上 小幅活动", "走神/玩耍"),
    ("转头", "双手空置离开桌面 摊开的课本 头部转向侧方 身体扭转 在座位上 大幅移动", "走神/玩耍"),
    ("趴睡", "双臂交叉作枕 摊开的课本 头枕在手臂里 趴在桌上 在座位上 静止", "走神/玩耍"),
    ("无人", "不可见 桌面留着书本和文具 不可见 不可见 不在画面中 不可见", "离开"),
    ("空座", "不可见 桌面留着课本 不可见 座位空置 已离座 不可见", "离开"),
]


@pytest.mark.parametrize("scene,desc,expected", CASES, ids=[c[0] for c in CASES])
def test_rule_classification(clf, scene, desc, expected):
    label, _ = clf.classify(desc)
    assert label == expected, f"{scene}：期望 {expected}，实际 {label}"


def test_leave_keywords_are_specific_enough(clf):
    """「离开」的关键词不能宽泛到误匹配手部或桌面描述。

    回归用例：曾用过泛化的「空置」，导致"双手空置"被判为离开——
    离开规则 priority 最高，会直接抢在走神规则之前命中。
    """
    label, _ = clf.classify("双手空置放在腿上 摊开的课本 头部转向侧方 端坐 在座位上 静止")
    assert label != "离开"


# 下面两条是 qwen3-vl-flash 在 data/frames 上跑出的真实输出，原样保留
# 措辞。它们都曾被判成「走神/玩耍」，根因是七个字段拼成一句后，
# desk_objects 里的静物"手机"与 hand_action 里的动作"手机"无法区分。
REAL_BADCASES = [
    (
        "看网课时桌上摆着手机",
        {
            "hand_action": "双手交叠置于桌面，左手腕佩戴智能手表，右手自然搭在左手上，无明显操作动作",
            "desk_objects": "平板电脑支架立于右侧，屏幕显示教学视频；前方摊开课本与练习册；左侧有透明收纳袋、手机、沙漏；右侧笔筒内插多支笔及文具；右下角摆放粉色兔子玩偶与小日历",
            "head_orientation": "头部微侧向右前方，面向平板电脑方向",
            "body_pos": "上身端正，肩部放松，略微前倾面向屏幕",
            "seat_status": "坐在木质椅子上，椅背可见，身体稳定未移位",
            "motion_state": "静止状态，无明显肢体移动，仅可能随视频内容轻微调整坐姿",
            "desc_summary": "学生正端坐于书桌前，面向平板电脑观看线上课程，双手静置桌面，环境整洁有序",
        },
        "学习",
    ),
    (
        "写作业时手机架在桌上",
        {
            "hand_action": "右手执蓝色钢笔在摊开的笔记本上书写，左手轻按纸面固定",
            "desk_objects": "木质桌面摆放有打开的书本、墨水瓶、手机支架上的手机、抽屉内露出多支彩色笔",
            "head_orientation": "头部自然侧倾，朝向桌面方向",
            "body_pos": "身体后靠于床头软垫，上身略微前倾以配合书写动作",
            "seat_status": "坐在床上，背部倚靠床头板，身体位于画面右侧区域",
            "motion_state": "手部有持续书写动作，身体基本保持稳定，无明显大幅位移",
            "desc_summary": "一名学生侧坐于床上，正低头用右手执笔在笔记本上书写，桌面布置学习用品，整体姿态放松但专注",
        },
        "学习",
    ),
]


@pytest.mark.parametrize(
    "scene,fields,expected", REAL_BADCASES, ids=[c[0] for c in REAL_BADCASES]
)
def test_desk_objects_do_not_drive_behavior(clf, scene, fields, expected):
    """桌面静物不得参与行为判定。

    书桌上摆着手机或平板是常态，若静物清单参与匹配，孩子只要在这样的
    桌子前写作业就会被永久判成走神——这类误判还会一路传导到日报统计。
    """
    label, _ = clf.classify(fields)
    assert label == expected, f"{scene}：期望 {expected}，实际 {label}"


def test_real_phone_usage_still_detected(clf):
    """反向保证：手里真的拿着手机时，仍要判为走神。

    上一条测试排除的是静物干扰，不能顺手把真实信号一起排除掉。
    """
    label, _ = clf.classify(
        {
            "hand_action": "双手捧着手机，拇指在屏幕上滑动",
            "desk_objects": "摊开的作业本、笔袋、台灯",
            "head_orientation": "低头朝向手中的手机",
            "body_pos": "后靠椅背，上身放松",
            "seat_status": "在座位上",
            "motion_state": "手指持续小幅活动",
            "desc_summary": "学生后靠在椅子上双手玩手机，作业本摊开未动",
        }
    )
    assert label == "走神/玩耍"


def test_references_do_not_depend_on_gaze():
    """机位约束：分类配置不得依赖眼睛、视线或面部表情。

    摄像头在侧后方 45° 俯拍，看不到正脸。任何依赖目光的参考短句
    在真实素材上都不可能命中，会静默拉低准确率。
    """
    import yaml

    banned = ["目光", "视线", "眼神", "注视", "眼睛", "表情"]

    for name in ("categories.yaml", "rules.yaml"):
        text = (SERVER_ROOT / "classifier" / name).read_text(encoding="utf-8")
        # 去掉注释行——头部说明里会提到这些词以解释为什么禁用
        body = "\n".join(
            line for line in text.splitlines() if not line.lstrip().startswith("#")
        )
        for word in banned:
            assert word not in body, f"{name} 中仍存在依赖目光的表述：{word}"
