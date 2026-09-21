# 左滑删除任务只改内存

日期：2026-09-21

- 现象：首页未排期任务左滑后消失，重新打开 App 又出现。`tasks` 行仍是 `open`。
- 根因：`WardDayPage` 只把 id 放进 `removedPoolTaskIds`，没有删除接口。
- 规避：左滑调用 `DELETE /wards/{ward_id}/assignments/{assignment_id}`，删除 `tasks` 行，并清掉日程与草稿里对该任务的引用。已有学习记录的任务返回 409，不删。
