/// 首页任务卡片是读模型：安排状态来自 Task，进行中和暂停来自未结束的 StudySession。
enum HomeTaskCardKind { unscheduled, scheduled, inProgress, paused, completed }

HomeTaskCardKind homeTaskCardKind(Map<String, dynamic> item) {
  final taskStatus = item['status'] as String?;
  final session = item['session'];
  final sessionStatus =
      session is Map ? session['status'] as String? : null;
  if (taskStatus == 'completed') return HomeTaskCardKind.completed;
  if (sessionStatus == 'active') return HomeTaskCardKind.inProgress;
  if (sessionStatus == 'paused') return HomeTaskCardKind.paused;
  if (taskStatus == 'scheduled') return HomeTaskCardKind.scheduled;
  return HomeTaskCardKind.unscheduled;
}

String homeTaskCardLabel(HomeTaskCardKind kind) => switch (kind) {
      HomeTaskCardKind.unscheduled => '未排期',
      HomeTaskCardKind.scheduled => '已排期',
      HomeTaskCardKind.inProgress => '进行中',
      HomeTaskCardKind.paused => '暂停',
      HomeTaskCardKind.completed => '已完成',
    };
