import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:timezone/data/latest_all.dart' as tzdata;
import 'package:timezone/timezone.dart' as tz;

/// 把服务端给出的未来时刻交给系统。App 在后台或息屏时由系统弹出。
class CueNotifications {
  CueNotifications._();

  static final plugin = FlutterLocalNotificationsPlugin();
  static var ready = false;

  static Future<void> ensureReady() async {
    if (ready) return;
    tzdata.initializeTimeZones();
    const android = AndroidInitializationSettings('@mipmap/ic_launcher');
    const ios = DarwinInitializationSettings();
    await plugin.initialize(const InitializationSettings(android: android, iOS: ios));
    await plugin
        .resolvePlatformSpecificImplementation<AndroidFlutterLocalNotificationsPlugin>()
        ?.requestNotificationsPermission();
    await plugin
        .resolvePlatformSpecificImplementation<IOSFlutterLocalNotificationsPlugin>()
        ?.requestPermissions(alert: true, badge: false, sound: true);
    ready = true;
  }

  static Future<void> replace(Object? raw) async {
    if (raw is! List) return;
    await ensureReady();
    await plugin.cancelAll();
    final now = tz.TZDateTime.now(tz.UTC);
    for (final item in raw) {
      if (item is! Map) continue;
      final fireAt = DateTime.tryParse('${item['fire_at']}');
      final title = item['title'] as String?;
      final body = item['body'] as String?;
      final id = item['id'] as String?;
      if (fireAt == null || title == null || body == null || id == null) continue;
      final when = tz.TZDateTime.from(fireAt.toUtc(), tz.UTC);
      if (!when.isAfter(now)) continue;
      await plugin.zonedSchedule(
        id.hashCode & 0x7fffffff,
        title,
        body,
        when,
        const NotificationDetails(
          android: AndroidNotificationDetails(
            'study_cues',
            '学习提醒',
            channelDescription: '到点、休息和今日总结',
            importance: Importance.high,
            priority: Priority.high,
          ),
          iOS: DarwinNotificationDetails(),
        ),
        androidScheduleMode: AndroidScheduleMode.inexactAllowWhileIdle,
        uiLocalNotificationDateInterpretation: UILocalNotificationDateInterpretation.absoluteTime,
      );
    }
  }
}
